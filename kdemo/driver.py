"""Live runs: one Retrievr run per row, told as the steps of the diagram.

The :class:`Tracker` turns what can be seen from outside (requests sent, AI calls,
Retrievr's events) into steps; :class:`SiteRunner` sets up Retrievr with those observers
and builds the row's result. Retrievr itself is used through its public API only.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from retrievr import Retrievr
from retrievr.config import OutputSettings, Settings, StateSettings, load_settings
from retrievr.events import Event
from retrievr.fetch import HostSession

from kdemo.adapter import PortalAdapter
from kdemo.config import DemoConfig, Prices
from kdemo.observe import AICall, AICallTap, NetworkTransport, ObservingTransport
from kdemo.sheet import SiteRow

Emit = Callable[[dict[str, Any]], None]

# The diagram's main path for each branch; missing steps are filled in this order.
LEARN_PATH = ["learn", "read", "health", "classify", "download", "store"]
REPLAY_PATH = ["replay", "read", "health", "classify", "download", "store"]
REPAIR_PATH = ["replay", "read", "health", "repair", "verify", "classify", "download", "store"]
FILED = ("downloaded", "known_url", "duplicate_content")
CHECKS = [
    ("anchors", "Every reference document is found"),
    ("known_documents", "95% of known documents are still there"),
    ("volume", "The volume stays plausible"),
    ("domains", "Everything stays on the issuer's site"),
    ("deterministic", "Two runs give the same result"),
]


class Tracker:
    """Steps of one row's run, from the signals observed while it runs."""

    def __init__(self, row: SiteRow, emit: Emit, prices: Prices) -> None:
        self.row = row
        self._emit = emit
        self.prices = prices
        self.steps: list[str] = []
        self.branch = "replay"
        self.pages = 0
        self.found: int | None = None
        self.repairing = False
        self.repaired = False
        self.degraded = False
        self.ai_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost = 0.0
        self.downloads: dict[str, int] = {}
        self.rejected = ""
        """Why a learned recipe failed validation (failed checks), when it did."""

    def emit(self, kind: str, **data: Any) -> None:
        self._emit({"type": kind, "row": self.row.id, **data})

    def step(self, name: str, **data: Any) -> None:
        if name in self.steps:
            return
        self.steps.append(name)
        self.emit("step", step=name, **data)

    @property
    def path(self) -> list[str]:
        if self.branch == "learn":
            return LEARN_PATH
        return REPAIR_PATH if self.repairing or self.repaired or self.degraded else REPLAY_PATH

    def through(self, target: str) -> None:
        """Every step of the path up to ``target``, in order (those already passed are kept)."""
        for name in self.path:
            if name not in self.steps:
                self.step(name, **self._defaults(name))
            if name == target:
                return

    def _defaults(self, name: str) -> dict[str, Any]:
        if name == "read":
            return {"pages": self.pages, "found": self.found}
        if name == "health":
            return {"verdict": "baseline" if self.branch == "learn" else "ok"}
        return {}

    # -- signals -----------------------------------------------------------------------

    def start(self) -> None:
        self.step("site", url=self.row.url, request=self.row.request)
        self.step("access", private=self.row.private)

    def known(self, known: bool, relearn: bool) -> None:
        self.branch = "replay" if known else "learn"
        self.step("known", known=known, relearn=relearn)
        self.step(self.branch)

    def on_request(self, request: httpx.Request) -> None:
        if request.url.path.endswith("/robots.txt") or "download" in self.steps:
            return
        self.pages += 1
        if self.branch == "replay" and not self.repairing and "health" not in self.steps:
            self.step("read", pages=self.pages)
        self.emit("pages", n=self.pages)

    def link(self) -> str:
        if self.branch == "learn" and "read" not in self.steps:
            return "a1"
        return "a2" if self.repairing else "a3"

    def on_ai_start(self, _request: httpx.Request) -> None:
        link = self.link()
        if link == "a3":
            self.through("classify")
        self.emit("ai_start", link=link)

    def on_ai_call(self, call: AICall) -> None:
        link = self.link()
        cost = 0.0 if call.cached else self.prices.cost(call.input_tokens, call.output_tokens)
        if not call.cached:
            self.ai_calls += 1
            self.tokens_in += call.input_tokens
            self.tokens_out += call.output_tokens
            self.cost += cost
        self.emit(
            "ai_end",
            link=link,
            step=call.step,
            cached=call.cached,
            input_tokens=0 if call.cached else call.input_tokens,
            output_tokens=0 if call.cached else call.output_tokens,
            cost=cost,
        )

    def on_event(self, event: Event) -> None:
        data = dict(event.data)
        if event.kind == "health_alert":
            verdict = str(data.get("verdict", ""))
            if verdict == "broken":
                self.repairing = True
                self.through("read")
                self.step("health", verdict=verdict, changed=True, summary=event.message)
                self.step("repair")
            else:
                self.through("read")
                self.step("health", verdict=verdict, changed=False, summary=event.message)
        elif event.kind == "recipe_rejected" and self.repairing:
            self.emit("repair_attempt", rung=data.get("rung"), passed=False)
        elif event.kind == "recipe_rejected":
            self.rejected = event.message
            self.emit("notice", kind="rejected", text=event.message[:300])
        elif event.kind == "recipe_repaired":
            self.repairing, self.repaired = False, True
            self.step("verify", passed=True)
            self.emit("checks", passed=True, checks=[{"name": n, "label": l, "passed": True} for n, l in CHECKS])
        elif event.kind == "site_degraded":
            self.repairing, self.degraded = False, True
            self.step("verify", passed=False)
            self.emit("checks", passed=False, checks=[])
        elif event.kind == "recipe_learned":
            self.found = int(data.get("documents", 0)) or None
        elif event.kind == "document_downloaded":
            total = int(data.get("total", 0))
            if "download" not in self.steps:
                if self.found is None:
                    self.found = total
                self.through("download")
            status = str(data.get("status", ""))
            self.downloads[status] = self.downloads.get(status, 0) + 1
            reason = re.search(r"\((.*)\)\s*$", event.message) if status not in FILED else None
            self.emit(
                "doc",
                index=int(data.get("index", 0)),
                total=total,
                status=status,
                label=self.doc_label(event.message, status),
                reason=reason.group(1)[:200] if reason else "",
            )
        elif event.kind == "blocked":
            self.emit("notice", kind=event.kind, text=re.sub(r" at https?://\S+", "", event.message)[:200])
        elif event.kind in ("unauthorized", "budget_exceeded", "llm_error"):
            self.emit("notice", kind=event.kind, text=event.message[:200])

    def doc_label(self, message: str, status: str) -> str:
        """A short card label from the file path Retrievr reports (type and period)."""
        if self.row.private:
            return "Fund document"
        m = re.search(r":\s+(\S+\.\w{2,5})", message)
        if not m or status not in FILED:
            return "Document"
        stem = PurePosixPath(m.group(1).replace("\\", "/")).stem
        parts = [p for p in stem.split("_") if p and p.lower() not in ("en", "fr", "de", "es", "it")]
        text = " ".join(parts).replace("-", " ")
        return (text[:1].upper() + text[1:])[:40] or "Document"


class NoAITransport(httpx.BaseTransport):
    """For private portals: no portal data ever reaches an AI (same rule as Kraken's collect)."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("AI disabled for private portals", request=request)


class SiteRunner:
    """Runs rows with Retrievr, observed by a :class:`Tracker`.

    Private rows run like the host's own collection: with the host's session, no AI (no
    request to compile, no repair) and the host's state and output folders."""

    def __init__(self, cfg: DemoConfig, emit: Emit, adapter: PortalAdapter | None = None) -> None:
        self.cfg = cfg
        self._emit = emit
        self.adapter = adapter

    def settings(self, *, fresh_ai: bool, row: SiteRow | None = None) -> Settings:
        cfg = self.cfg
        if cfg.retrievr_config is not None and cfg.retrievr_config.is_file():
            settings = load_settings(cfg.retrievr_config)
        else:
            settings = Settings()
        state_dir, output_dir = cfg.state_dir, cfg.output_dir
        dirs = getattr(self.adapter, "retrievr_dirs", None)
        if row is not None and row.private and dirs is not None:
            state_dir, output_dir = dirs(row)
        update: dict[str, Any] = {}
        if state_dir is not None:
            update["state"] = StateSettings(state_dir=state_dir)
        if output_dir is not None:
            update["output"] = OutputSettings(output_dir=output_dir)
        if fresh_ai:
            update["llm"] = settings.llm.model_copy(update={"cache": "off"})
        return settings.model_copy(update=update) if update else settings

    def is_known(self, row: SiteRow) -> bool:
        r = Retrievr(settings=self.settings(fresh_ai=False, row=row))
        return r.store.active_recipe(row.id) is not None

    def run(self, row: SiteRow, *, relearn: bool = False) -> dict[str, Any]:
        tracker = Tracker(row, self._emit, self.cfg.prices)
        started = time.monotonic()
        tracker.emit("run_start", name=row.name, private=row.private, source="live")
        tracker.start()
        session: HostSession | None = None
        try:
            if row.private:
                tracker.step("auth")
                if self.adapter is None:
                    return self._end(tracker, row, started, "Sign-in refused",
                                     notes="no private-portal adapter configured")
                try:
                    session = self.adapter.open_session(row)
                except Exception as exc:  # the adapter says why; never a secret
                    return self._end(tracker, row, started, "Sign-in refused", notes=str(exc)[:200])
            if row.private:
                relearn = False  # private portals run hand-written recipes only
            known = not relearn and (row.private or not row.force_learn) and self.is_known(row)
            tracker.known(known, relearn or row.force_learn)
            if row.private and not known:
                return self._end(tracker, row, started, "No recipe",
                                 notes=f"no recipe installed for site '{row.id}'")
            learning = not known
            if self.cfg.redownload and not row.private:
                self.forget_files(row)
            retrievr = self._retrievr(tracker, session, row, fresh_ai=learning and self.cfg.fresh_ai_on_learn)
            with AICallTap(tracker.on_ai_call):
                if learning:
                    result: Any = retrievr.learn(
                        row.url, row.request or None, issuer=row.id,
                        years=row.years or None, download=True,
                    )
                else:
                    result = retrievr.run(
                        row.id, request=None if row.private else (row.request or None),
                        years=row.years or None, download=True, repair=not row.private,
                    )
            return self._finish(tracker, row, started, result, learning)
        finally:
            if session is not None and self.adapter is not None:
                try:
                    self.adapter.close_session(session)
                except Exception:
                    pass

    def files_dir(self, row: SiteRow) -> Path | None:
        """The folder holding the files filed for this row (``<output>/<issuer>``), or
        None when nothing was filed yet."""
        settings = self.settings(fresh_ai=False, row=row)
        out = Path(settings.output.output_dir).resolve()
        recipe = Retrievr(settings=settings).store.active_recipe(row.id)
        for name in ([recipe.issuer] if recipe is not None else []) + [row.id]:
            folder = (out / name).resolve()
            if out in folder.parents and folder.is_dir() and any(folder.rglob("*.*")):
                return folder
        return None

    def forget_files(self, row: SiteRow) -> int:
        """Delete the files Retrievr filed for this row's issuer in the demo's output folder
        (read from its manifest). Retrievr then downloads them again: a file missing from
        disk is never treated as known. Returns the number of files deleted."""
        settings = self.settings(fresh_ai=False, row=row)
        out = Path(settings.output.output_dir).resolve()
        manifest = out / "manifest.json"
        if not manifest.is_file():
            return 0
        # A re-learned site files under its row id, a hand-written recipe under its issuer:
        # both, since the manifest knows documents by URL whatever folder they are in.
        recipe = Retrievr(settings=settings).store.active_recipe(row.id)
        issuers = {row.id} | ({recipe.issuer} if recipe is not None else set())
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8")).get("documents", [])
        except (OSError, ValueError):
            return 0
        deleted = 0
        for entry in entries:
            if entry.get("issuer") not in issuers or not entry.get("path"):
                continue
            path = (out / entry["path"]).resolve()
            if out in path.parents and path.is_file():  # never outside the output folder
                path.unlink()
                deleted += 1
        return deleted

    def _retrievr(self, tracker: Tracker, session: HostSession | None, row: SiteRow, *,
                  fresh_ai: bool) -> Retrievr:
        llm: httpx.BaseTransport
        if row.private:
            llm = NoAITransport()
        else:
            inner_llm = self.adapter.llm_transport() if self.adapter is not None else None
            llm = ObservingTransport(inner_llm or NetworkTransport(), tracker.on_ai_start)
        kwargs: dict[str, Any] = {}
        if session is not None:
            watched = ObservingTransport(session.transport, tracker.on_request, owns_inner=False)
            kwargs["session"] = HostSession(transport=watched, values=session.values)
        else:
            kwargs["fetch_transport"] = ObservingTransport(NetworkTransport(), tracker.on_request)
        return Retrievr(
            settings=self.settings(fresh_ai=fresh_ai, row=row),
            on_event=tracker.on_event,
            llm_transport=llm,
            **kwargs,
        )

    def _finish(self, tracker: Tracker, row: SiteRow, started: float, result: Any, learning: bool) -> dict[str, Any]:
        status = result.status
        failed = "; ".join(p for p in tracker.rejected.split("; ") if "FAIL" in p)
        notes = "; ".join(x for x in [failed, *result.errors, *result.warnings] if x)[:400]
        if status in ("blocked", "unauthorized", "error", "no_recipe", "budget_exceeded", "rejected"):
            label = {"blocked": "Blocked", "unauthorized": "Sign-in refused", "no_recipe": "No recipe",
                     "rejected": "Not validated", "budget_exceeded": "Over budget"}.get(status, "Error")
            return self._end(tracker, row, started, label, notes=notes, result=result)
        if status == "degraded":
            return self._end(tracker, row, started, "Degraded", notes=notes, result=result)
        downloads = getattr(result, "downloads", []) or []
        if result.documents and downloads and not any(d.status in FILED for d in downloads):
            # Listed but not one file saved: never shown as a success.
            failed = next((d for d in downloads if d.status not in FILED), None)
            why = f"{failed.status}: {failed.reason}" if failed is not None else ""
            return self._end(tracker, row, started, "Not downloaded",
                             notes="; ".join(x for x in [why, notes] if x)[:400], result=result)
        tracker.through("store")
        label = "Learned" if learning else ("Repaired" if tracker.repaired else "Done")
        return self._end(tracker, row, started, label, notes=notes, result=result)

    def _end(self, tracker: Tracker, row: SiteRow, started: float, label: str, *,
             notes: str = "", result: Any = None) -> dict[str, Any]:
        downloads = getattr(result, "downloads", []) if result is not None else []
        statuses = [d.status for d in downloads]
        health = getattr(result, "health", None)
        if label == "Learned":
            health_label = "New recipe"
        elif label == "Repaired":
            health_label = "Repaired"
        elif label == "Done":
            verdict = health.verdict if health is not None else "ok"
            health_label = {"ok": "Good", "stale": "Good", "suspect": "Suspect"}.get(verdict, verdict.title())
        else:
            health_label = label
        res = {
            "status_label": label,
            "recipe_label": {"Learned": "Learned", "Repaired": "Repaired", "Done": "Known"}.get(label, ""),
            "found": len(getattr(result, "documents", []) or []) if result is not None else None,
            "files": sum(1 for s in statuses if s in FILED) if result is not None else None,
            "new": statuses.count("downloaded") if result is not None else None,
            "ai_calls": tracker.ai_calls,
            "tokens": tracker.tokens_in + tracker.tokens_out,
            "cost": round(tracker.cost, 6),
            "seconds": round(time.monotonic() - started, 1),
            "health_label": health_label,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "notes": notes,
            "pages": tracker.pages,
        }
        tracker.emit("run_end", result=res)
        return res

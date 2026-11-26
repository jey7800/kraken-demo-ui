"""Recorded runs ("films"): every live run is saved, and can be played back offline.

A film is the list of events a live run emitted, with their times. Playing it emits
the same events again, so the page cannot tell a film from a live run, except that
long waits are shortened and the speed can be changed.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Emit = Callable[[dict[str, Any]], None]
DOC_MAX_GAP_S = 0.25
GOOD = ("Done", "Learned", "Repaired")


def film_kind(events: list[dict[str, Any]]) -> str:
    """``learn`` when the run learned the site, else ``replay``."""
    for e in events:
        if e.get("type") == "step" and e.get("step") == "learn":
            return "learn"
    return "replay"


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "site"


@dataclass
class Recorder:
    """Collects the events of one row's live run."""

    row: dict[str, Any]
    started: float = field(default_factory=time.monotonic)
    events: list[dict[str, Any]] = field(default_factory=list)

    def add(self, event: dict[str, Any]) -> None:
        self.events.append({"dt": round(time.monotonic() - self.started, 3), "event": event})

    def save(self, films_dir: Path) -> Path | None:
        plain = [e["event"] for e in self.events]
        end = next((e for e in plain if e.get("type") == "run_end"), None)
        if end is None or end.get("result", {}).get("status_label") not in GOOD:
            return None  # a failed live run never replaces a good recording
        films_dir.mkdir(parents=True, exist_ok=True)
        kind = film_kind(plain)
        path = films_dir / f"{_safe(self.row['id'])}.{kind}.json"
        film = {"row": self.row, "kind": kind, "recorded": time.strftime("%Y-%m-%d %H:%M"),
                "events": self.events}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(film, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
        return path


class FilmLibrary:
    def __init__(self, films_dir: Path) -> None:
        self.dir = films_dir

    def path(self, row_id: str, kind: str) -> Path:
        return self.dir / f"{_safe(row_id)}.{kind}.json"

    def available(self) -> dict[str, list[str]]:
        """Row id -> kinds recorded."""
        out: dict[str, list[str]] = {}
        if not self.dir.is_dir():
            return out
        for p in sorted(self.dir.glob("*.json")):
            m = re.fullmatch(r"(.+)\.(learn|replay)\.json", p.name)
            if m:
                out.setdefault(m.group(1), []).append(m.group(2))
        return out

    def load(self, row_id: str, prefer: str) -> dict[str, Any] | None:
        for kind in (prefer, "replay" if prefer == "learn" else "learn"):
            p = self.path(row_id, kind)
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        return None


def play(
    film: dict[str, Any],
    row_id: str,
    emit: Emit,
    *,
    speed: Callable[[], float],
    cancelled: Callable[[], bool],
    max_gap_s: float = 1.5,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """Emit the film's events again for ``row_id``; returns the recorded result."""
    previous = 0.0
    result = None
    for item in film.get("events", []):
        if cancelled():
            return None
        event = dict(item["event"])
        gap = max(0.0, float(item["dt"]) - previous)
        previous = float(item["dt"])
        cap = DOC_MAX_GAP_S if event.get("type") == "doc" else max_gap_s
        wait = min(gap, cap) / max(speed(), 0.1)
        if wait > 0:
            sleep(wait)
        event["row"] = row_id
        if event.get("type") == "run_start":
            event["source"] = "film"
        if event.get("type") == "run_end":
            result = {**event.get("result", {}), "source": "film", "recorded": film.get("recorded")}
            event["result"] = result
        emit(event)
    return result

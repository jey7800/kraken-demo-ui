"""Local web server: the page, a JSON API and a Server-Sent Events stream.

Standard library only; bound to 127.0.0.1. One job (a list of rows) runs at a time in a
background thread; every event it emits goes to all open pages.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import queue
import subprocess
import sys
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from kdemo.adapter import PortalAdapter
from kdemo.config import DemoConfig
from kdemo.driver import SiteRunner
from kdemo.films import FilmLibrary, Recorder, play
from kdemo.sheet import Sheet, SheetError, export, read_sheet

log = logging.getLogger("kdemo")
STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_UPLOAD = 10 * 1024 * 1024
# The Windows registry may map these to something else.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


class EventBus:
    def __init__(self) -> None:
        self._subs: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=5000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:  # a stalled page must not block a run
                pass


class App:
    def __init__(self, cfg: DemoConfig, adapter: PortalAdapter | None) -> None:
        self.cfg = cfg
        self.bus = EventBus()
        self.adapter = adapter
        self.films = FilmLibrary(cfg.films_dir)
        self.sheet: Sheet | None = None
        self.results: dict[str, dict[str, Any]] = {}
        self.speed = 1.0
        self._job: threading.Thread | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self._restore()

    # -- persistence -------------------------------------------------------------------

    def _restore(self) -> None:
        meta = self.cfg.data_dir / "current.json"
        if not meta.is_file():
            return
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            data = (self.cfg.data_dir / info["stored"]).read_bytes()
            self.sheet = read_sheet(info["filename"], data)
            results = self.cfg.data_dir / "results.json"
            if results.is_file():
                self.results = json.loads(results.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as exc:
            log.warning("previous parameters file not restored: %s", exc)

    def _save_results(self) -> None:
        path = self.cfg.data_dir / "results.json"
        path.write_text(json.dumps(self.results, ensure_ascii=False, indent=1), encoding="utf-8")

    def upload(self, filename: str, data: bytes) -> Sheet:
        sheet = read_sheet(filename, data)
        suffix = Path(filename).suffix.lower()
        stored = f"current{suffix}"
        (self.cfg.data_dir / stored).write_bytes(data)
        (self.cfg.data_dir / "current.json").write_text(
            json.dumps({"filename": filename, "stored": stored}), encoding="utf-8"
        )
        with self._lock:
            self.sheet = sheet
            self.results = {}
            self._save_results()
        self.bus.publish({"type": "sheet", "sheet": sheet.to_json()})
        return sheet

    # -- state -------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._job is not None and self._job.is_alive()

    def state(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet.to_json() if self.sheet else None,
            "results": self.results,
            "films": self.films.available(),
            "running": self.running,
            "ai_name": self.cfg.ai_name,
            "prices": {"input": self.cfg.prices.input_per_million, "output": self.cfg.prices.output_per_million},
            "adapter": self.adapter is not None,
            "speed": self.speed,
        }

    # -- jobs --------------------------------------------------------------------------

    def start_job(self, ids: list[str], *, relearn: bool, source: str) -> str | None:
        """Start running ``ids``; returns an error message when it cannot start."""
        if self.sheet is None:
            return "load a parameters file first"
        if self.running:
            return "a run is already in progress"
        rows = [r for r in self.sheet.rows if r.id in ids] if ids else list(self.sheet.rows)
        if not rows:
            return "no matching row"
        self._cancel.clear()
        self._job = threading.Thread(target=self._run_rows, args=(rows, relearn, source), daemon=True)
        self._job.start()
        return None

    def stop(self) -> None:
        self._cancel.set()

    def _run_rows(self, rows: list[Any], relearn: bool, source: str) -> None:
        self.bus.publish({"type": "job_start", "rows": [r.id for r in rows], "source": source})
        for row in rows:
            if self._cancel.is_set():
                break
            try:
                result = self._run_film(row, relearn) if source == "film" else self._run_live(row, relearn)
            except Exception as exc:
                log.error("run of %s failed:\n%s", row.id, traceback.format_exc())
                result = {"status_label": "Error", "notes": f"{type(exc).__name__}: {exc}"[:300]}
                self.bus.publish({"type": "run_end", "row": row.id, "result": result})
            if result is not None:
                with self._lock:
                    self.results[row.id] = result
                    self._save_results()
        self.bus.publish({"type": "job_end", "cancelled": self._cancel.is_set(), "films": self.films.available()})

    def _run_live(self, row: Any, relearn: bool) -> dict[str, Any]:
        recorder = Recorder(row.to_json())

        def emit(event: dict[str, Any]) -> None:
            recorder.add(event)
            self.bus.publish(event)

        result = SiteRunner(self.cfg, emit, self.adapter).run(row, relearn=relearn)
        if recorder.save(self.cfg.films_dir) is None:
            log.info("run of %s not recorded (no end)", row.id)
        return {**result, "source": "live"}

    def _run_film(self, row: Any, relearn: bool) -> dict[str, Any] | None:
        film = self.films.load(row.id, "learn" if relearn else "replay")
        if film is None:
            self.bus.publish({"type": "notice", "row": row.id, "kind": "no_film",
                              "text": f"No recorded run for {row.name} yet: run it live once."})
            return None
        return play(
            film, row.id, self.bus.publish,
            speed=lambda: self.speed, cancelled=self._cancel.is_set, max_gap_s=self.cfg.film_max_gap_s,
        )

    def open_files(self, row_id: str) -> str | None:
        """Show the row's downloaded files in the file manager; returns an error message."""
        row = next((r for r in self.sheet.rows if r.id == row_id), None) if self.sheet else None
        if row is None:
            return "unknown row"
        folder = SiteRunner(self.cfg, self.bus.publish, self.adapter).files_dir(row)
        if folder is None:
            return f"No files downloaded yet for {row.name}: run it first."
        if os.name == "nt":
            os.startfile(folder)  # noqa: S606 - a folder we computed, opened in Explorer
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])  # noqa: S603
        return None

    # -- page 2 ------------------------------------------------------------------------

    def stories(self) -> dict[str, Any]:
        path = self.cfg.films_dir / "stories.json"
        out: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        learned = self.films.available()
        prefer = sorted((k for k in learned if "learn" in learned[k]), key=lambda k: (k != "credit-agricole", k))
        for key in prefer:
            film = self.films.load(key, "learn") or {}
            end = next((e["event"] for e in film.get("events", []) if e["event"].get("type") == "run_end"), None)
            if end and end.get("result", {}).get("status_label") == "Learned":
                out["learn"] = {"name": film.get("row", {}).get("name", key), **end["result"]}
                break
        return out


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "kraken-demo"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet console
        log.debug("http " + fmt, *args)

    # -- helpers -----------------------------------------------------------------------

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise ValueError("file too large (10 MB at most)")
        return self.rfile.read(length) if length else b""

    def _static(self, rel: str) -> None:
        path = (STATIC / (rel or "index.html")).resolve()
        if STATIC.resolve() not in path.parents or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # -- routes ------------------------------------------------------------------------

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        app = self.app
        if path == "/events":
            return self._events()
        if path == "/api/state":
            return self._json(app.state())
        if path == "/api/stories":
            return self._json(app.stories())
        if path == "/api/export":
            if app.sheet is None:
                return self._json({"error": "no parameters file loaded"}, 400)
            data = export(app.sheet, app.results, app.cfg.ai_name)
            name = Path(app.sheet.filename).stem + "_kraken_results.xlsx"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        if path == "/" or path.startswith("/static/"):
            return self._static(path.removeprefix("/static/").removeprefix("/"))
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        app = self.app
        try:
            if path == "/api/upload":
                name = Path(self.headers.get("X-Filename", "parameters.xlsx")).name
                sheet = app.upload(name, self._body())
                return self._json({"sheet": sheet.to_json()})
            payload = json.loads(self._body() or b"{}")
            if path == "/api/run":
                error = app.start_job(
                    list(payload.get("ids") or []),
                    relearn=bool(payload.get("relearn")),
                    source="film" if payload.get("source") == "film" else "live",
                )
                return self._json({"error": error} if error else {"ok": True}, 409 if error else 202)
            if path == "/api/open":
                error = app.open_files(str(payload.get("id", "")))
                return self._json({"error": error} if error else {"ok": True}, 404 if error else 200)
            if path == "/api/stop":
                app.stop()
                return self._json({"ok": True})
            if path == "/api/speed":
                app.speed = min(8.0, max(0.25, float(payload.get("speed", 1))))
                return self._json({"speed": app.speed})
        except SheetError as exc:
            return self._json({"error": str(exc)}, 400)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.app.bus.subscribe()
        try:
            self.wfile.write(b": hello\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15)
                    chunk = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
                except queue.Empty:
                    chunk = b": ping\n\n"
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.app.bus.unsubscribe(q)


def serve(app: App) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((app.cfg.host, app.cfg.port), handler)
    server.daemon_threads = True
    return server

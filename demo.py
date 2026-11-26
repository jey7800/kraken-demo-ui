"""Kraken 2.0 demo: start the local server and open the page.

    python demo.py                    # reads demo.toml next to this file
    python demo.py --config other.toml --no-browser

Run it with the Python environment where Retrievr is installed (on the work PC, the
Kraken 2.0 environment, so that the private-portal adapter can be imported).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(Path.cwd()))  # the host app's package (adapter), when started from its folder

from kdemo.adapter import load_adapter  # noqa: E402
from kdemo.config import DemoConfig, load_env_file  # noqa: E402
from kdemo.server import App, serve  # noqa: E402

EDGE_PATHS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def open_page(url: str) -> None:
    """Edge in app mode (a window without tabs or address bar), else the default browser."""
    edge = shutil.which("msedge") or next((str(p) for p in EDGE_PATHS if p.is_file()), None)
    if edge:
        subprocess.Popen([edge, f"--app={url}", "--start-maximized"])  # noqa: S603
    else:
        webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kraken 2.0 demo")
    parser.add_argument("--config", type=Path, default=HERE / "demo.toml")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("retrievr").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = DemoConfig.load(args.config if args.config.is_file() else None)
    if args.port:
        cfg.port = args.port
    loaded = load_env_file(cfg.env_file)
    if loaded:
        logging.info("environment loaded from %s: %s", cfg.env_file, ", ".join(loaded))
    adapter = load_adapter(cfg.adapter)  # may ask for the vault password in this terminal
    app = App(cfg, adapter)
    server = serve(app)
    url = f"http://{cfg.host}:{cfg.port}/"
    logging.info("Kraken 2.0 demo on %s (Ctrl+C to stop)", url)
    if cfg.open_browser and not args.no_browser:
        open_page(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

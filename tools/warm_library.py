"""Prepare the document library before the demo: extract every text, write every AI
summary (kept, so they open instantly), and optionally record the answers to each
summary's suggested questions (replayed in Recorded mode, with no network).

    python tools/warm_library.py                       # texts + summaries, all issuers
    python tools/warm_library.py --issuer airbus --answers
    python tools/warm_library.py --texts-only

Run it with the demo's Python environment and settings (demo.toml): on the work PC the AI
calls go through SecureGPT, exactly as in the page. Summaries already made are skipped.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(Path.cwd()))  # the host app's package (adapter), when started from its folder

from kdemo.adapter import load_adapter  # noqa: E402
from kdemo.ai import AIError  # noqa: E402
from kdemo.config import DemoConfig, load_env_file  # noqa: E402
from kdemo.library import TextUnavailableError  # noqa: E402
from kdemo.server import App  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the document library (texts, summaries, answers)")
    parser.add_argument("--config", type=Path, default=HERE / "demo.toml")
    parser.add_argument("--issuer", action="append", default=[], help="only this issuer folder (repeatable)")
    parser.add_argument("--texts-only", action="store_true", help="extract texts, no AI call")
    parser.add_argument("--answers", action="store_true", help="also record the answers to suggested questions")
    parser.add_argument("--refresh", action="store_true", help="write the summaries again")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    cfg = DemoConfig.load(args.config if args.config.is_file() else None)
    cfg.library.warm = False
    load_env_file(cfg.env_file)
    adapter = load_adapter(cfg.adapter) if not args.texts_only else None
    app = App(cfg, adapter)
    docs = [d for d in app.library_docs() if d.readable and (not args.issuer or d.issuer in args.issuer)]
    print(f"{len(docs)} documents the AI can read")
    totals = {"tokens": 0, "cost": 0.0, "summaries": 0, "answers": 0, "failed": 0}
    started = time.monotonic()
    try:
        for i, doc in enumerate(docs, 1):
            label = f"[{i}/{len(docs)}] {doc.rel}"
            try:
                text = app.texts.get(doc)
            except TextUnavailableError as exc:
                print(f"{label}: no text ({exc})")
                continue
            if args.texts_only:
                print(f"{label}: {len(text.pages)} {'pages' if text.kind == 'pdf' else 'sheets'}")
                continue
            try:
                had = app.ai.has_summary(doc) and not args.refresh
                summary = app.ai.summary(doc, refresh=args.refresh)
                if not had:
                    totals["summaries"] += 1
                    totals["tokens"] += summary["input_tokens"] + summary["output_tokens"]
                    totals["cost"] += summary["cost"]
                print(f"{label}: summary {'kept' if had else f'written in {summary['seconds']} s'}")
                if args.answers:
                    for q in summary.get("questions", []):
                        history = [{"role": "user", "content": q}]
                        if app.ai.has_answer(doc, q):
                            continue
                        for event in app.ai.chat(doc, history):
                            if event["type"] == "done":
                                totals["answers"] += 1
                                totals["tokens"] += event["input_tokens"] + event["output_tokens"]
                                totals["cost"] += event["cost"]
                            elif event["type"] == "error":
                                print(f"    answer failed: {event['text']}")
            except AIError as exc:
                totals["failed"] += 1
                print(f"{label}: FAILED {exc}")
    finally:
        app.close()
    print(f"\n{totals['summaries']} summaries and {totals['answers']} answers written, {totals['failed']} failed, "
          f"{totals['tokens']:,} tokens, EUR {totals['cost']:.4f} at the demo's prices, "
          f"{time.monotonic() - started:.0f} s")
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

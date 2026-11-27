"""Check the library's AI path on this machine, with a redacted report (no document text,
no answer text, no secret): PDF reading, the AI endpoint through the host's transport,
JSON mode, streaming and reasoning_effort, and the timings a demo will show.

    python tools/check_library_ai.py

Run it from the folder where the host app's package is importable (the adapter), with the
demo's settings (demo.toml). It makes three short AI calls on the smallest public PDF.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(Path.cwd()))

from kdemo.adapter import load_adapter  # noqa: E402
from kdemo.ai import chat_messages, summary_messages  # noqa: E402
from kdemo.config import DemoConfig, load_env_file  # noqa: E402
from kdemo.server import App  # noqa: E402


def main() -> int:
    cfg = DemoConfig.load(HERE / "demo.toml" if (HERE / "demo.toml").is_file() else None)
    cfg.library.warm = False
    load_env_file(cfg.env_file)
    adapter = load_adapter(cfg.adapter)
    app = App(cfg, adapter)
    ok = True
    try:
        docs = app.library_docs()
        public = [d for d in docs if d.readable]
        print(f"library: {len(docs)} documents, {len(public)} readable by the AI, "
              f"{sum(d.private for d in docs)} private (masked)")
        try:
            import pypdf

            print(f"pypdf: {pypdf.__version__}")
        except ImportError:
            print("pypdf: MISSING (pip install pypdf in this environment)")
            return 1
        pdfs = sorted((d for d in public if d.kind == "pdf" and d.size > 50_000), key=lambda d: d.size)
        if not pdfs:
            print("no public PDF in the library: run a site first")
            return 1
        doc = pdfs[0]
        t = time.monotonic()
        text = app.texts.get(doc)
        print(f"text: {len(text.pages)} pages, {text.chars} chars, extracted in {time.monotonic() - t:.1f} s")
        client = app.ai.client
        ep = client.ep
        print(f"endpoint: model={ep.model} host_transport={'yes' if adapter is not None else 'no'} "
              f"max_tokens={ep.max_tokens} reasoning_effort={ep.chat_effort or '-'}")

        msgs, _ = summary_messages(doc, text, cfg.library.max_chars, cfg.ai_name)
        t = time.monotonic()
        try:
            answer, usage = client.complete(msgs, max_tokens=ep.max_tokens, json_mode=True)
            print(f"summary call: ok in {time.monotonic() - t:.1f} s, json_mode={'refused' if client.no_json_mode else 'ok'}, "
                  f"tokens in/out {usage.input_tokens}/{usage.output_tokens}{' (estimated)' if usage.estimated else ''}, "
                  f"answer {len(answer)} chars")
        except Exception as exc:
            ok = False
            print(f"summary call: FAILED {type(exc).__name__}: {str(exc)[:200]}")

        for effort in (True, False):
            msgs, _ = chat_messages(doc, text, [{"role": "user", "content": "What is this document about?"}],
                                    cfg.library.max_chars, cfg.ai_name)
            t = time.monotonic()
            first, pieces, usage = None, 0, None
            try:
                for piece in client.stream(msgs, max_tokens=ep.max_tokens, effort=effort):
                    if isinstance(piece, str):
                        first = first if first is not None else time.monotonic() - t
                        pieces += 1
                    else:
                        usage = piece
                print(f"chat (effort {'on' if effort else 'off'}): first words {first or 0:.1f} s, total "
                      f"{time.monotonic() - t:.1f} s, {pieces} pieces, streaming={'refused' if client.no_stream else 'ok'}, "
                      f"reasoning_effort={'refused' if client.no_effort else ('ok' if effort and ep.chat_effort else '-')}, "
                      f"tokens in/out {usage.input_tokens if usage else '?'}/{usage.output_tokens if usage else '?'}")
            except Exception as exc:
                ok = False
                print(f"chat (effort {'on' if effort else 'off'}): FAILED {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        app.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

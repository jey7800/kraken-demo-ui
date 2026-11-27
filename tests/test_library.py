"""Offline tests of the document library: index, text, summaries and chat (no network,
the AI endpoint is an httpx mock transport)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kdemo.ai import AIError, Client, DocAI, Endpoint, parse_summary, question_key, split_value  # noqa: E402
from kdemo.config import Prices  # noqa: E402
from kdemo.library import (  # noqa: E402
    PDF,
    SHEET,
    DocText,
    Source,
    TextStore,
    period_label,
    scan,
    type_label,
    why_label,
)
from kdemo.xlsx import TEXT, OutCell, OutSheet, read_sheets, write_workbook  # noqa: E402


def _tree(tmp: Path) -> Path:
    out = tmp / "downloads"
    (out / "acme" / "2025").mkdir(parents=True)
    (out / "acme" / "2024").mkdir(parents=True)
    (out / "acme" / "2025" / "annual_report_2025-FY_en.pdf").write_bytes(b"%PDF-1.7 a")
    (out / "acme" / "2024" / "press_release_2024-Q3_fr.pdf").write_bytes(b"%PDF-1.7 b")
    (out / "acme" / "2024" / "quarterly_series_2024-Q3_fr_ab12cd34.xlsb").write_bytes(b"x")
    (out / "manifest.json").write_text(json.dumps({"manifest_version": 1, "documents": [{
        "issuer": "acme", "path": "acme/2025/annual_report_2025-FY_en.pdf", "title": "Annual Report 2025",
        "type": "annual_report", "period": "2025-FY", "fiscal_year": 2025, "language": "en", "size": 10,
        "sha256": "aa" * 32, "url": "https://ir.acme.example/ar2025.pdf",
        "justification": "type=annual_report by link_text /annual/; period=2025-FY by link_text+url /x/; "
                         "language=en by recipe default",
    }, {"issuer": "gone", "path": "gone/2025/x.pdf"}]}), encoding="utf-8")
    return out


def test_scan_reads_the_manifest_and_the_folder_tree(tmp_path: Path) -> None:
    out = _tree(tmp_path)
    docs = scan([Source(out)], {"acme": "Acme Group"})
    assert [d.path.name for d in docs] == [
        "annual_report_2025-FY_en.pdf", "press_release_2024-Q3_fr.pdf", "quarterly_series_2024-Q3_fr_ab12cd34.xlsb",
    ]
    ar, pr, xb = docs
    assert ar.issuer_name == "Acme Group" and ar.title == "Annual Report 2025" and ar.sha256
    assert pr.title == "press release 2024-Q3 fr" and pr.period == "2024-Q3" and pr.language == "fr"
    assert pr.fiscal_year == 2024 and pr.readable and pr.kind == PDF
    assert xb.type == "quarterly_series" and not xb.readable  # a binary workbook: listed, not read
    j = ar.to_json()
    assert j["host"] == "ir.acme.example" and j["period_label"] == "Full year 2025"
    assert j["why"][1] == {"field": "Period", "value": "2025-FY", "from": "the link text and the link address"}


def test_private_documents_are_masked(tmp_path: Path) -> None:
    out = _tree(tmp_path)
    docs = scan([Source(out, private=True, issuers={"acme"})], {})
    j = docs[0].to_json()
    assert j["private"] and not j["readable"] and j["url"] == "" and j["title"].startswith("Fund document")
    assert j["why"] == [] and j["issuer_name"] == "Acme"
    assert scan([Source(out, exclude={"acme"})], {}) == []


def test_labels() -> None:
    assert type_label("analyst_call_transcript") == "Analyst call transcript"
    assert type_label("urd") == "Universal registration document"
    assert period_label("2025-Q3") == "Q3 2025" and period_label("2024-H1") == "H1 2024"
    assert why_label("type=x by any /a/; language=fr by recipe default", "AI") == [
        {"field": "Type", "value": "x", "from": "the link and its text"},
        {"field": "Language", "value": "fr", "from": "the site's recipe"},
    ]


def test_context_is_marked_by_page_and_cut() -> None:
    text = DocText(PDF, ["alpha " * 10, "beta " * 10, "gamma " * 10], ["1", "2", "3"])
    body, n = text.context(10_000)
    assert n == 3 and body.startswith("[[Page 1]]\nalpha") and "[[Page 3]]" in body
    body, n = text.context(140)
    assert n == 2 and "[[Page 3]]" not in body
    body, n = text.context(20)
    assert n == 1 and len(body) == 20  # never empty


def test_sheet_text_reads_every_sheet(tmp_path: Path) -> None:
    data = write_workbook([
        OutSheet("Income", [[OutCell("Net income", TEXT), OutCell(1234.5)], [OutCell(None)]]),
        OutSheet("Capital", [[OutCell("CET1", TEXT), OutCell(0.132)]]),
    ])
    assert [name for name, _ in read_sheets(data)] == ["Income", "Capital"]
    path = tmp_path / "acme" / "2025" / "series_2025-Q3_en.xlsx"
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    doc = scan([Source(tmp_path)], {})[0]
    text = TextStore(tmp_path / "cache").get(doc)
    assert text.kind == SHEET and text.labels == ["Income", "Capital"]
    assert text.pages == ["Net income | 1234.5", "CET1 | 0.132"]
    assert TextStore(tmp_path / "cache").info(doc)["pages"] == 2  # side file, no text read


def test_parse_summary_and_split_values() -> None:
    raw = "```json\n" + json.dumps({
        "headline": "Record year", "overview": "o", "key_points": ["a", "", "b"],
        "key_figures": [{"label": "Net income", "value": "€8,754 million in 2025; +1.3% year on year", "page": 7},
                        {"label": "CET1", "value": "17.4 %", "change": "-0.2 pt", "page": "p. 28"}],
        "questions": ["q1", "q2", "q3", "q4"],
    }) + "\n```"
    s = parse_summary(raw)
    assert s["key_points"] == ["a", "b"] and len(s["questions"]) == 3
    assert s["key_figures"][0] == {"label": "Net income", "value": "€8,754 million", "change": "+1.3% year on year",
                                   "page": "7"}
    assert s["key_figures"][1]["page"] == "28" and s["key_figures"][1]["change"] == "-0.2 pt"
    assert split_value("$412 m (up 4%)") == ("$412 m", "up 4%")
    assert split_value("€6.4 bn") == ("€6.4 bn", "")
    with pytest.raises(AIError):
        parse_summary("sorry, I cannot")


def _endpoint(handler: Any, **kw: Any) -> Endpoint:
    return Endpoint(base_url="https://ai.example/v1", model="m", api_key="k", extra_body={}, temperature=None,
                    timeout_s=5, transport=lambda: httpx.MockTransport(handler), **kw)


def _sse(*pieces: str, usage: tuple[int, int] = (100, 5)) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}" for p in pieces]
    lines.append(f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': usage[0], 'completion_tokens': usage[1]}})}")
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def test_stream_with_effort_falls_back_when_refused() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(400, json={"error": "unknown parameter"})
        return httpx.Response(200, content=_sse("Hel", "lo"), headers={"content-type": "text/event-stream"})

    client = Client(_endpoint(handler, chat_effort="low"))
    out = list(client.stream([{"role": "user", "content": "hi"}], max_tokens=50, effort=True))
    assert out[:2] == ["Hel", "lo"] and out[-1].input_tokens == 100 and not out[-1].estimated
    assert client.no_effort and seen[-1]["stream"] is True and seen[-1]["max_tokens"] == 50
    list(client.stream([{"role": "user", "content": "hi"}], max_tokens=50, effort=True))
    assert "reasoning_effort" not in seen[-1]  # not sent any more


def test_stream_refused_gives_whole_answers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content).get("stream"):
            return httpx.Response(400, json={"error": "stream not supported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "A whole answer"}}]})

    client = Client(_endpoint(handler))
    out = list(client.stream([{"role": "user", "content": "hi"}], max_tokens=50))
    assert "".join(p for p in out if isinstance(p, str)) == "A whole answer"
    assert out[-1].estimated and client.no_stream


def test_empty_answer_says_why() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})

    with pytest.raises(AIError, match="ran out of room"):
        Client(_endpoint(handler)).complete([{"role": "user", "content": "x"}], max_tokens=5)


def test_summary_is_kept_and_chat_replays_offline(tmp_path: Path) -> None:
    out = _tree(tmp_path)
    doc = scan([Source(out)], {})[0]
    texts = TextStore(tmp_path / "cache" / "text")
    store_text = DocText(PDF, ["Net income was EUR 8.75 bn."], ["1"])
    texts._memo[doc.key] = store_text  # no pypdf needed: the text is "already extracted"
    (tmp_path / "cache" / "text").mkdir(parents=True)
    (tmp_path / "cache" / "text" / f"{doc.key}.json").write_text(json.dumps(store_text.to_json()))
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body.get("stream"):
            return httpx.Response(200, content=_sse("EUR 8.75 bn ", "[p. 1]."), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"headline": "h", "key_points": ["k"], "key_figures": [], "questions": ["Net income?"]})}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})

    ai = DocAI(folder=tmp_path / "cache", texts=texts, endpoint=lambda: _endpoint(handler), prices=Prices(),
               ai_name="SecureGPT", max_chars=10_000)
    first = ai.summary(doc)
    assert not first["cached"] and first["pages_read"] == 1 and first["cost"] == pytest.approx(0.00014)
    assert "<document>" in calls[0]["messages"][1]["content"]
    assert ai.summary(doc)["cached"] and len(calls) == 1
    events = list(ai.chat(doc, [{"role": "user", "content": "Net income?"}]))
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "EUR 8.75 bn [p. 1]."
    assert events[-1]["type"] == "done" and not events[-1]["cached"]
    assert calls[-1]["messages"][0]["role"] == "system" and "[[Page 1]]" in calls[-1]["messages"][0]["content"]
    assert ai.has_answer(doc, "  net INCOME ")
    replay = list(ai.chat(doc, [{"role": "user", "content": "net income"}], offline=True))
    assert "".join(e["text"] for e in replay if e["type"] == "delta") == "EUR 8.75 bn [p. 1]."
    assert replay[-1]["cached"] and len(calls) == 2  # no call when replayed
    missing = list(ai.chat(doc, [{"role": "user", "content": "Dividend?"}], offline=True))
    assert missing[-1]["type"] == "error"
    assert question_key(doc, "Net income?") == question_key(doc, "net income")

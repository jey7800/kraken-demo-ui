"""Offline tests of the demo's own logic (no network, no AI)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrievr.events import Event  # noqa: E402

from kdemo.config import Prices  # noqa: E402
from kdemo.driver import Tracker  # noqa: E402
from kdemo.films import Recorder, play  # noqa: E402
from kdemo.observe import AICall  # noqa: E402
from kdemo.sheet import SheetError, SiteRow, export, parse_table, parse_years, read_csv, read_sheet  # noqa: E402
from kdemo.xlsx import TEXT, OutCell, OutSheet, read_first_sheet, write_workbook  # noqa: E402


def test_years() -> None:
    today = date(2026, 11, 26)
    assert parse_years("2024-2025") == [2024, 2025]
    assert parse_years("2023, 2025") == [2023, 2025]
    assert parse_years(2024.0) == [2024]
    assert parse_years("since 2024", today) == [2024, 2025, 2026]
    assert parse_years("") == []


def test_headers_in_french_and_values() -> None:
    table: list[list[Any]] = [
        ["Nom", "Lien", "Privé/Public", "Années", "Types de documents", "Forcer le learning"],
        ["Émetteur A", "https://a.example/ir", "Privé", "2025", "rapports annuels", "oui"],
        ["Émetteur A", "https://b.example/ir", "Public", "2024-2025", "", "non"],
        ["Sans lien", "", "Public", "", "", ""],
    ]
    sheet = parse_table("f.xlsx", "Feuil1", table)
    a, b = sheet.rows
    assert (a.id, a.private, a.years, a.force_learn) == ("emetteur-a", True, [2025], True)
    assert (b.id, b.private, b.force_learn) == ("emetteur-a-2", False, False)
    assert sheet.warnings and "Sans lien" in sheet.warnings[0]
    assert sheet.lines == [2, 3, 4]


def test_missing_columns_say_what_is_needed() -> None:
    with pytest.raises(SheetError, match="'name' column and a 'url' column"):
        parse_table("f.csv", "x", [["a", "b"], ["1", "2"]])


def test_csv_semicolons_and_cp1252() -> None:
    data = "Name;URL;Access\nSoci\xe9t\xe9;https://x.example;public\n".encode("cp1252")
    sheet = parse_table("f.csv", "Sites", read_csv(data))
    assert sheet.rows[0].name == "Société"


def test_xlsx_round_trip_and_export() -> None:
    rows = [[OutCell(v, TEXT) for v in r] for r in (
        ["Name", "URL", "Access", "Years"],
        ["UBS", "https://ubs.example", "Public", 2025],
        ["Fund & Co <x>", "https://p.example", "Private", "2024-2025"],
    )]
    data = write_workbook([OutSheet("Sites", rows)])
    name, table = read_first_sheet(data)
    assert name == "Sites" and table[2][0] == "Fund & Co <x>" and table[1][3] == 2025
    sheet = read_sheet("p.xlsx", data)
    out = export(sheet, {"ubs": {"status_label": "Done", "found": 3, "cost": 0.0002}}, "SecureGPT")
    _, enriched = read_first_sheet(out)
    assert enriched[0][4] == "Status" and enriched[0][11] == "SecureGPT cost (EUR)"
    assert enriched[1][4] == "Done" and enriched[2][4] == "Not run"


def _tracker(private: bool = False) -> tuple[Tracker, list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    row = SiteRow("s", "Site", "https://s.example", private, [2025], "annual reports", False, 2)
    return Tracker(row, out.append, Prices(0.10, 0.40)), out


def steps(out: list[dict[str, Any]]) -> list[str]:
    return [e["step"] for e in out if e["type"] == "step"]


def test_replay_steps_from_requests_and_downloads() -> None:
    t, out = _tracker()
    t.start()
    t.known(True, False)
    t.on_request(httpx.Request("GET", "https://s.example/robots.txt"))
    t.on_request(httpx.Request("GET", "https://s.example/list?page=1"))
    t.on_event(Event("document_downloaded", "s", "[1/2] downloaded: s/2025/annual_report_FY2025_en.pdf",
                     {"status": "downloaded", "index": 1, "total": 2}))
    t.through("store")
    assert steps(out) == ["site", "access", "known", "replay", "read", "health", "classify", "download", "store"]
    doc = next(e for e in out if e["type"] == "doc")
    assert doc["label"] == "Annual report FY2025" and t.pages == 1


def test_repair_path_and_ai_links() -> None:
    t, out = _tracker()
    t.start()
    t.known(True, False)
    t.on_request(httpx.Request("GET", "https://s.example/list"))
    t.on_event(Event("health_alert", "s", "broken", {"verdict": "broken"}))
    t.on_ai_start(httpx.Request("POST", "https://ai.example"))
    t.on_ai_call(AICall("repair:structure", "m", False, 1000, 100))
    t.on_event(Event("recipe_repaired", "s", "ok", {}))
    t.through("store")
    assert steps(out) == ["site", "access", "known", "replay", "read", "health", "repair", "verify",
                          "classify", "download", "store"]
    ai = [e for e in out if e["type"] in ("ai_start", "ai_end")]
    assert {e["link"] for e in ai} == {"a2"}
    assert t.ai_calls == 1 and t.cost == pytest.approx((1000 * 0.10 + 100 * 0.40) / 1e6)


def test_cached_ai_calls_cost_nothing() -> None:
    t, _out = _tracker()
    t.known(False, True)
    t.on_ai_call(AICall("structure", "m", True, 5000, 500))
    assert t.ai_calls == 0 and t.cost == 0


def test_private_cards_never_show_titles() -> None:
    t, _out = _tracker(private=True)
    assert t.doc_label("[1/1] downloaded: x/2025/statement_Q3_en.pdf", "downloaded") == "Fund document"


def test_film_round_trip(tmp_path: Path) -> None:
    rec = Recorder({"id": "s"})
    rec.add({"type": "run_start", "row": "s"})
    rec.add({"type": "step", "row": "s", "step": "learn"})
    rec.add({"type": "run_end", "row": "s", "result": {"status_label": "Learned"}})
    path = rec.save(tmp_path)
    assert path is not None and path.name == "s.learn.json"
    import json

    film = json.loads(path.read_text(encoding="utf-8"))
    got: list[dict[str, Any]] = []
    result = play(film, "other", got.append, speed=lambda: 1.0, cancelled=lambda: False, sleep=lambda _s: None)
    assert [e["row"] for e in got] == ["other"] * 3
    assert got[0]["source"] == "film" and result is not None and result["source"] == "film"


def test_forget_files_deletes_only_this_issuer(tmp_path: Path) -> None:
    import json

    from kdemo.config import DemoConfig
    from kdemo.driver import SiteRunner

    out = tmp_path / "downloads"
    for rel in ("s/2025/a.pdf", "other/2025/b.pdf"):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(b"%PDF-")
    (out / "manifest.json").write_text(json.dumps({"documents": [
        {"issuer": "s", "path": "s/2025/a.pdf"},
        {"issuer": "other", "path": "other/2025/b.pdf"},
        {"issuer": "s", "path": "../outside.pdf"},
    ]}), encoding="utf-8")
    (tmp_path / "outside.pdf").write_bytes(b"keep")
    cfg = DemoConfig(root=tmp_path, state_dir=tmp_path / "state", output_dir=out).resolved()
    row = SiteRow("s", "Site", "https://s.example", False, [], "", False, 2)
    assert SiteRunner(cfg, lambda _e: None).forget_files(row) == 1
    assert not (out / "s/2025/a.pdf").exists()
    assert (out / "other/2025/b.pdf").exists() and (tmp_path / "outside.pdf").exists()


def test_failed_runs_are_not_recorded(tmp_path: Path) -> None:
    rec = Recorder({"id": "s"})
    rec.add({"type": "run_end", "row": "s", "result": {"status_label": "Blocked"}})
    assert rec.save(tmp_path) is None and not list(tmp_path.iterdir())

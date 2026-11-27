"""The parameters file (Excel or CSV): one row per site, and its enriched export."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from kdemo.xlsx import (
    BAD,
    BOLD,
    HEAD,
    HEAD_RESULT,
    INT,
    LEARNED,
    MONEY,
    OK,
    TEXT,
    TITLE,
    WARN,
    Cell,
    OutCell,
    OutSheet,
    read_first_sheet,
    write_workbook,
)


class SheetError(ValueError):
    """The file cannot be read as a parameters sheet; the message says what to fix."""


@dataclass
class SiteRow:
    id: str
    """Retrievr site key (a slug of the name unless a ``site id`` column gives it)."""
    name: str
    url: str
    private: bool
    years: list[int]
    request: str
    force_learn: bool
    line: int
    """Row number in the source file (1 = header)."""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Sheet:
    filename: str
    sheet_name: str
    header: list[str]
    data: list[list[Cell]]
    """Source rows below the header, as read (kept for the export)."""
    lines: list[int] = field(default_factory=list)
    """Source line number of each ``data`` row."""
    rows: list[SiteRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "rows": [r.to_json() for r in self.rows],
            "warnings": self.warnings,
        }


# Header names accepted for each field (compared without accents, case or punctuation).
ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "issuer", "nom", "emetteur", "site", "company", "societe"),
    "url": ("url", "start url", "link", "lien", "adresse", "website"),
    "access": ("access", "private public", "prive public", "public prive", "type", "acces",
               "private", "prive", "visibility"),
    "years": ("years", "annees", "target years", "annees ciblees", "year", "annee", "period"),
    "request": ("documents", "document types", "types de documents", "request", "demande",
                "requested documents", "documents demandes", "types"),
    "force": ("force learning", "forcer le learning", "force learn", "relearn", "re learn",
              "force", "forcer", "learning"),
    "site_id": ("site id", "recipe", "recette", "id"),
}
REQUIRED = ("name", "url")
TRUE = {"yes", "oui", "true", "vrai", "1", "x", "y", "o"}


def _key(text: object) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _key(text)).strip("-") or "site"


def _columns(header: list[Cell]) -> dict[str, int]:
    found: dict[str, int] = {}
    keys = [_key(h) for h in header]
    for fieldname, names in ALIASES.items():
        for name in names:  # first alias wins, so "documents" beats a generic "type"
            if name in keys and keys.index(name) not in found.values():
                found[fieldname] = keys.index(name)
                break
    return found


def parse_years(value: Cell, today: date | None = None) -> list[int]:
    """``2024``, ``"2024-2025"``, ``"2023, 2025"``, ``"since 2022"``, ``"2022+"``."""
    if value is None or value == "":
        return []
    if isinstance(value, int | float) and not isinstance(value, bool):
        return [int(value)]
    text = str(value)
    current = (today or date.today()).year
    found = [int(y) for y in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)]
    if not found:
        return []
    if re.search(r"(since|depuis|from|\+|onwards|à partir)", text, re.IGNORECASE) and len(found) == 1:
        return list(range(found[0], current + 1))
    if len(found) == 2 and re.search(r"\d\s*(-|–|to|à|a|\.\.)\s*(19|20)\d{2}", text):
        lo, hi = sorted(found)
        return list(range(lo, hi + 1))
    return sorted(set(found))


def _private(value: Cell, header_key: str) -> bool:
    text = _key(value)
    if "priv" in text:
        return True
    if "pub" in text:
        return False
    return text in TRUE and "priv" in header_key


def _rows_from(table: list[list[Cell]]) -> tuple[int, list[Cell]]:
    """The header row: the first row naming a name column and a URL column."""
    for i, row in enumerate(table[:20]):
        cols = _columns(row)
        if all(k in cols for k in REQUIRED):
            return i, row
    raise SheetError(
        "no header row found: the file needs at least a 'name' column and a 'url' column "
        "(also read: access, years, documents, force learning)"
    )


def parse_table(filename: str, sheet_name: str, table: list[list[Cell]]) -> Sheet:
    head_index, header = _rows_from(table)
    cols = _columns(header)
    sheet = Sheet(filename, sheet_name, [str(h or "") for h in header], [])
    seen: set[str] = set()
    access_key = _key(header[cols["access"]]) if "access" in cols else ""
    for offset, raw in enumerate(table[head_index + 1 :], start=head_index + 2):
        get = lambda f: raw[cols[f]] if f in cols and cols[f] < len(raw) else None  # noqa: E731
        name = str(get("name") or "").strip()
        url = str(get("url") or "").strip()
        if not name and not url:
            continue
        sheet.data.append(raw)
        sheet.lines.append(offset)
        if not url.lower().startswith(("http://", "https://")):
            sheet.warnings.append(f"line {offset}: '{name}' has no http(s) URL, skipped")
            continue
        site_id = str(get("site_id") or "").strip() or slug(name or url)
        base, n = site_id, 2
        while site_id in seen:
            site_id, n = f"{base}-{n}", n + 1
        seen.add(site_id)
        sheet.rows.append(
            SiteRow(
                id=site_id,
                name=name or url,
                url=url,
                private=_private(get("access"), access_key),
                years=parse_years(get("years")),
                request=str(get("request") or "").strip(),
                force_learn=_key(get("force")) in TRUE,
                line=offset,
            )
        )
    if not sheet.rows:
        raise SheetError("the file lists no site with an http(s) URL")
    return sheet


def read_csv(data: bytes) -> list[list[Cell]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SheetError("the CSV file is neither UTF-8 nor Windows-1252 text")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [list(r) for r in csv.reader(io.StringIO(text), dialect)]


def read_sheet(filename: str, data: bytes) -> Sheet:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return parse_table(filename, "Sites", read_csv(data))
    if lower.endswith((".xlsx", ".xlsm")):
        try:
            name, table = read_first_sheet(data)
        except ValueError as exc:
            raise SheetError(f"cannot read {filename}: {exc}") from exc
        return parse_table(filename, name, table)
    raise SheetError("expected an .xlsx or .csv file")


# -- export ----------------------------------------------------------------------------

RESULT_COLUMNS = [
    ("Status", 14), ("Recipe", 14), ("Documents found", 12), ("Files filed", 11),
    ("New files", 10), ("AI calls", 9), ("Tokens", 10), ("AI cost (EUR)", 13),
    ("Duration", 10), ("Health", 13), ("Run at", 17), ("Notes", 48),
]
STATUS_STYLE = {"Done": OK, "Learned": LEARNED, "Repaired": WARN, "Degraded": BAD,
                "Blocked": BAD, "Sign-in refused": BAD, "Error": BAD, "No recipe": BAD,
                "Not downloaded": BAD, "Not validated": BAD}


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    m, s = divmod(int(round(seconds)), 60)
    return f"{m} min {s:02d}"


def export(sheet: Sheet, results: dict[str, dict[str, Any]], ai_name: str) -> bytes:
    """The source rows with the result columns appended, plus a summary sheet."""
    width = max(len(sheet.header), *(len(r) for r in sheet.data)) if sheet.data else len(sheet.header)
    header = [OutCell(h, HEAD) for h in sheet.header] + [OutCell("", HEAD)] * (width - len(sheet.header))
    header += [OutCell(name.replace("AI", ai_name, 1), HEAD_RESULT) for name, _w in RESULT_COLUMNS]
    by_line = {r.line: r for r in sheet.rows}
    out = OutSheet(sheet.sheet_name or "Sites", [header])
    for raw, line in zip(sheet.data, sheet.lines, strict=True):
        cells = [OutCell(v, TEXT) for v in raw] + [OutCell(None, TEXT)] * (width - len(raw))
        row = by_line.get(line)
        res = results.get(row.id, {}) if row else {}
        cells += _result_cells(res)
        out.rows.append(cells)
    src_widths = [min(max(len(str(h)) + 4, 12), 50) for h in sheet.header] + [12] * (width - len(sheet.header))
    for c in range(len(sheet.header)):
        longest = max((len(str(r[c] or "")) for r in sheet.data if c < len(r)), default=0)
        src_widths[c] = min(max(src_widths[c], longest + 2), 60)
    out.widths = src_widths + [w for _n, w in RESULT_COLUMNS]
    return write_workbook([out, _summary(sheet, results, ai_name)])


def _result_cells(res: dict[str, Any]) -> list[OutCell]:
    if not res:
        return [OutCell("Not run", TEXT)] + [OutCell(None, TEXT)] * (len(RESULT_COLUMNS) - 1)
    status = res.get("status_label", "")
    return [
        OutCell(status, STATUS_STYLE.get(status, TEXT)),
        OutCell(res.get("recipe_label", ""), TEXT),
        OutCell(res.get("found"), INT),
        OutCell(res.get("files"), INT),
        OutCell(res.get("new"), INT),
        OutCell(res.get("ai_calls"), INT),
        OutCell(res.get("tokens"), INT),
        OutCell(res.get("cost"), MONEY),
        OutCell(_duration(res.get("seconds")), TEXT),
        OutCell(res.get("health_label", ""), STATUS_STYLE.get(res.get("health_label", ""), TEXT)),
        OutCell(res.get("at", ""), TEXT),
        OutCell(res.get("notes", ""), TEXT),
    ]


def _summary(sheet: Sheet, results: dict[str, dict[str, Any]], ai_name: str) -> OutSheet:
    done = [results[r.id] for r in sheet.rows if r.id in results]
    total = lambda k: sum(float(d.get(k) or 0) for d in done)  # noqa: E731
    rows = [
        [OutCell("Kraken 2.0 run summary", TITLE)],
        [],
        [OutCell("Sites in the file", BOLD), OutCell(len(sheet.rows), INT)],
        [OutCell("Sites run", BOLD), OutCell(len(done), INT)],
        [OutCell("Documents found", BOLD), OutCell(int(total("found")), INT)],
        [OutCell("Files filed", BOLD), OutCell(int(total("files")), INT)],
        [OutCell(f"{ai_name} calls", BOLD), OutCell(int(total("ai_calls")), INT)],
        [OutCell("Tokens", BOLD), OutCell(int(total("tokens")), INT)],
        [OutCell(f"{ai_name} cost (EUR)", BOLD), OutCell(round(total("cost"), 6), MONEY)],
        [OutCell("Source file", BOLD), OutCell(sheet.filename, TEXT)],
    ]
    return OutSheet("Summary", rows, widths=[26, 30], freeze_header=False, autofilter=False)

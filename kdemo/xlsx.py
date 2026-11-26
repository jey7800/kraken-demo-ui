"""Minimal .xlsx reader and writer on the standard library (zipfile + XML).

Reading: the first worksheet, cell values only (shared strings, inline strings,
numbers, booleans). Writing: one or more sheets with a small fixed set of styles,
frozen header row, column widths and an autofilter. Nothing else of the format.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

Cell = str | float | int | bool | None


class XlsxError(ValueError):
    """The file is not a readable .xlsx workbook."""


# -- reading ---------------------------------------------------------------------------


def col_index(ref: str) -> int:
    """``"C7"`` -> 2 (zero-based column)."""
    letters = re.match(r"[A-Z]+", ref.upper())
    if not letters:
        raise XlsxError(f"bad cell reference {ref!r}")
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_letter(index: int) -> str:
    """0 -> ``"A"``, 27 -> ``"AB"``."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(t.text or "" for t in node.iter(f"{{{NS['m']}}}t"))


def read_first_sheet(data: bytes) -> tuple[str, list[list[Cell]]]:
    """The name and rows of the first worksheet (a row is a list of cell values)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError("not an .xlsx file") from exc
    with zf:
        try:
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        except KeyError as exc:
            raise XlsxError("not an .xlsx workbook") from exc
        sheet = workbook.find("m:sheets/m:sheet", NS)
        if sheet is None:
            raise XlsxError("the workbook has no sheet")
        rid = sheet.get(f"{{{REL_NS}}}id")
        target = next(
            (r.get("Target", "") for r in rels.findall("r:Relationship", PKG_REL) if r.get("Id") == rid),
            "",
        )
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared = [_text(si) for si in sst.findall("m:si", NS)]
        root = ET.fromstring(zf.read(path))
    rows: list[list[Cell]] = []
    for row in root.findall("m:sheetData/m:row", NS):
        values: list[Cell] = []
        for c in row.findall("m:c", NS):
            ref = c.get("r")
            idx = col_index(ref) if ref else len(values)
            while len(values) < idx:
                values.append(None)
            values.append(_cell_value(c, shared))
        index = int(row.get("r", len(rows) + 1)) - 1
        while len(rows) < index:
            rows.append([])
        rows.append(values)
    return sheet.get("name", "Sheet1"), rows


def _cell_value(c: ET.Element, shared: list[str]) -> Cell:
    kind = c.get("t", "n")
    if kind == "inlineStr":
        return _text(c.find("m:is", NS))
    v = c.find("m:v", NS)
    raw = v.text if v is not None and v.text is not None else None
    if raw is None:
        return None
    if kind == "s":
        i = int(raw)
        return shared[i] if 0 <= i < len(shared) else ""
    if kind in ("str", "e"):
        return raw
    if kind == "b":
        return raw == "1"
    try:
        num = float(raw)
    except ValueError:
        return raw
    return int(num) if num.is_integer() else num


# -- writing ---------------------------------------------------------------------------

# Style ids (cellXfs order in STYLES below).
DEFAULT, HEAD, HEAD_RESULT, TEXT, INT, MONEY, OK, LEARNED, WARN, BAD, TITLE, BOLD = range(12)

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;€&quot;#,##0.0000"/></numFmts>
<fonts count="8">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FF1E7B34"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FF1F3FD1"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFB26B00"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFC00000"/><name val="Calibri"/></font>
<font><b/><sz val="16"/><color rgb="FF00008F"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF00008F"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFF1721"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left/><right/><top/><bottom style="thin"><color rgb="FFD5DAEB"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="12">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>
<xf numFmtId="0" fontId="4" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>
<xf numFmtId="0" fontId="5" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>
<xf numFmtId="0" fontId="6" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="7" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


@dataclass
class OutCell:
    value: Cell
    style: int = TEXT


@dataclass
class OutSheet:
    name: str
    rows: list[list[OutCell]] = field(default_factory=list)
    widths: list[float] = field(default_factory=list)
    freeze_header: bool = True
    autofilter: bool = True


def _cell_xml(ref: str, cell: OutCell) -> str:
    v = cell.value
    s = f' s="{cell.style}"' if cell.style else ""
    if v is None or v == "":
        return f'<c r="{ref}"{s}/>'
    if isinstance(v, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(v)}</v></c>'
    if isinstance(v, int | float):
        return f'<c r="{ref}"{s}><v>{v}</v></c>'
    text = escape(str(v))
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(sheet: OutSheet) -> str:
    width = max((len(r) for r in sheet.rows), default=1)
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
    ]
    if sheet.freeze_header and len(sheet.rows) > 1:
        parts.append(
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        )
    parts.append('<sheetFormatPr defaultRowHeight="18"/>')
    if sheet.widths:
        parts.append("<cols>")
        for i, w in enumerate(sheet.widths):
            parts.append(f'<col min="{i + 1}" max="{i + 1}" width="{w:.1f}" customWidth="1"/>')
        parts.append("</cols>")
    parts.append("<sheetData>")
    for r, row in enumerate(sheet.rows, start=1):
        height = ' ht="24" customHeight="1"' if r == 1 else ""
        cells = "".join(_cell_xml(f"{col_letter(c)}{r}", cell) for c, cell in enumerate(row))
        parts.append(f'<row r="{r}"{height}>{cells}</row>')
    parts.append("</sheetData>")
    if sheet.autofilter and len(sheet.rows) > 1:
        parts.append(f'<autoFilter ref="A1:{col_letter(width - 1)}{len(sheet.rows)}"/>')
    parts.append("</worksheet>")
    return "".join(parts)


def write_workbook(sheets: Sequence[OutSheet]) -> bytes:
    """An .xlsx file holding ``sheets``."""
    buf = io.BytesIO()
    n = len(sheets)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, n + 1)
        )
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        names = "".join(
            f'<sheet name="{escape(s.name[:31])}" sheetId="{i}" r:id="rId{i}"/>'
            for i, s in enumerate(sheets, start=1)
        )
        filters = "".join(
            f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
            f"'{escape(s.name[:31])}'!$A$1:${col_letter(max(len(s.rows[0]), 1) - 1)}${len(s.rows)}"
            "</definedName>"
            for i, s in enumerate(sheets)
            if s.autofilter and len(s.rows) > 1
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'xmlns:r="{REL_NS}"><sheets>{names}</sheets>'
            + (f"<definedNames>{filters}</definedNames>" if filters else "")
            + "</workbook>",
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/'
            f'2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, n + 1)
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{rels}<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        )
        zf.writestr("xl/styles.xml", STYLES)
        for i, sheet in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet))
    return buf.getvalue()

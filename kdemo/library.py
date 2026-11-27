"""The document library: every file Kraken filed, by issuer then year, with its metadata
and its text (extracted once, cached on disk) for the AI summary and the document chat.

The index is read from Retrievr's ``manifest.json`` in each output folder (one entry per
document) plus any file of the folder tree the manifest does not list. Documents of a
private portal are listed masked: generic title, no source address, no AI, no preview.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kdemo.xlsx import XlsxError, read_sheets

log = logging.getLogger("kdemo.library")

TEXT_VERSION = 1
"""Bump when the extracted text format changes: cached texts are then extracted again."""
PDF, SHEET, OTHER = "pdf", "sheet", "other"
KINDS = {".pdf": PDF, ".xlsx": SHEET, ".xlsm": SHEET}
FORMATS = {".pdf": "PDF", ".xlsx": "Excel", ".xlsm": "Excel", ".xlsb": "Excel (binary)", ".zip": "ZIP archive",
           ".xhtml": "XHTML (ESEF)", ".html": "HTML", ".csv": "CSV"}
LANGS = {"en": "English", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian", "nl": "Dutch",
         "pt": "Portuguese", "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "sv": "Swedish", "da": "Danish"}
TYPE_LABELS = {
    "urd": "Universal registration document",
    "esef": "ESEF annual financial report",
    "agm": "General meeting document",
    "pillar3": "Pillar 3 report",
    "pillar_3": "Pillar 3 report",
    "sfcr": "Solvency and financial condition report",
    "fds": "Financial data supplement",
    "other": "Other document",
}
# "<type>_<period>_<lang>[_<hash>].<ext>", the file names Retrievr writes.
NAME_RE = re.compile(r"^(?P<type>[a-z0-9_]+?)_(?P<period>\d{4}(?:-[A-Z0-9]+)?)_(?P<lang>[a-z]{2})(?:_[0-9a-f]{6,})?$")
WHY = {"url": "the link address", "any": "the link and its text", "link_text": "the link text",
       "link_title": "the link's tooltip", "title": "the link text", "context": "the text around the link",
       "text": "the document's own words", "column_header": "the table column", "row_header": "the table row",
       "heading": "the section heading", "llm": "{ai}, once, when it learned the site",
       "recipe default": "the site's recipe", "default": "the site's recipe"}


def type_label(kind: str) -> str:
    if not kind:
        return "Document"
    if kind in TYPE_LABELS:
        return TYPE_LABELS[kind]
    text = kind.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def period_label(period: str | None) -> str:
    """``2024-FY`` -> ``Full year 2024``, ``2025-Q3`` -> ``Q3 2025``, ``2024-H1`` -> ``H1 2024``."""
    if not period:
        return ""
    m = re.fullmatch(r"(\d{4})-(\w+)", period)
    if not m:
        return period
    year, part = m.groups()
    if part == "FY":
        return f"Full year {year}"
    if part.startswith("9M"):
        return f"Nine months {year}"
    return f"{part} {year}"


def why_label(justification: str, ai_name: str) -> list[dict[str, str]]:
    """``type=x by url /regex/; period=2024-FY by title /.../`` -> plain words per field."""
    out = []
    for part in (justification or "").split("; "):
        m = re.match(r"(\w+)=(\S+) by (recipe default|[\w+:]+)", part)
        if not m:
            continue
        what, value, how = m.groups()
        if what not in ("type", "period", "language"):
            continue
        sources = [WHY.get(h.split(":")[0], h.replace("_", " ")) for h in how.split("+")]
        source = " and ".join(dict.fromkeys(sources)).replace("{ai}", ai_name)
        out.append({"field": what.title(), "value": value, "from": source})
    return out


@dataclass
class LibDoc:
    id: str
    issuer: str
    issuer_name: str
    path: Path
    rel: str
    private: bool
    title: str = ""
    type: str = ""
    period: str | None = None
    fiscal_year: int | None = None
    language: str | None = None
    size: int = 0
    sha256: str = ""
    url: str = ""
    downloaded_at: str = ""
    date: str | None = None
    recipe: str = ""
    recipe_version: int | None = None
    justification: str = ""
    score: float | None = None
    content_type: str = ""

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()

    @property
    def kind(self) -> str:
        return KINDS.get(self.ext, OTHER)

    @property
    def readable(self) -> bool:
        """The AI can read it: text can be extracted and it is not a private document."""
        return self.kind != OTHER and not self.private

    @property
    def key(self) -> str:
        """Cache key of the content (the same file filed twice shares its summary)."""
        return self.sha256 or self.id

    def to_json(self, ai_name: str = "SecureGPT") -> dict[str, Any]:
        masked = self.private
        title = (f"Fund document {self.period or ''}".strip() if masked else self.title) or type_label(self.type)
        return {
            "id": self.id,
            "issuer": self.issuer,
            "issuer_name": self.issuer_name,
            "year": self.fiscal_year,
            "private": self.private,
            "title": title,
            "type": self.type,
            "type_label": "Fund document" if masked else type_label(self.type),
            "period": self.period,
            "period_label": period_label(self.period),
            "language": self.language,
            "language_label": LANGS.get(self.language or "", (self.language or "").upper()),
            "ext": self.ext.lstrip("."),
            "format": FORMATS.get(self.ext, self.ext.lstrip(".").upper()),
            "kind": self.kind,
            "readable": self.readable,
            "size": self.size,
            "sha256": self.sha256,
            "file_name": self.path.name,
            "rel": self.rel,
            "url": "" if masked else self.url,
            "host": "" if masked else _host(self.url),
            "downloaded_at": self.downloaded_at,
            "date": self.date,
            "recipe": "" if masked else self.recipe,
            "recipe_version": self.recipe_version,
            "why": [] if masked else why_label(self.justification, ai_name),
            "score": self.score,
        }


def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else ""


@dataclass
class Source:
    """One output folder to list: the demo's own, or the host's for a private portal."""

    out_dir: Path
    private: bool = False
    issuers: set[str] | None = None
    """Only these issuer folders (None: all but ``exclude``)."""
    exclude: set[str] = field(default_factory=set)


def doc_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).lower().encode(), usedforsecurity=False).hexdigest()[:12]


def scan(sources: Iterable[Source], names: dict[str, str]) -> list[LibDoc]:
    """Every document of the sources, newest year first, then issuer, type and period."""
    docs: dict[str, LibDoc] = {}
    for src in sources:
        out = src.out_dir.resolve()
        if not out.is_dir():
            continue
        listed: set[Path] = set()
        for entry in _manifest(out):
            issuer = str(entry.get("issuer") or "")
            if not _wanted(src, issuer) or not entry.get("path"):
                continue
            path = (out / str(entry["path"])).resolve()
            if out not in path.parents or not path.is_file():
                continue
            listed.add(path)
            doc = _from_entry(entry, path, out, src, names)
            docs.setdefault(doc.id, doc)
        for path in sorted(out.rglob("*")):
            if not path.is_file() or path in listed or path.parent == out or path.name.startswith("."):
                continue
            issuer = path.relative_to(out).parts[0]
            if not _wanted(src, issuer):
                continue
            doc = _from_name(path, out, issuer, src, names)
            docs.setdefault(doc.id, doc)
    return sorted(docs.values(), key=_order)


def _order(d: LibDoc) -> tuple[Any, ...]:
    period = d.period or ""
    return (d.issuer_name.lower(), -(d.fiscal_year or 0), _period_rank(period), d.type, d.path.name)


def _period_rank(period: str) -> int:
    part = period.partition("-")[2]
    return {"FY": 0, "Q4": 1, "9M": 2, "Q3": 3, "H1": 4, "Q2": 5, "Q1": 6}.get(part, 7)


def _wanted(src: Source, issuer: str) -> bool:
    if not issuer:
        return False
    if src.issuers is not None:
        return issuer in src.issuers
    return issuer not in src.exclude


def _manifest(out: Path) -> list[dict[str, Any]]:
    path = out / "manifest.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("manifest %s not read: %s", path, exc)
        return []
    docs = data.get("documents", []) if isinstance(data, dict) else []
    return [d for d in docs if isinstance(d, dict)]


def issuer_name(issuer: str, names: dict[str, str]) -> str:
    if issuer in names:
        return names[issuer]
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_ ]+", issuer) if w) or issuer


def _from_entry(e: dict[str, Any], path: Path, out: Path, src: Source, names: dict[str, str]) -> LibDoc:
    issuer = str(e.get("issuer"))
    fy = e.get("fiscal_year")
    if not isinstance(fy, int):
        fy = _year_of(path, out)
    return LibDoc(
        id=doc_id(path), issuer=issuer, issuer_name=issuer_name(issuer, names), path=path,
        rel=path.relative_to(out).as_posix(), private=src.private,
        title=str(e.get("title") or "").strip(), type=str(e.get("type") or ""), period=e.get("period"),
        fiscal_year=fy, language=e.get("language"), size=int(e.get("size") or path.stat().st_size),
        sha256=str(e.get("sha256") or ""), url=str(e.get("url") or ""),
        downloaded_at=str(e.get("downloaded_at") or ""), date=e.get("date"),
        recipe=str(e.get("recipe") or ""), recipe_version=e.get("recipe_version"),
        justification=str(e.get("justification") or ""),
        score=e.get("score") if isinstance(e.get("score"), (int, float)) else None,
        content_type=str(e.get("content_type") or ""),
    )


def _from_name(path: Path, out: Path, issuer: str, src: Source, names: dict[str, str]) -> LibDoc:
    m = NAME_RE.match(path.stem)
    period = m.group("period") if m else None
    return LibDoc(
        id=doc_id(path), issuer=issuer, issuer_name=issuer_name(issuer, names), path=path,
        rel=path.relative_to(out).as_posix(), private=src.private,
        title=path.stem.replace("_", " "), type=m.group("type") if m else "",
        period=period, fiscal_year=_year_of(path, out), language=m.group("lang") if m else None,
        size=path.stat().st_size,
    )


def _year_of(path: Path, out: Path) -> int | None:
    parts = path.relative_to(out).parts
    if len(parts) >= 3 and parts[1].isdigit():
        return int(parts[1])
    return None


# -- text ------------------------------------------------------------------------------


@dataclass
class DocText:
    """The text of a document, by page (PDF) or by sheet (Excel)."""

    kind: str
    pages: list[str]
    labels: list[str]
    """``"12"`` for a PDF page, the sheet name for a spreadsheet."""
    seconds: float = 0.0

    @property
    def chars(self) -> int:
        return sum(len(p) for p in self.pages)

    def to_json(self) -> dict[str, Any]:
        return {"v": TEXT_VERSION, "kind": self.kind, "pages": self.pages, "labels": self.labels,
                "seconds": self.seconds}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> DocText | None:
        if data.get("v") != TEXT_VERSION:
            return None
        return cls(data["kind"], list(data["pages"]), list(data["labels"]), float(data.get("seconds", 0)))

    def context(self, max_chars: int) -> tuple[str, int]:
        """The text marked by page for a prompt, cut at ``max_chars``; returns it with the
        number of pages (or sheets) included."""
        parts: list[str] = []
        used = 0
        for i, (label, page) in enumerate(zip(self.labels, self.pages, strict=True)):
            head = f"[[Page {label}]]" if self.kind == PDF else f"[[Sheet {label}]]"
            block = f"{head}\n{page.strip()}\n"
            if used + len(block) > max_chars:
                if i == 0:  # never empty: the start of a huge first page
                    parts.append(block[:max_chars])
                    return "".join(parts), 1
                return "".join(parts), i
            parts.append(block)
            used += len(block)
        return "".join(parts), len(self.pages)


class TextUnavailableError(RuntimeError):
    """The document's text cannot be read (format, missing library, damaged file)."""


def extract(doc: LibDoc) -> DocText:
    if doc.kind not in (PDF, SHEET):
        raise TextUnavailableError(f"{FORMATS.get(doc.ext, doc.ext)} files cannot be read by the AI")
    return extract_file(str(doc.path), doc.kind)


def extract_file(path: str, kind: str) -> DocText:
    """Module-level so that it runs in a worker process (pypdf is pure Python: in the
    server's process it would hold the GIL and slow every page request down)."""
    import time

    started = time.monotonic()
    text = _pdf_text(Path(path)) if kind == PDF else _sheet_text(Path(path))
    text.seconds = round(time.monotonic() - started, 2)
    return text


def _pdf_text(path: Path) -> DocText:
    try:
        import pypdf
    except ImportError as exc:
        raise TextUnavailableError("PDF reading needs the pypdf package (pip install pypdf)") from exc
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = pypdf.PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append(_clean(page.extract_text() or ""))
            except Exception:  # one broken page must not lose the document
                pages.append("")
    except Exception as exc:
        raise TextUnavailableError(f"this PDF cannot be read ({type(exc).__name__})") from exc
    if not any(p.strip() for p in pages):
        raise TextUnavailableError("this PDF holds images only (no text layer)")
    return DocText(PDF, pages, [str(i + 1) for i in range(len(pages))])


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v).strip()


def _sheet_text(path: Path) -> DocText:
    try:
        sheets = read_sheets(path.read_bytes())
    except (XlsxError, OSError, ValueError) as exc:
        raise TextUnavailableError(f"this workbook cannot be read ({exc})") from exc
    pages, labels = [], []
    for name, rows in sheets:
        lines = []
        for row in rows:
            cells = [_cell(v) for v in row]
            while cells and not cells[-1]:
                cells.pop()
            if any(cells):
                lines.append(" | ".join(cells))
        if lines:
            pages.append("\n".join(lines))
            labels.append(name)
    if not pages:
        raise TextUnavailableError("this workbook is empty")
    return DocText(SHEET, pages, labels)


def sheet_preview(doc: LibDoc, max_rows: int = 150, max_cols: int = 24) -> list[dict[str, Any]]:
    """The first rows of each sheet, for the viewer."""
    try:
        sheets = read_sheets(doc.path.read_bytes())
    except (XlsxError, OSError, ValueError) as exc:
        raise TextUnavailableError(f"this workbook cannot be read ({exc})") from exc
    out = []
    for name, rows in sheets:
        kept = [[_cell(v) for v in r[:max_cols]] for r in rows if any(v not in (None, "") for v in r)]
        out.append({"name": name, "rows": kept[:max_rows], "more": max(0, len(kept) - max_rows)})
    return out


class TextStore:
    """Extracted texts cached as JSON (``<dir>/<content key>.json``), one extraction at a
    time per document."""

    def __init__(self, folder: Path, *, worker_process: bool = False) -> None:
        self.folder = folder
        self._worker = worker_process
        self._pool: Any = None
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._memo: dict[str, DocText] = {}
        self._info: dict[str, dict[str, Any]] = {}

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def cached(self, doc: LibDoc) -> DocText | None:
        if doc.key in self._memo:
            return self._memo[doc.key]
        path = self.folder / f"{doc.key}.json"
        if not path.is_file():
            return None
        try:
            text = DocText.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            return None
        if text is not None:
            self._remember(doc.key, text)
        return text

    def has(self, doc: LibDoc) -> bool:
        return (self.folder / f"{doc.key}.json").is_file()

    def info(self, doc: LibDoc) -> dict[str, Any] | None:
        """Pages (or sheets) and size of the extracted text, from a small side file: the
        list of documents needs it without reading every text."""
        if doc.key in self._info:
            return self._info[doc.key]
        path = self.folder / f"{doc.key}.info.json"
        info: dict[str, Any] | None = None
        try:
            info = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, ValueError):
            info = None
        if info is None and self.has(doc):  # extracted before side files existed
            text = self.cached(doc)
            if text is not None:
                info = self._write_info(doc, text)
        if info is not None:
            self._info[doc.key] = info
        return info

    def _write_info(self, doc: LibDoc, text: DocText) -> dict[str, Any]:
        info = {"pages": len(text.pages), "chars": text.chars, "kind": text.kind,
                "unit": "pages" if text.kind == PDF else "sheets",
                "labels": text.labels if text.kind != PDF else [], "seconds": text.seconds}
        (self.folder / f"{doc.key}.info.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        self._info[doc.key] = info
        return info

    def get(self, doc: LibDoc) -> DocText:
        with self._lock(doc.key):
            text = self.cached(doc)
            if text is None:
                text = self._extract(doc)
                self.folder.mkdir(parents=True, exist_ok=True)
                tmp = self.folder / f"{doc.key}.json.tmp"
                tmp.write_text(json.dumps(text.to_json(), ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.folder / f"{doc.key}.json")
                self._write_info(doc, text)
                self._remember(doc.key, text)
            return text

    def _extract(self, doc: LibDoc) -> DocText:
        if not self._worker or doc.kind not in (PDF, SHEET):
            return extract(doc)
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures.process import BrokenProcessPool

        with self._guard:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(max_workers=1)
            pool = self._pool
        try:
            return pool.submit(extract_file, str(doc.path), doc.kind).result()  # type: ignore[no-any-return]
        except BrokenProcessPool:
            with self._guard:
                self._pool = None
            return extract(doc)

    def close(self) -> None:
        with self._guard:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def _remember(self, key: str, text: DocText) -> None:
        if len(self._memo) > 12:  # a few recent texts in memory, the rest on disk
            self._memo.pop(next(iter(self._memo)))
        self._memo[key] = text


def warm(docs: Iterable[LibDoc], store: TextStore, *, paused: Callable[[], bool],
         stop: threading.Event) -> None:
    """Extract the text of every readable document ahead of time (smallest first), pausing
    while a run is in progress."""
    for doc in sorted((d for d in docs if d.readable), key=lambda d: d.size):
        while paused() and not stop.is_set():
            stop.wait(2.0)
        if stop.is_set():
            return
        if store.has(doc):
            continue
        try:
            store.get(doc)
        except TextUnavailableError:
            pass
        except Exception:
            log.exception("text of %s not extracted", doc.rel)
        stop.wait(0.05)

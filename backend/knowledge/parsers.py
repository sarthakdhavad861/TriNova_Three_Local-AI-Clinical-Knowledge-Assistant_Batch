"""
knowledge/parsers.py
Format parsers: PDF, TXT, Markdown (→ text chunks with page/section provenance) and
CSV, JSON (→ structured records). Pure functions, stdlib only (PDF reading is injected).

Text is preserved verbatim apart from whitespace at chunk boundaries: no truncation, no
numeric coercion, so clinical units/qualifiers ("500 mg", "eGFR < 30 mL/min/1.73m2") survive.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

from knowledge.store import ChunkDraft, RecordDraft

CATEGORIES = ("symptom", "medicine", "equipment", "other")

# header/key names (normalised: lower-case, spaces→underscores) that identify the record name
NAME_KEYS = ("name", "drug", "drug_name", "medicine", "medicine_name", "generic_name", "brand_name",
             "equipment", "equipment_name", "device", "device_name", "item")
_MEDICINE_HINTS = {"drug", "drug_name", "medicine", "medicine_name", "generic_name", "brand_name",
                   "dose", "dosage", "contraindications"}
_EQUIPMENT_HINTS = {"equipment", "equipment_name", "device", "device_name", "model", "manufacturer"}
_MAX_WARNINGS = 20


class IngestionError(Exception):
    """A file was rejected. `code` is a stable machine-readable reason."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Parsed:
    chunks: list[ChunkDraft] = field(default_factory=list)
    records: list[RecordDraft] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    category: str | None = None


def _norm(h: str) -> str:
    return re.sub(r"\s+", "_", str(h).strip().lower())


# ── text chunking ─────────────────────────────────────────────────────────────
_SENT = re.compile(r"(?<=[.!?])\s+")
_PARA = re.compile(r"\n\s*\n")


def _split_long(par: str, max_words: int) -> list[str]:
    pieces: list[str] = []
    cur: list[str] = []
    n = 0
    for sent in _SENT.split(par):
        w = sent.split()
        if not w:
            continue
        if len(w) > max_words:                       # no sentence boundary: hard split on words
            if cur:
                pieces.append(" ".join(cur)); cur, n = [], 0
            pieces += [" ".join(w[i:i + max_words]) for i in range(0, len(w), max_words)]
            continue
        if cur and n + len(w) > max_words:
            pieces.append(" ".join(cur)); cur, n = [], 0
        cur.append(" ".join(w)); n += len(w)
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def pack_blocks(blocks, max_words: int) -> list[ChunkDraft]:
    """blocks: iterable of (page, section, paragraph). Chunks never span pages or sections."""
    chunks: list[ChunkDraft] = []
    cur: list[str] = []
    cur_key = None
    n = 0

    def flush():
        nonlocal cur, n
        if cur:
            chunks.append(ChunkDraft(len(chunks), "\n\n".join(cur), cur_key[0], cur_key[1]))
        cur, n = [], 0

    for page, section, par in blocks:
        par = par.strip()
        if not par:
            continue
        pieces = [par] if len(par.split()) <= max_words else _split_long(par, max_words)
        for piece in pieces:
            w = len(piece.split())
            key = (page, section)
            if key != cur_key or n + w > max_words:
                flush()
                cur_key = key
            cur.append(piece); n += w
    flush()
    return chunks


def _require_chunks(chunks: list[ChunkDraft]) -> list[ChunkDraft]:
    if not chunks:
        raise IngestionError("no_content", "No extractable text content found.")
    return chunks


def parse_text(text: str, max_words: int) -> Parsed:
    blocks = [(None, "", p) for p in _PARA.split(text)]
    return Parsed(chunks=_require_chunks(pack_blocks(blocks, max_words)))


_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


def parse_markdown(text: str, max_words: int) -> Parsed:
    blocks: list[tuple] = []
    section, buf = "", []

    def flush_buf():
        if buf:
            blocks.append((None, section, "\n".join(buf)))
            buf.clear()

    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            flush_buf()
            section = m.group(1).strip()
        elif not line.strip():
            flush_buf()
        else:
            buf.append(line)
    flush_buf()
    return Parsed(chunks=_require_chunks(pack_blocks(blocks, max_words)))


def parse_pdf_pages(pages: list[tuple[int, str]], max_words: int) -> Parsed:
    """pages: [(page_number, text)] as returned by a PDF reader."""
    blocks = [(num, "", p) for num, txt in pages for p in _PARA.split(txt or "")]
    chunks = pack_blocks(blocks, max_words)
    if not chunks:
        raise IngestionError("no_text", "No extractable text in PDF (scanned image? OCR is not supported).")
    return Parsed(chunks=chunks)


def read_pdf_pages(path: str) -> list[tuple[int, str]]:
    """Default PDF reader (PyMuPDF, imported lazily)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:  # pragma: no cover - environment dependent
        raise IngestionError("pdf_support_missing", f"PyMuPDF is not installed: {e}")
    try:
        doc = fitz.open(path)
    except Exception as e:  # pragma: no cover - environment dependent
        raise IngestionError("malformed_pdf", f"PDF could not be opened: {str(e)[:150]}")
    try:
        if getattr(doc, "needs_pass", False):
            raise IngestionError("encrypted_pdf", "PDF is password-protected.")
        return [(i, page.get_text("text")) for i, page in enumerate(doc, start=1)]
    except IngestionError:
        raise
    except Exception as e:  # pragma: no cover - environment dependent
        raise IngestionError("malformed_pdf", f"PDF text extraction failed: {str(e)[:150]}")
    finally:
        doc.close()


# ── structured records ────────────────────────────────────────────────────────
def _infer_category(keys: set[str], explicit: str | None) -> str:
    if explicit:
        return explicit
    med, eq = bool(keys & _MEDICINE_HINTS), bool(keys & _EQUIPMENT_HINTS)
    return "medicine" if med and not eq else "equipment" if eq and not med else "other"


def _warn(warnings: list[str], msg: str) -> None:
    if len(warnings) < _MAX_WARNINGS:
        warnings.append(msg)
    elif len(warnings) == _MAX_WARNINGS:
        warnings.append("further warnings suppressed")


def parse_csv(text: str, category: str | None) -> Parsed:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max(",;\t|", key=lambda d: first.count(d)) if first else ","
    if first.count(delim) == 0:
        delim = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    warnings: list[str] = []
    header: list[str] | None = None
    name_idx = -1
    rows: list[RecordDraft] = []
    try:
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            line = reader.line_num
            if header is None:
                header = [h.strip() for h in row]
                if any(not h for h in header):
                    raise IngestionError("malformed_csv", f"Header row (line {line}) has an empty column name.")
                normed = [_norm(h) for h in header]
                if len(set(normed)) != len(normed):
                    raise IngestionError("malformed_csv", "Header row has duplicate column names.")
                name_idx = next((i for i, h in enumerate(normed) if h in NAME_KEYS), -1)
                if name_idx < 0:
                    raise IngestionError(
                        "no_name_column",
                        f"No name column found. Expected one of {list(NAME_KEYS)}; got {header}.")
                category = _infer_category(set(normed), category)
                continue
            if len(row) > len(header):
                raise IngestionError(
                    "malformed_csv", f"Line {line} has {len(row)} fields but the header has {len(header)}.")
            if len(row) < len(header):
                _warn(warnings, f"line {line}: {len(row)} of {len(header)} fields; missing values left empty")
                row = row + [""] * (len(header) - len(row))
            values = [c.strip() for c in row]
            name = values[name_idx]
            if not name:
                _warn(warnings, f"line {line}: skipped (empty name)")
                continue
            rows.append(RecordDraft(line, category, name, dict(zip(header, values))))
    except csv.Error as e:
        raise IngestionError("malformed_csv", f"CSV parse error near line {reader.line_num}: {e}")
    if header is None:
        raise IngestionError("empty", "CSV file has no header row.")
    if not rows:
        raise IngestionError("no_records", "CSV file has no usable data rows.")
    return Parsed(records=rows, warnings=warnings, category=category)


def parse_json(text: str, category: str | None) -> Parsed:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise IngestionError("malformed_json", f"Invalid JSON at line {e.lineno} column {e.colno}: {e.msg}")
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) != 1:
            raise IngestionError(
                "unsupported_json", "JSON object must contain exactly one list of records "
                                    "(or the file must itself be a list of objects).")
        data = lists[0]
    if not isinstance(data, list) or not data:
        raise IngestionError("unsupported_json", "JSON must be a non-empty list of record objects.")
    warnings: list[str] = []
    rows: list[RecordDraft] = []
    all_keys: set[str] = set()
    pending = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise IngestionError("unsupported_json", f"Item {i} is not an object.")
        keys = {_norm(k): k for k in item}
        all_keys |= set(keys)
        pending.append((i, item, keys))
    category = _infer_category(all_keys, category)
    for i, item, keys in pending:
        name_key = next((keys[k] for k in NAME_KEYS if k in keys), None)
        name = str(item[name_key]).strip() if name_key is not None and item[name_key] is not None else ""
        if not name:
            _warn(warnings, f"item {i}: skipped (no name field among {list(NAME_KEYS)})")
            continue
        rows.append(RecordDraft(i, category, name, item))
    if not rows:
        raise IngestionError("no_records", f"No JSON items had a usable name field ({list(NAME_KEYS)}).")
    return Parsed(records=rows, warnings=warnings, category=category)

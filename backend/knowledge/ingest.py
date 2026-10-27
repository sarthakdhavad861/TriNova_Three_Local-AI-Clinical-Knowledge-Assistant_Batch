"""
knowledge/ingest.py
Document and dataset ingestion: validate → hash → parse → embed → atomic commit.

Guarantees (see tests/test_knowledge.py):
  * identical re-upload is a no-op; changed content creates a new version and supersedes the old one
  * identical content under a different filename is rejected as a duplicate
  * a rejected or failed file leaves no chunks, records, versions or vectors behind
  * every outcome (success, unchanged, duplicate, error) is persisted as an ingestion event
The embedder, vector index and PDF reader are injected so the pipeline is testable offline.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol

from knowledge.parsers import (
    CATEGORIES, IngestionError, Parsed, parse_csv, parse_json, parse_markdown,
    parse_pdf_pages, parse_text, read_pdf_pages,
)
from knowledge.store import KnowledgeStore

log = logging.getLogger("knowledge.ingest")

KINDS = {".pdf": "pdf", ".txt": "text", ".md": "markdown", ".markdown": "markdown",
         ".csv": "csv", ".json": "json"}
SUPPORTED_EXTS = tuple(sorted(KINDS))
_SHORT = {"pdf": "pdf", "text": "txt", "markdown": "md", "csv": "csv", "json": "json"}


class VectorIndex(Protocol):
    def upsert(self, ids: list[str], embeddings: list[list[float]], documents: list[str],
               metadatas: list[dict]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...


@dataclass
class IngestResult:
    status: str                       # success | unchanged | duplicate | error
    message: str
    event_id: int | None = None
    source_id: str | None = None
    version: int | None = None
    sha256: str | None = None
    chunk_count: int = 0
    record_count: int = 0
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def safe_basename(name: str) -> str:
    base = PurePosixPath((name or "").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:200] or "unnamed"


def make_source_id(filename: str, kind: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")[:80] or "source"
    return f"{stem}-{_SHORT[kind]}"


class IngestionService:
    def __init__(self, store: KnowledgeStore, index: VectorIndex,
                 embedder: Callable[[list[str]], list[list[float]]], *, embed_model: str = "",
                 pdf_reader: Callable[[str], list[tuple[int, str]]] = read_pdf_pages,
                 max_bytes: int = 50 * 1024 ** 2, max_words: int = 180, embed_batch: int = 32):
        self.store, self.index, self.embedder = store, index, embedder
        self.embed_model, self.pdf_reader = embed_model, pdf_reader
        self.max_bytes, self.max_words, self.embed_batch = max_bytes, max_words, embed_batch

    # ── public entry point: never raises for per-file problems ────────────────
    def ingest_file(self, path, original_name: str, *, category: str | None = None,
                    license: str | None = None, origin: str | None = None,
                    event_id: int | None = None) -> IngestResult:
        name = safe_basename(original_name)
        if event_id is None:
            event_id = self.store.begin_event(name)
        try:
            result = self._ingest(str(path), name, category, license, origin)
        except IngestionError as e:
            result = IngestResult("error", str(e), error_code=e.code)
        except Exception as e:  # noqa: BLE001 - recorded, not hidden
            log.exception("unexpected ingestion failure for %s", name)
            result = IngestResult("error", f"Unexpected error ({type(e).__name__}): {str(e)[:200]}",
                                  error_code="internal_error")
        result.event_id = event_id
        try:
            self.store.finish_event(
                event_id, status=result.status, message=result.message, source_id=result.source_id,
                sha256=result.sha256, error_code=result.error_code, version=result.version,
                chunk_count=result.chunk_count, record_count=result.record_count)
        except Exception:  # noqa: BLE001
            log.exception("could not persist ingestion event %s", event_id)
        return result

    # ── pipeline ──────────────────────────────────────────────────────────────
    def _ingest(self, path: str, name: str, category, license, origin) -> IngestResult:
        ext = Path(name).suffix.lower()
        kind = KINDS.get(ext)
        if kind is None:
            raise IngestionError("unsupported_type",
                                 f"Unsupported file type '{ext or name}'. Supported: {', '.join(SUPPORTED_EXTS)}.")
        if category is not None and category not in CATEGORIES:
            raise IngestionError("invalid_category", f"Category must be one of {list(CATEGORIES)}.")
        try:
            size = os.path.getsize(path)
        except OSError as e:
            raise IngestionError("unreadable", f"File could not be read: {e.strerror or e}")
        if size == 0:
            raise IngestionError("empty", "File is empty.")
        if size > self.max_bytes:
            raise IngestionError("too_large", f"File is {size} bytes; the limit is {self.max_bytes}.")

        data = Path(path).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        source_id = make_source_id(name, kind)

        dup = self.store.check_duplicate(source_id, sha)
        if dup:
            return self._duplicate_result(dup[0], dup[1], source_id, sha, name)

        parsed = self._parse(kind, path, data, category)
        vectors = self._embed([c.text for c in parsed.chunks])
        meta = {"source_id": source_id, "kind": kind, "category": parsed.category or category or "",
                "filename": name}

        def write_vectors(version: int, chunk_ids: list[str]) -> None:
            if not chunk_ids:
                return
            metadatas = [
                {**meta, "version": version, "chunk_id": cid, "title": name,
                 "page_number": c.page or 0, "section_heading": c.section,
                 "source_type": "pdf" if kind == "pdf" else "document",   # legacy retrieval filters; Phase 3 normalises
                 "number": "", "start": 0.0, "end": 0.0}
                for cid, c in zip(chunk_ids, parsed.chunks)]
            try:
                self.index.upsert(chunk_ids, vectors, [c.text for c in parsed.chunks], metadatas)
            except BaseException:
                try:
                    self.index.delete(chunk_ids)       # best effort; the DB transaction rolls back regardless
                except Exception:  # noqa: BLE001
                    log.warning("cleanup of partially written vectors failed", exc_info=True)
                raise

        commit = self.store.commit_version(
            source_id=source_id, display_name=name, kind=kind, category=parsed.category or category,
            license=license, origin=origin, original_filename=name, sha256=sha, byte_size=size,
            embed_model=self.embed_model, warnings=parsed.warnings, chunks=parsed.chunks,
            records=parsed.records, before_commit=write_vectors)

        if commit.status != "committed":                      # lost a race to an identical concurrent upload
            return self._duplicate_result(commit.status, commit.duplicate_of or source_id, source_id, sha, name)

        warnings = list(parsed.warnings)
        if commit.superseded_chunk_ids:
            try:
                self.index.delete(commit.superseded_chunk_ids)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"previous version's vectors could not be removed ({type(e).__name__}); "
                                "they are ignored at query time because their chunks are no longer active")
        note = " Previous version superseded." if commit.version and commit.version > 1 else ""
        return IngestResult(
            "success", f"'{name}' ingested as {source_id} v{commit.version}: {len(parsed.chunks)} chunks, "
                       f"{len(parsed.records)} records.{note}",
            source_id=source_id, version=commit.version, sha256=sha, chunk_count=len(parsed.chunks),
            record_count=len(parsed.records), warnings=warnings)

    @staticmethod
    def _duplicate_result(kind: str, other: str | None, source_id: str, sha: str, name: str) -> IngestResult:
        if kind == "unchanged":
            return IngestResult("unchanged", f"'{name}' is already ingested with identical content; nothing changed.",
                                source_id=source_id, sha256=sha)
        return IngestResult("duplicate", f"'{name}' has identical content to already-ingested source '{other}'; "
                                         "not ingested.", source_id=other, sha256=sha, error_code="duplicate_content")

    def _parse(self, kind: str, path: str, data: bytes, category) -> Parsed:
        if kind == "pdf":
            if not data.startswith(b"%PDF-"):
                raise IngestionError("malformed_pdf", "File does not look like a PDF (missing %PDF- header).")
            return parse_pdf_pages(self.pdf_reader(path), self.max_words)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise IngestionError("not_utf8", "File is not valid UTF-8 text.")
        if "\x00" in text:
            raise IngestionError("binary_content", "File contains binary data.")
        if not text.strip():
            raise IngestionError("empty", "File contains only whitespace.")
        if kind == "text":
            return parse_text(text, self.max_words)
        if kind == "markdown":
            return parse_markdown(text, self.max_words)
        if kind == "csv":
            return parse_csv(text, category)
        return parse_json(text, category)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.embed_batch):
            batch = texts[i:i + self.embed_batch]
            out = self.embedder(batch)
            if len(out) != len(batch):
                raise IngestionError("embedding_failed", "Embedder returned the wrong number of vectors.")
            vectors.extend(out)
        if vectors and len({len(v) for v in vectors}) != 1:
            raise IngestionError("embedding_failed", "Embedder returned vectors of differing dimensions.")
        return vectors

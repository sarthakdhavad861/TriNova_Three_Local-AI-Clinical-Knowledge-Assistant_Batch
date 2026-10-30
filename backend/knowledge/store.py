"""
knowledge/store.py
SQLite system of record for the medical knowledge base (stdlib only).

SQLite holds source identity, versions, provenance, chunk text, structured records and
ingestion events. The vector index (Chroma) is a *derived* index keyed by chunk_id; it can be
rebuilt from the `chunks` table and must be cross-checked against it at query time
(see get_active_chunks) because a crash can leave orphaned vectors.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  source_id    TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  kind         TEXT NOT NULL,
  category     TEXT,
  license      TEXT,
  origin       TEXT,
  created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_versions(
  version_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id         TEXT NOT NULL REFERENCES sources(source_id),
  version           INTEGER NOT NULL,
  original_filename TEXT NOT NULL,
  sha256            TEXT NOT NULL,
  byte_size         INTEGER NOT NULL,
  status            TEXT NOT NULL CHECK(status IN ('active','superseded')),
  chunk_count       INTEGER NOT NULL DEFAULT 0,
  record_count      INTEGER NOT NULL DEFAULT 0,
  embed_model       TEXT,
  warnings          TEXT NOT NULL DEFAULT '[]',
  ingested_at       TEXT NOT NULL,
  UNIQUE(source_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_version ON source_versions(source_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_versions_sha ON source_versions(sha256);
CREATE TABLE IF NOT EXISTS chunks(
  chunk_id   TEXT PRIMARY KEY,
  version_id INTEGER NOT NULL REFERENCES source_versions(version_id),
  source_id  TEXT NOT NULL,
  ordinal    INTEGER NOT NULL,
  page       INTEGER,
  section    TEXT NOT NULL DEFAULT '',
  text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(version_id);
CREATE TABLE IF NOT EXISTS records(
  record_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id INTEGER NOT NULL REFERENCES source_versions(version_id),
  source_id  TEXT NOT NULL,
  row_number INTEGER NOT NULL,
  category   TEXT NOT NULL,
  name       TEXT NOT NULL,
  fields     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_version ON records(version_id);
CREATE INDEX IF NOT EXISTS idx_records_name ON records(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS ingestion_events(
  event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  filename     TEXT NOT NULL,
  source_id    TEXT,
  sha256       TEXT,
  status       TEXT NOT NULL CHECK(status IN ('processing','success','unchanged','duplicate','error')),
  error_code   TEXT,
  message      TEXT NOT NULL DEFAULT '',
  version      INTEGER,
  chunk_count  INTEGER NOT NULL DEFAULT 0,
  record_count INTEGER NOT NULL DEFAULT 0
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, chunk_id UNINDEXED, tokenize='porter unicode61 remove_diacritics 2');
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ChunkDraft:
    ordinal: int
    text: str
    page: int | None = None
    section: str = ""


@dataclass
class RecordDraft:
    row_number: int
    category: str
    name: str
    fields: dict


@dataclass
class CommitResult:
    status: str                      # committed | unchanged | duplicate
    source_id: str
    version: int | None = None
    chunk_ids: list[str] = field(default_factory=list)
    superseded_chunk_ids: list[str] = field(default_factory=list)
    duplicate_of: str | None = None


class KnowledgeStore:
    def __init__(self, db_path):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        c = self._connect()
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            try:
                c.executescript(FTS_SCHEMA)
                self.fts_enabled = True
            except sqlite3.OperationalError:          # SQLite built without FTS5
                self.fts_enabled = False
            if self.fts_enabled and not c.execute("SELECT 1 FROM chunks_fts LIMIT 1").fetchone():
                c.execute(
                    """INSERT INTO chunks_fts(text, chunk_id)
                       SELECT c.text, c.chunk_id FROM chunks c
                       JOIN source_versions v ON v.version_id=c.version_id WHERE v.status='active'""")
        finally:
            c.close()

    # ── connection helpers ────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE … COMMIT; any exception rolls everything back."""
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            c.close()

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        c = self._connect()
        try:
            return [dict(r) for r in c.execute(sql, params).fetchall()]
        finally:
            c.close()

    # ── ingestion events (persisted job state and error log) ──────────────────
    def begin_event(self, filename: str) -> int:
        with self.transaction() as c:
            cur = c.execute(
                "INSERT INTO ingestion_events(started_at, filename, status) VALUES(?,?,'processing')",
                (_now(), filename),
            )
            return cur.lastrowid

    def finish_event(self, event_id: int, *, status: str, message: str, source_id=None, sha256=None,
                     error_code=None, version=None, chunk_count=0, record_count=0) -> None:
        with self.transaction() as c:
            c.execute(
                """UPDATE ingestion_events SET finished_at=?, status=?, message=?, source_id=?, sha256=?,
                   error_code=?, version=?, chunk_count=?, record_count=? WHERE event_id=?""",
                (_now(), status, message[:1000], source_id, sha256, error_code, version,
                 chunk_count, record_count, event_id),
            )

    def get_event(self, event_id: int) -> dict | None:
        rows = self._query("SELECT * FROM ingestion_events WHERE event_id=?", (event_id,))
        return rows[0] if rows else None

    def list_events(self, limit: int = 50, status: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        if status:
            return self._query("SELECT * FROM ingestion_events WHERE status=? ORDER BY event_id DESC LIMIT ?",
                               (status, limit))
        return self._query("SELECT * FROM ingestion_events ORDER BY event_id DESC LIMIT ?", (limit,))

    # ── duplicate detection (cheap pre-check; re-checked inside the commit) ───
    def check_duplicate(self, source_id: str, sha256: str) -> tuple[str, str | None] | None:
        same = self._query(
            "SELECT version FROM source_versions WHERE source_id=? AND status='active' AND sha256=?",
            (source_id, sha256))
        if same:
            return ("unchanged", source_id)
        other = self._query(
            "SELECT source_id FROM source_versions WHERE status='active' AND sha256=? AND source_id<>?",
            (sha256, source_id))
        if other:
            return ("duplicate", other[0]["source_id"])
        return None

    # ── the atomic write ──────────────────────────────────────────────────────
    def commit_version(self, *, source_id, display_name, kind, category, license, origin,
                       original_filename, sha256, byte_size, embed_model, warnings,
                       chunks: list[ChunkDraft], records: list[RecordDraft],
                       before_commit=None) -> CommitResult:
        """
        Create a new active version of a source and supersede the previous one, atomically.
        `before_commit(version, chunk_ids)` runs inside the transaction (used to write vectors);
        if it raises, the whole transaction is rolled back.
        """
        with self.transaction() as c:
            same = c.execute(
                "SELECT version FROM source_versions WHERE source_id=? AND status='active' AND sha256=?",
                (source_id, sha256)).fetchone()
            if same:
                return CommitResult("unchanged", source_id, same["version"])
            other = c.execute(
                "SELECT source_id FROM source_versions WHERE status='active' AND sha256=? AND source_id<>?",
                (sha256, source_id)).fetchone()
            if other:
                return CommitResult("duplicate", source_id, duplicate_of=other["source_id"])

            c.execute(
                """INSERT INTO sources(source_id, display_name, kind, category, license, origin, created_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET display_name=excluded.display_name, kind=excluded.kind,
                     category=COALESCE(excluded.category, sources.category),
                     license=COALESCE(excluded.license, sources.license),
                     origin=COALESCE(excluded.origin, sources.origin)""",
                (source_id, display_name, kind, category, license, origin, _now()))

            old = c.execute("SELECT version_id FROM source_versions WHERE source_id=? AND status='active'",
                            (source_id,)).fetchone()
            old_chunk_ids: list[str] = []
            if old:
                old_chunk_ids = [r[0] for r in c.execute(
                    "SELECT chunk_id FROM chunks WHERE version_id=?", (old["version_id"],))]
                c.execute("UPDATE source_versions SET status='superseded' WHERE version_id=?", (old["version_id"],))
                if self.fts_enabled and old_chunk_ids:
                    c.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({','.join('?' * len(old_chunk_ids))})",
                              old_chunk_ids)

            version = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM source_versions WHERE source_id=?",
                                (source_id,)).fetchone()[0]
            cur = c.execute(
                """INSERT INTO source_versions(source_id, version, original_filename, sha256, byte_size, status,
                   chunk_count, record_count, embed_model, warnings, ingested_at)
                   VALUES(?,?,?,?,?,'active',?,?,?,?,?)""",
                (source_id, version, original_filename, sha256, byte_size, len(chunks), len(records),
                 embed_model, json.dumps(warnings), _now()))
            version_id = cur.lastrowid

            chunk_ids = [f"{source_id}:v{version}:{ch.ordinal}" for ch in chunks]
            c.executemany(
                "INSERT INTO chunks(chunk_id, version_id, source_id, ordinal, page, section, text) VALUES(?,?,?,?,?,?,?)",
                [(cid, version_id, source_id, ch.ordinal, ch.page, ch.section, ch.text)
                 for cid, ch in zip(chunk_ids, chunks)])
            if self.fts_enabled:
                c.executemany("INSERT INTO chunks_fts(text, chunk_id) VALUES(?,?)",
                              [(ch.text, cid) for cid, ch in zip(chunk_ids, chunks)])
            c.executemany(
                "INSERT INTO records(version_id, source_id, row_number, category, name, fields) VALUES(?,?,?,?,?,?)",
                [(version_id, source_id, r.row_number, r.category, r.name,
                  json.dumps(r.fields, ensure_ascii=False)) for r in records])

            if before_commit:
                before_commit(version, chunk_ids)
            return CommitResult("committed", source_id, version, chunk_ids, old_chunk_ids)

    # ── inspection ────────────────────────────────────────────────────────────
    @staticmethod
    def _decode_warnings(row: dict) -> dict:
        if "warnings" in row and isinstance(row["warnings"], str):
            row["warnings"] = json.loads(row["warnings"] or "[]")
        return row

    def list_sources(self) -> list[dict]:
        rows = self._query(
            """SELECT s.source_id, s.display_name, s.kind, s.category, s.license, s.origin, s.created_at,
                      v.version, v.original_filename, v.sha256, v.byte_size, v.chunk_count, v.record_count,
                      v.embed_model, v.warnings, v.ingested_at
               FROM sources s LEFT JOIN source_versions v ON v.source_id=s.source_id AND v.status='active'
               ORDER BY s.source_id""")
        return [self._decode_warnings(r) for r in rows]

    def get_source(self, source_id: str) -> dict | None:
        src = self._query("SELECT * FROM sources WHERE source_id=?", (source_id,))
        if not src:
            return None
        versions = self._query(
            """SELECT version, status, original_filename, sha256, byte_size, chunk_count, record_count,
                      embed_model, warnings, ingested_at FROM source_versions WHERE source_id=? ORDER BY version""",
            (source_id,))
        out = src[0]
        out["versions"] = [self._decode_warnings(v) for v in versions]
        return out

    def list_chunks(self, source_id: str, *, version: int | None = None, limit: int = 50, offset: int = 0):
        limit, offset = max(1, min(int(limit), 500)), max(0, int(offset))
        if version is None:
            sql = """SELECT c.chunk_id, c.ordinal, c.page, c.section, c.text, v.version, v.status
                     FROM chunks c JOIN source_versions v ON v.version_id=c.version_id
                     WHERE c.source_id=? AND v.status='active' ORDER BY c.ordinal LIMIT ? OFFSET ?"""
            return self._query(sql, (source_id, limit, offset))
        sql = """SELECT c.chunk_id, c.ordinal, c.page, c.section, c.text, v.version, v.status
                 FROM chunks c JOIN source_versions v ON v.version_id=c.version_id
                 WHERE c.source_id=? AND v.version=? ORDER BY c.ordinal LIMIT ? OFFSET ?"""
        return self._query(sql, (source_id, version, limit, offset))

    def list_records(self, *, source_id: str | None = None, category: str | None = None,
                     name: str | None = None, limit: int = 50) -> list[dict]:
        """Active records only. `name` is a case-insensitive exact match."""
        limit = max(1, min(int(limit), 500))
        where, params = ["v.status='active'"], []
        if source_id:
            where.append("r.source_id=?"); params.append(source_id)
        if category:
            where.append("r.category=?"); params.append(category)
        if name:
            where.append("r.name=? COLLATE NOCASE"); params.append(name.strip())
        rows = self._query(
            f"""SELECT r.record_id, r.source_id, v.version, r.row_number, r.category, r.name, r.fields
                FROM records r JOIN source_versions v ON v.version_id=r.version_id
                WHERE {' AND '.join(where)} ORDER BY r.source_id, r.row_number LIMIT ?""",
            tuple(params) + (limit,))
        for r in rows:
            r["fields"] = json.loads(r["fields"])
        return rows

    def record_index(self) -> list[dict]:
        """(record_id, name, category) of every ACTIVE record — used for exact-name matching of a question."""
        return self._query(
            """SELECT r.record_id, r.name, r.category
               FROM records r JOIN source_versions v ON v.version_id=r.version_id
               WHERE v.status='active' ORDER BY r.record_id""")

    def get_records(self, record_ids: list) -> list[dict]:
        """Active records by id (fields decoded), in the order of `record_ids`."""
        if not record_ids:
            return []
        marks = ",".join("?" * len(record_ids))
        rows = self._query(
            f"""SELECT r.record_id, r.source_id, v.version, r.row_number, r.category, r.name, r.fields,
                       s.display_name, s.license, s.origin
                FROM records r JOIN source_versions v ON v.version_id=r.version_id
                JOIN sources s ON s.source_id=r.source_id
                WHERE v.status='active' AND r.record_id IN ({marks})""", tuple(record_ids))
        for r in rows:
            r["fields"] = json.loads(r["fields"])
        order = {rid: i for i, rid in enumerate(record_ids)}
        return sorted(rows, key=lambda r: order[r["record_id"]])

    def get_active_chunks(self, chunk_ids: list[str]) -> dict[str, dict]:
        """Chunk rows for the given ids that belong to an ACTIVE version (filters orphaned/stale vectors)."""
        if not chunk_ids:
            return {}
        marks = ",".join("?" * len(chunk_ids))
        rows = self._query(
            f"""SELECT c.chunk_id, c.source_id, c.ordinal, c.page, c.section, c.text, v.version, s.display_name,
                       s.kind, s.category, s.license, s.origin
                FROM chunks c JOIN source_versions v ON v.version_id=c.version_id
                JOIN sources s ON s.source_id=c.source_id
                WHERE v.status='active' AND c.chunk_id IN ({marks})""", tuple(chunk_ids))
        return {r["chunk_id"]: r for r in rows}

    def search_lexical(self, terms: list[str], limit: int = 20) -> list[str]:
        """Active chunk ids ranked by BM25 for ANY of the terms (terms are quoted; no query-syntax injection)."""
        if not self.fts_enabled or not terms:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        try:
            rows = self._query("SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
                               (match, max(1, int(limit))))
        except sqlite3.OperationalError:
            return []
        return [r["chunk_id"] for r in rows]

    def totals(self) -> dict:
        r = self._query(
            """SELECT (SELECT COUNT(*) FROM sources) AS sources,
                      COALESCE((SELECT SUM(chunk_count) FROM source_versions WHERE status='active'),0) AS chunks,
                      COALESCE((SELECT SUM(record_count) FROM source_versions WHERE status='active'),0) AS records""")
        return r[0]

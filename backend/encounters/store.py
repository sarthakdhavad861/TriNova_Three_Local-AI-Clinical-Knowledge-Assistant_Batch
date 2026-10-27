"""
encounters/store.py
Patient-encounter isolation (stdlib only).

An *encounter* is one patient consultation. Everything private to it — conversation history and context notes —
lives in its own SQLite file, physically separate from the shared knowledge base (knowledge/store.py never touches it).

Security model (local, single-doctor deployment; there are NO user accounts):
  * creating an encounter returns an unguessable id and a secret access token ONCE; only sha256(token) is stored;
  * every read/write goes through `_authorize(encounter_id, token)` and every SQL statement is additionally scoped by
    encounter_id — wrong token, missing token, unknown id and erased encounter are indistinguishable (`NotFound`);
  * there is deliberately NO operation that lists encounters or looks anything up by message/note id alone;
  * `erase()` hard-deletes an encounter's rows; `purge_older_than()` implements automatic expiry.
Not provided: encryption at rest (use full-disk encryption), per-doctor authentication, rate limiting. Do not store real
patient identifiers — this project is a demo that uses synthetic data only.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

MAX_LABEL = 80
MAX_NOTE_CHARS = 2000
MAX_MESSAGE_CHARS = 20000
ROLES = ("user", "assistant")

SCHEMA = """
CREATE TABLE IF NOT EXISTS encounters (
    encounter_id TEXT PRIMARY KEY,
    token_hash   TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    last_active  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    message_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content      TEXT NOT NULL,
    meta         TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_enc ON messages(encounter_id, message_id);
CREATE TABLE IF NOT EXISTS context_notes (
    note_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_enc ON context_notes(encounter_id, note_id);
"""


class NotFound(Exception):
    """Unknown encounter, wrong/missing token, or an object that belongs to a different encounter. Deliberately uniform."""


class InvalidInput(ValueError):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8", "replace")).hexdigest()


_DUMMY_HASH = _hash("no-such-encounter")


class EncounterStore:
    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ── plumbing ──────────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def _conn(self):
        c = self._connect()
        try:
            yield c
        finally:
            c.close()

    def _authorize(self, c: sqlite3.Connection, encounter_id: str, token: str | None) -> None:
        """Raise NotFound unless (encounter_id, token) is a valid pair. Constant-time compare; same work either way."""
        row = c.execute("SELECT token_hash FROM encounters WHERE encounter_id=?",
                        (encounter_id if isinstance(encounter_id, str) else "",)).fetchone()
        ok = hmac.compare_digest((row["token_hash"] if row else _DUMMY_HASH), _hash(token if isinstance(token, str) else ""))
        if not (row and ok):
            raise NotFound("Encounter not found")

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def create(self, label: str = "") -> dict:
        label = (label or "").strip()
        if len(label) > MAX_LABEL:
            raise InvalidInput(f"label is limited to {MAX_LABEL} characters")
        encounter_id, token, now = uuid.uuid4().hex, secrets.token_urlsafe(32), self.clock()
        with self._conn() as c:
            c.execute("INSERT INTO encounters(encounter_id, token_hash, label, created_at, last_active) VALUES (?,?,?,?,?)",
                      (encounter_id, _hash(token), label, now, now))
        return {"encounter_id": encounter_id, "access_token": token, "label": label, "created_at": now}

    def authorize(self, encounter_id: str, token: str | None) -> bool:
        with self._conn() as c:
            try:
                self._authorize(c, encounter_id, token)
                return True
            except NotFound:
                return False

    def metadata(self, encounter_id: str, token: str | None) -> dict:
        with self._conn() as c:
            self._authorize(c, encounter_id, token)
            r = c.execute("SELECT encounter_id, label, created_at, last_active FROM encounters WHERE encounter_id=?",
                          (encounter_id,)).fetchone()
            d = dict(r)
            d["messages"] = c.execute("SELECT COUNT(*) FROM messages WHERE encounter_id=?", (encounter_id,)).fetchone()[0]
            d["context_notes"] = c.execute("SELECT COUNT(*) FROM context_notes WHERE encounter_id=?",
                                           (encounter_id,)).fetchone()[0]
            return d

    def erase(self, encounter_id: str, token: str | None) -> None:
        """Hard-delete the encounter and everything in it."""
        with self._conn() as c:
            self._authorize(c, encounter_id, token)
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM messages WHERE encounter_id=?", (encounter_id,))
            c.execute("DELETE FROM context_notes WHERE encounter_id=?", (encounter_id,))
            c.execute("DELETE FROM encounters WHERE encounter_id=?", (encounter_id,))
            c.execute("COMMIT")

    def purge_older_than(self, max_age_seconds: float) -> int:
        """Erase every encounter idle for longer than `max_age_seconds` (automatic data minimisation). Returns count."""
        cutoff = self.clock() - max_age_seconds
        with self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT encounter_id FROM encounters WHERE last_active < ?", (cutoff,))]
            if ids:
                c.execute("BEGIN IMMEDIATE")
                for table in ("messages", "context_notes"):
                    c.executemany(f"DELETE FROM {table} WHERE encounter_id=?", [(i,) for i in ids])
                c.executemany("DELETE FROM encounters WHERE encounter_id=?", [(i,) for i in ids])
                c.execute("COMMIT")
            return len(ids)

    # ── conversation history ──────────────────────────────────────────────────
    def add_message(self, encounter_id: str, token: str | None, role: str, content: str, meta: dict | None = None) -> int:
        import json
        if role not in ROLES:
            raise InvalidInput("role must be 'user' or 'assistant'")
        if not isinstance(content, str) or not content.strip():
            raise InvalidInput("message is empty")
        if len(content) > MAX_MESSAGE_CHARS:
            raise InvalidInput(f"message is limited to {MAX_MESSAGE_CHARS} characters")
        with self._conn() as c:
            self._authorize(c, encounter_id, token)
            now = self.clock()
            cur = c.execute("INSERT INTO messages(encounter_id, role, content, meta, created_at) VALUES (?,?,?,?,?)",
                            (encounter_id, role, content, json.dumps(meta or {}, ensure_ascii=False), now))
            c.execute("UPDATE encounters SET last_active=? WHERE encounter_id=?", (now, encounter_id))
            return cur.lastrowid

    def messages(self, encounter_id: str, token: str | None, *, limit: int = 200) -> list[dict]:
        import json
        with self._conn() as c:
            self._authorize(c, encounter_id, token)
            rows = c.execute("SELECT message_id, role, content, meta, created_at FROM messages WHERE encounter_id=? "
                             "ORDER BY message_id LIMIT ?", (encounter_id, max(1, min(int(limit), 1000)))).fetchall()
            return [{**dict(r), "meta": json.loads(r["meta"])} for r in rows]

    # ── private context notes ─────────────────────────────────────────────────
    def add_note(self, encounter_id: str, token: str | None, text: str) -> int:
        if not isinstance(text, str) or not text.strip():
            raise InvalidInput("note is empty")
        if len(text) > MAX_NOTE_CHARS:
            raise InvalidInput(f"a context note is limited to {MAX_NOTE_CHARS} characters")
        with self._conn() as c:
            self._authorize(c, encounter_id, token)
            now = self.clock()
            cur = c.execute("INSERT INTO context_notes(encounter_id, text, created_at) VALUES (?,?,?)",
                            (encounter_id, text.strip(), now))
            c.execute("UPDATE encounters SET last_active=? WHERE encounter_id=?", (now, encounter_id))
            return cur.lastrowid

    def notes(self, encounter_id: str, token: str | None) -> list[dict]:
        with self._conn() as c:
            self._authorize(c, encounter_id, token)
            return [dict(r) for r in c.execute(
                "SELECT note_id, text, created_at FROM context_notes WHERE encounter_id=? ORDER BY note_id",
                (encounter_id,))]

    def delete_note(self, encounter_id: str, token: str | None, note_id: int) -> None:
        with self._conn() as c:
            self._authorize(c, encounter_id, token)
            cur = c.execute("DELETE FROM context_notes WHERE note_id=? AND encounter_id=?", (note_id, encounter_id))
            if cur.rowcount == 0:                       # includes "note exists but belongs to another encounter"
                raise NotFound("Note not found")


# ── prompt block ──────────────────────────────────────────────────────────────
CONTEXT_WORD_BUDGET = 300
HISTORY_TURNS = 6

CONTEXT_HEADER = ("Patient context for THIS encounter only (entered by the clinician; it is NOT a source — never cite it, "
                  "never use it to calculate, adjust or choose a dose, and never state a fact about the patient that is "
                  "not written here):")


def build_context_block(store: EncounterStore, encounter_id: str, token: str | None, *,
                        max_words: int = CONTEXT_WORD_BUDGET, history_turns: int = HISTORY_TURNS) -> tuple[str, list[str]]:
    """Text for the prompt + notices for the clinician. Reads ONLY this (authorised) encounter. Notes are included whole,
    newest first, until the word budget is reached; omitted notes are announced, never silently cut. Earlier
    *questions* (not answers: their [S#] numbers belong to other prompts) give follow-up questions their context."""
    notes = store.notes(encounter_id, token)
    history = [m["content"] for m in store.messages(encounter_id, token, limit=1000) if m["role"] == "user"]
    notices: list[str] = []
    kept, words = [], 0
    for n in reversed(notes):
        w = len(n["text"].split())
        if kept and words + w > max_words:
            continue
        if not kept and w > max_words:
            continue
        kept.append(n["text"]); words += w
    omitted = len(notes) - len(kept)
    if omitted:
        notices.append(f"Note: {omitted} older patient-context note(s) did not fit the prompt budget and were not used.")
    parts = []
    if kept:
        parts.append(CONTEXT_HEADER + "\n" + "\n".join(f"- {t}" for t in reversed(kept)))
    prior = history[-(history_turns + 1):-1] if history_turns else []     # last stored user message is the current question
    if prior:
        parts.append("Earlier questions in this encounter (for follow-up context only):\n" + "\n".join(f"- {q}" for q in prior))
    return "\n\n".join(parts), notices

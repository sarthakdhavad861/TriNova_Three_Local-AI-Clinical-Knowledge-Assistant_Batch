"""
Phase 5 tests — patient-encounter isolation. Everything here is SYNTHETIC (invented labels/notes/markers).
Acceptance being tested: one encounter cannot retrieve another encounter's history or private context — through the
store API, through crafted ids/tokens, under concurrency, via the prompt, via the knowledge base and vector index.
What this does NOT prove: HTTP-layer behaviour with real FastAPI, disk-level encryption, or protection from someone
who already holds a valid token or has filesystem access.
Run from backend/:   python -B -m unittest discover -s tests -t . -v
"""
import pathlib
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from encounters.store import (
    CONTEXT_HEADER, MAX_LABEL, MAX_NOTE_CHARS, EncounterStore, InvalidInput, NotFound, build_context_block,
)
from knowledge.clinical import ground, plan_clinical
from tests.test_grounded import FICTITROL, GroundedBase


class EncBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.now = [1_000_000.0]
        self.store = EncounterStore(self.dir / "enc.db", clock=lambda: self.now[0])
        self.a, self.b = self.store.create("encounter A"), self.store.create("encounter B")
        self.store.add_message(self.a["encounter_id"], self.a["access_token"], "user", "A-QUESTION-MARKER")
        self.store.add_message(self.b["encounter_id"], self.b["access_token"], "user", "B-QUESTION-MARKER")
        self.store.add_note(self.a["encounter_id"], self.a["access_token"], "A-NOTE-MARKER synthetic context")
        self.store.add_note(self.b["encounter_id"], self.b["access_token"], "B-NOTE-MARKER synthetic context")

    def tearDown(self):
        self._tmp.cleanup()

    def ida(self): return self.a["encounter_id"]
    def idb(self): return self.b["encounter_id"]
    def ta(self): return self.a["access_token"]
    def tb(self): return self.b["access_token"]

    def raw(self, sql, *params):
        c = sqlite3.connect(self.store.path)
        try:
            return c.execute(sql, params).fetchall()
        finally:
            c.close()


class AccessControlTests(EncBase):
    def test_owner_reads_only_own_history_and_context(self):
        self.assertEqual([m["content"] for m in self.store.messages(self.ida(), self.ta())], ["A-QUESTION-MARKER"])
        self.assertEqual([n["text"] for n in self.store.notes(self.idb(), self.tb())], ["B-NOTE-MARKER synthetic context"])

    def test_every_operation_refuses_another_encounters_token_and_changes_nothing(self):
        before = (self.raw("SELECT COUNT(*) FROM messages")[0][0], self.raw("SELECT COUNT(*) FROM context_notes")[0][0],
                  self.raw("SELECT COUNT(*) FROM encounters")[0][0])
        note_b = self.store.notes(self.idb(), self.tb())[0]["note_id"]
        ops = {
            "messages": lambda: self.store.messages(self.idb(), self.ta()),
            "notes": lambda: self.store.notes(self.idb(), self.ta()),
            "metadata": lambda: self.store.metadata(self.idb(), self.ta()),
            "add_message": lambda: self.store.add_message(self.idb(), self.ta(), "user", "intruder"),
            "add_note": lambda: self.store.add_note(self.idb(), self.ta(), "intruder"),
            "delete_note": lambda: self.store.delete_note(self.idb(), self.ta(), note_b),
            "erase": lambda: self.store.erase(self.idb(), self.ta()),
        }
        for name, op in ops.items():
            with self.assertRaises(NotFound, msg=name):
                op()
        after = (self.raw("SELECT COUNT(*) FROM messages")[0][0], self.raw("SELECT COUNT(*) FROM context_notes")[0][0],
                 self.raw("SELECT COUNT(*) FROM encounters")[0][0])
        self.assertEqual(before, after)

    def test_missing_wrong_empty_and_nonstring_tokens_and_unknown_ids_are_all_refused(self):
        for token in (None, "", " ", "wrong", self.ta()[:-1], self.ta() + "x", self.ta().upper(), 123, b"x", ["x"]):
            self.assertFalse(self.store.authorize(self.idb(), token), repr(token))
        for eid in ("", "nope", "0" * 32, None, 5, self.ida().upper()):
            self.assertFalse(self.store.authorize(eid, self.ta()), repr(eid))

    def test_crafted_ids_and_tokens_cannot_bypass_authorisation(self):
        for evil in ("' OR '1'='1", "%", "*", "1; DROP TABLE messages;--", "../" + self.idb(), self.idb() + " ",
                     "\x00", "‮" + self.idb()):
            self.assertFalse(self.store.authorize(evil, self.tb()), repr(evil))
            self.assertFalse(self.store.authorize(self.idb(), evil), repr(evil))
        self.assertEqual(self.raw("SELECT COUNT(*) FROM messages")[0][0], 2)

    def test_a_note_of_another_encounter_cannot_be_deleted_through_my_own_id(self):
        note_b = self.store.notes(self.idb(), self.tb())[0]["note_id"]
        with self.assertRaises(NotFound):
            self.store.delete_note(self.ida(), self.ta(), note_b)
        self.assertEqual(len(self.store.notes(self.idb(), self.tb())), 1)

    def test_error_is_uniform_between_unknown_id_and_wrong_token(self):
        msgs = set()
        for eid, tok in ((self.idb(), "bad"), ("unknown-id", self.tb()), (self.idb(), None)):
            try:
                self.store.messages(eid, tok)
            except NotFound as e:
                msgs.add(str(e))
        self.assertEqual(len(msgs), 1)

    def test_ids_and_tokens_are_unguessable_and_token_is_stored_only_as_hash(self):
        made = [self.store.create() for _ in range(30)]
        self.assertEqual(len({m["encounter_id"] for m in made}), 30)
        self.assertEqual(len({m["access_token"] for m in made}), 30)
        self.assertTrue(all(len(m["encounter_id"]) == 32 and len(m["access_token"]) >= 40 for m in made))
        raw_bytes = self.store.path.read_bytes()
        self.assertNotIn(self.ta().encode(), raw_bytes)
        self.assertNotIn(self.tb().encode(), raw_bytes)
        self.assertNotIn("token", [c[1] for c in self.raw("PRAGMA table_info(encounters)")])

    def test_there_is_no_listing_api(self):
        public = [n for n in dir(EncounterStore) if not n.startswith("_")]
        self.assertFalse([n for n in public if n.startswith(("list", "all", "find", "search"))], public)

    def test_input_validation(self):
        with self.assertRaises(InvalidInput): self.store.create("x" * (MAX_LABEL + 1))
        with self.assertRaises(InvalidInput): self.store.add_note(self.ida(), self.ta(), "  ")
        with self.assertRaises(InvalidInput): self.store.add_note(self.ida(), self.ta(), "x" * (MAX_NOTE_CHARS + 1))
        with self.assertRaises(InvalidInput): self.store.add_message(self.ida(), self.ta(), "system", "hi")
        with self.assertRaises(InvalidInput): self.store.add_message(self.ida(), self.ta(), "user", "")


class LifecycleTests(EncBase):
    def test_erase_removes_all_rows_invalidates_token_and_spares_others(self):
        self.store.erase(self.ida(), self.ta())
        for table in ("messages", "context_notes"):
            self.assertEqual(self.raw(f"SELECT COUNT(*) FROM {table} WHERE encounter_id=?", self.ida())[0][0], 0)
        self.assertEqual(self.raw("SELECT COUNT(*) FROM encounters WHERE encounter_id=?", self.ida())[0][0], 0)
        self.assertFalse(self.store.authorize(self.ida(), self.ta()))
        self.assertEqual(len(self.store.messages(self.idb(), self.tb())), 1)
        self.assertEqual(len(self.store.notes(self.idb(), self.tb())), 1)

    def test_erased_text_is_not_recoverable_with_the_same_id_by_a_new_encounter(self):
        self.store.erase(self.ida(), self.ta())
        c = self.store.create("new")
        self.assertEqual(self.store.messages(c["encounter_id"], c["access_token"]), [])

    def test_idle_encounters_expire_and_active_ones_survive(self):
        self.now[0] += 3600 * 30
        self.store.add_message(self.idb(), self.tb(), "user", "still active")        # touches last_active
        self.assertEqual(self.store.purge_older_than(3600 * 24), 1)
        self.assertFalse(self.store.authorize(self.ida(), self.ta()))
        self.assertTrue(self.store.authorize(self.idb(), self.tb()))
        self.assertEqual(self.raw("SELECT COUNT(*) FROM messages WHERE encounter_id=?", self.ida())[0][0], 0)
        self.assertEqual(self.raw("SELECT COUNT(*) FROM context_notes WHERE encounter_id=?", self.ida())[0][0], 0)

    def test_metadata_counts_only_own_rows(self):
        self.store.add_note(self.ida(), self.ta(), "second A note")
        m = self.store.metadata(self.ida(), self.ta())
        self.assertEqual((m["messages"], m["context_notes"], m["label"]), (1, 2, "encounter A"))
        self.assertNotIn("token_hash", m)


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_encounters_never_see_each_others_data(self):
        with tempfile.TemporaryDirectory() as d:
            store = EncounterStore(pathlib.Path(d) / "enc.db")
            n_enc, n_msg = 8, 25
            enc = [store.create(f"e{i}") for i in range(n_enc)]
            barrier, errors = threading.Barrier(n_enc), []

            def work(i):
                e = enc[i]
                eid, tok = e["encounter_id"], e["access_token"]
                barrier.wait()
                try:
                    for k in range(n_msg):
                        store.add_message(eid, tok, "user", f"MARK-{i}-msg-{k}")
                        store.add_note(eid, tok, f"MARK-{i}-note-{k}")
                        if k % 5 == 0:                                  # read back while others are writing
                            texts = [m["content"] for m in store.messages(eid, tok)] + [n["text"] for n in store.notes(eid, tok)]
                            bad = [t for t in texts if not t.startswith(f"MARK-{i}-")]
                            if bad:
                                errors.append((i, bad[:2]))
                            other = enc[(i + 1) % n_enc]
                            try:
                                store.messages(other["encounter_id"], tok)
                                errors.append((i, "accessed neighbour"))
                            except NotFound:
                                pass
                except Exception as ex:                                  # noqa: BLE001
                    errors.append((i, repr(ex)))

            with ThreadPoolExecutor(n_enc) as pool:
                list(pool.map(work, range(n_enc)))
            self.assertEqual(errors, [])
            for i, e in enumerate(enc):
                msgs = store.messages(e["encounter_id"], e["access_token"])
                self.assertEqual(len(msgs), n_msg)
                self.assertTrue(all(m["content"].startswith(f"MARK-{i}-") for m in msgs))
                self.assertEqual(len(store.notes(e["encounter_id"], e["access_token"])), n_msg)


class PromptIsolationTests(EncBase):
    def test_context_block_contains_only_the_authorised_encounters_data(self):
        self.store.add_message(self.ida(), self.ta(), "user", "A-CURRENT-QUESTION")
        block, notices = build_context_block(self.store, self.ida(), self.ta())
        self.assertIn("A-NOTE-MARKER", block)
        self.assertIn("A-QUESTION-MARKER", block)          # earlier question of A
        self.assertNotIn("A-CURRENT-QUESTION", block)      # the current question is asked separately
        self.assertNotIn("B-NOTE-MARKER", block)
        self.assertNotIn("B-QUESTION-MARKER", block)
        self.assertIn(CONTEXT_HEADER, block)
        self.assertEqual(notices, [])

    def test_context_block_refuses_wrong_token(self):
        with self.assertRaises(NotFound):
            build_context_block(self.store, self.idb(), self.ta())

    def test_history_has_questions_only_never_assistant_answers(self):
        self.store.add_message(self.ida(), self.ta(), "assistant", "A-ANSWER-WITH [S1] CITATION")
        self.store.add_message(self.ida(), self.ta(), "user", "current")
        block, _ = build_context_block(self.store, self.ida(), self.ta())
        self.assertNotIn("A-ANSWER", block)
        self.assertNotIn("[S1]", block)

    def test_notes_over_budget_are_announced_not_silently_dropped(self):
        for i in range(5):
            self.store.add_note(self.ida(), self.ta(), f"note{i} " + "word " * 60)
        block, notices = build_context_block(self.store, self.ida(), self.ta(), max_words=150)
        self.assertTrue(notices and "did not fit" in notices[0])
        self.assertIn("note4", block)                      # newest kept first
        self.assertNotIn("note0", block)

    def test_history_is_limited_to_recent_questions(self):
        for i in range(10):
            self.store.add_message(self.ida(), self.ta(), "user", f"Q{i}")
        block, _ = build_context_block(self.store, self.ida(), self.ta(), history_turns=3)
        self.assertIn("Q8", block); self.assertIn("Q7", block); self.assertIn("Q6", block)
        self.assertNotIn("Q5", block)
        self.assertNotIn("Q9", block)                      # the latest stored question is the current one


class KnowledgeSeparationTests(GroundedBase):
    def setUp(self):
        super().setUp()
        self.enc_store = EncounterStore(self.dir / "encounters.db")
        self.e = self.enc_store.create("sep")

    def test_databases_are_separate_files_with_disjoint_schemas(self):
        self.assertNotEqual(self.store.path, self.enc_store.path)
        def tables(p):
            c = sqlite3.connect(p)
            try:
                return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                c.close()
        kb, enc = tables(self.store.path), tables(self.enc_store.path)
        self.assertFalse({"encounters", "messages", "context_notes"} & kb)
        self.assertFalse({"sources", "chunks", "records", "source_versions"} & enc)

    def test_patient_text_never_reaches_the_knowledge_base_or_vector_index(self):
        self.enc_store.add_note(self.e["encounter_id"], self.e["access_token"], "PRIVATE-NOTE-ZZ9 weighs 70 kg")
        self.enc_store.add_message(self.e["encounter_id"], self.e["access_token"], "user", "PRIVATE-QUESTION-ZZ9 Fictitrol")
        self.load(("fict.md", FICTITROL))
        self.retriever.retrieve("PRIVATE-QUESTION-ZZ9 Fictitrol maximum dose")
        kb = pathlib.Path(self.store.path)
        blob = b"".join(f.read_bytes() for f in kb.parent.glob(kb.name + "*")) + repr(self.index.items).encode()
        self.assertIn(b"Fictitrol", blob)                      # sanity: the scan does cover the stored knowledge
        self.assertNotIn(b"ZZ9", blob)

    def test_private_context_reaches_only_that_encounters_prompt_and_is_not_a_source(self):
        self.load(("fict.md", FICTITROL))
        other = self.enc_store.create("other")
        self.enc_store.add_note(self.e["encounter_id"], self.e["access_token"], "SYNTHETIC-PATIENT-X on dialysis")
        self.enc_store.add_note(other["encounter_id"], other["access_token"], "SYNTHETIC-PATIENT-Y pregnant")
        q = "What is the maximum dose of Fictitrol?"
        self.enc_store.add_message(self.e["encounter_id"], self.e["access_token"], "user", q)
        block, _ = build_context_block(self.enc_store, self.e["encounter_id"], self.e["access_token"])
        plan = ground(q, plan_clinical(self.store, q), self.retriever.retrieve(q), context_block=block)
        self.assertIn("SYNTHETIC-PATIENT-X", plan.prompt)
        self.assertNotIn("SYNTHETIC-PATIENT-Y", plan.prompt)
        self.assertLess(plan.prompt.index("Excerpts:"), plan.prompt.index("SYNTHETIC-PATIENT-X"))
        self.assertLess(plan.prompt.index("SYNTHETIC-PATIENT-X"), plan.prompt.index("Question:"))
        self.assertNotIn("SYNTHETIC-PATIENT-X", " ".join(e.text for e in plan.used))   # never cited as a source
        stateless = ground(q, plan_clinical(self.store, q), self.retriever.retrieve(q))
        self.assertNotIn("SYNTHETIC-PATIENT", stateless.prompt)                       # /query without an encounter

    def test_prompt_without_context_is_unchanged(self):
        self.load(("fict.md", FICTITROL))
        q = "maximum dose of Fictitrol"
        self.assertEqual(ground(q, plan_clinical(self.store, q), self.retriever.retrieve(q)).prompt,
                         ground(q, plan_clinical(self.store, q), self.retriever.retrieve(q), context_block="  ").prompt)


if __name__ == "__main__":
    unittest.main()

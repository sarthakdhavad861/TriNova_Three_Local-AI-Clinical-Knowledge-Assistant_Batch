"""
Phase 2 tests — medical knowledge ingestion. Offline: fake embedder, in-memory vector index,
fake PDF reader. Run from backend/:   python -B -m unittest discover -s tests -t . -v
NOT covered here (needs installed packages / services): ChromaIndex, PyMuPDF reader, Ollama embeddings, HTTP routes.
"""
import hashlib
import json
import pathlib
import tempfile
import threading
import unittest
import uuid

from knowledge.ingest import IngestionService, make_source_id, safe_basename
from knowledge.parsers import IngestionError
from knowledge.store import KnowledgeStore

BACKEND = pathlib.Path(__file__).resolve().parent.parent


class FakeEmbedder:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def __call__(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("ollama down")
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]


class MemoryIndex:
    def __init__(self, fail_upsert=False, fail_delete=False):
        self.items, self.fail_upsert, self.fail_delete = {}, fail_upsert, fail_delete

    def upsert(self, ids, embeddings, documents, metadatas):
        for i, e, d, m in zip(ids, embeddings, documents, metadatas):
            self.items[i] = (e, d, m)
        if self.fail_upsert:
            raise RuntimeError("chroma unavailable")     # raised AFTER a partial write, on purpose

    def delete(self, ids):
        if self.fail_delete:
            raise RuntimeError("delete failed")
        for i in ids:
            self.items.pop(i, None)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.store = KnowledgeStore(self.dir / "k.db")
        self.index = MemoryIndex()
        self.embedder = FakeEmbedder()
        self.pdf_pages = [(1, "Intro\n\nParacetamol overview."), (2, "Dosing table\n\nSee label.")]
        self.svc = self.make_service()

    def tearDown(self):
        self._tmp.cleanup()

    def make_service(self, **kw):
        kw.setdefault("pdf_reader", lambda path: self.pdf_pages)
        return IngestionService(self.store, kw.pop("index", self.index), kw.pop("embedder", self.embedder),
                                embed_model="fake-embed", **kw)

    def write(self, name, content, binary=False):
        p = self.dir / f"upload-{uuid.uuid4().hex}"          # unique per call: safe for concurrent tests
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return p

    def ingest(self, name, content, svc=None, **kw):
        return (svc or self.svc).ingest_file(self.write(name, content), name, **kw)

    def assertNothingStored(self, index=None):
        t = self.store.totals()
        self.assertEqual((t["sources"], t["chunks"], t["records"]), (0, 0, 0))
        self.assertEqual(self.store.list_sources(), [])
        self.assertEqual(len((index or self.index).items), 0)


class FormatTests(Base):
    def test_text_ingest_has_traceable_provenance(self):
        body = "First paragraph about aspirin.\n\nSecond paragraph about warfarin.\n\nThird."
        r = self.ingest("Drug Notes.txt", body, license="CC0", origin="unit-test")
        self.assertEqual(r.status, "success", r.message)
        self.assertEqual(r.source_id, "drug-notes-txt")
        src = self.store.get_source("drug-notes-txt")
        self.assertEqual((src["license"], src["origin"], src["display_name"]), ("CC0", "unit-test", "Drug Notes.txt"))
        v = src["versions"][0]
        self.assertEqual(v["sha256"], hashlib.sha256(body.encode()).hexdigest())
        self.assertEqual((v["version"], v["status"], v["embed_model"]), (1, "active", "fake-embed"))
        chunks = self.store.list_chunks("drug-notes-txt")
        self.assertEqual(sorted(self.index.items), sorted(c["chunk_id"] for c in chunks))
        meta = self.index.items[chunks[0]["chunk_id"]][2]
        self.assertEqual((meta["source_id"], meta["version"], meta["filename"]), ("drug-notes-txt", 1, "Drug Notes.txt"))
        self.assertEqual(r.event_id, self.store.list_events()[0]["event_id"])

    def test_markdown_sections_are_kept(self):
        r = self.ingest("guide.md", "# Aspirin\nTake with food.\n\n## Warnings\nAvoid in children with viral illness.\n")
        self.assertEqual(r.status, "success", r.message)
        self.assertEqual([c["section"] for c in self.store.list_chunks("guide-md")], ["Aspirin", "Warnings"])

    def test_pdf_pages_and_display_name_without_upload_uuid(self):
        path = self.write("3f2a9c1e-0000-4000-8000-123456789abc.pdf", b"%PDF-1.4 fake")
        r = self.svc.ingest_file(path, "Drug Handbook 2024.pdf")
        self.assertEqual(r.status, "success", r.message)
        self.assertEqual(r.source_id, "drug-handbook-2024-pdf")
        chunks = self.store.list_chunks(r.source_id)
        self.assertEqual([c["page"] for c in chunks], [1, 2])
        meta = self.index.items[chunks[1]["chunk_id"]][2]
        self.assertEqual((meta["page_number"], meta["filename"], meta["source_type"]), (2, "Drug Handbook 2024.pdf", "pdf"))

    def test_csv_records_preserve_units_and_quoting(self):
        csv_text = ('\ufeffName,Dose,Contraindications\n'
                    'Metformin,"500 mg, twice daily",eGFR < 30 mL/min/1.73m2\n'
                    'Paracetamol,1 g q6h (max 4 g/24 h),Severe hepatic impairment\n')
        r = self.ingest("meds.csv", csv_text)
        self.assertEqual((r.status, r.record_count, r.chunk_count), ("success", 2, 0), r.message)
        rec = self.store.list_records(name="metformin")[0]            # case-insensitive exact name
        self.assertEqual(rec["category"], "medicine")
        self.assertEqual(rec["fields"]["Dose"], "500 mg, twice daily")
        self.assertEqual(rec["fields"]["Contraindications"], "eGFR < 30 mL/min/1.73m2")
        self.assertEqual((rec["source_id"], rec["version"], rec["row_number"]), ("meds-csv", 1, 2))
        self.assertEqual(len(self.index.items), 0)

    def test_csv_semicolon_short_rows_and_empty_names_become_warnings(self):
        r = self.ingest("eq.csv", "Device;Manufacturer;Range\nPulse oximeter;Acme;70-100 %\nBP cuff;Acme\n;Nameless;x\n")
        self.assertEqual(r.status, "success", r.message)
        self.assertEqual(self.store.list_records(category="equipment")[0]["name"], "Pulse oximeter")
        self.assertEqual(len(r.warnings), 2)
        self.assertEqual(self.store.get_source("eq-csv")["versions"][0]["warnings"], r.warnings)
        self.assertEqual(self.store.list_records(name="BP cuff")[0]["fields"]["Range"], "")

    def test_json_list_and_wrapped_list(self):
        a = self.ingest("a.json", json.dumps([{"drug_name": "Ibuprofen", "dose": "400 mg", "tags": ["NSAID"]}]))
        b = self.ingest("b.json", json.dumps({"equipment": [{"device": "ECG", "channels": 12}]}))
        self.assertEqual((a.status, b.status), ("success", "success"), (a.message, b.message))
        self.assertEqual(self.store.list_records(name="ibuprofen")[0]["fields"]["tags"], ["NSAID"])
        self.assertEqual(self.store.list_records(name="ecg")[0]["fields"]["channels"], 12)
        self.assertEqual(self.store.list_records(name="ecg")[0]["category"], "equipment")

    def test_explicit_category_overrides_inference_and_invalid_is_rejected(self):
        r = self.ingest("x.csv", "name,dose\nFoo,1 mg\n", category="symptom")
        self.assertEqual(self.store.list_records()[0]["category"], "symptom", r.message)
        bad = self.ingest("y.csv", "name,dose\nBar,1 mg\n", category="nonsense")
        self.assertEqual((bad.status, bad.error_code), ("error", "invalid_category"))

    def test_long_paragraph_is_split_without_losing_a_word_or_warning(self):
        filler = " ".join(f"Sentence number {i} describes routine dosing." for i in range(60))
        tail = "CONTRAINDICATED if eGFR < 30 mL/min/1.73m2."
        r = self.ingest("long.txt", filler + " " + tail, svc=self.make_service(max_words=40))
        self.assertEqual(r.status, "success", r.message)
        chunks = self.store.list_chunks("long-txt", limit=500)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c["text"].split()) <= 40 for c in chunks))
        self.assertIn(tail, " ".join(c["text"] for c in chunks))
        words = " ".join(c["text"] for c in chunks).split()
        self.assertEqual(words, (filler + " " + tail).split())


class DuplicateAndVersionTests(Base):
    def test_identical_reupload_is_a_noop(self):
        self.ingest("n.txt", "Alpha.\n\nBeta.")
        before = (self.store.totals(), dict(self.index.items), self.embedder.calls)
        r = self.ingest("n.txt", "Alpha.\n\nBeta.")
        self.assertEqual(r.status, "unchanged")
        self.assertEqual((self.store.totals(), dict(self.index.items), self.embedder.calls), before)
        self.assertEqual([e["status"] for e in self.store.list_events()], ["unchanged", "success"])

    def test_changed_file_supersedes_previous_version(self):
        r1 = self.ingest("n.txt", "Old dose: 5 mg.")
        old_ids = [c["chunk_id"] for c in self.store.list_chunks("n-txt")]
        r2 = self.ingest("n.txt", "New dose: 10 mg.")
        self.assertEqual((r1.version, r2.version, r2.status), (1, 2, "success"))
        self.assertIn("superseded", r2.message)
        self.assertEqual([v["status"] for v in self.store.get_source("n-txt")["versions"]], ["superseded", "active"])
        self.assertEqual(self.store.get_active_chunks(old_ids), {})
        self.assertTrue(set(old_ids).isdisjoint(self.index.items))
        self.assertEqual([c["text"] for c in self.store.list_chunks("n-txt")], ["New dose: 10 mg."])
        self.assertEqual(self.store.list_chunks("n-txt", version=1)[0]["text"], "Old dose: 5 mg.")   # history kept

    def test_same_content_under_another_name_is_rejected(self):
        self.ingest("n.txt", "Same content.")
        r = self.ingest("copy-of-n.txt", "Same content.")
        self.assertEqual((r.status, r.error_code, r.source_id), ("duplicate", "duplicate_content", "n-txt"))
        self.assertEqual([s["source_id"] for s in self.store.list_sources()], ["n-txt"])

    def test_same_stem_different_formats_do_not_collide(self):
        self.assertNotEqual(make_source_id("list.csv", "csv"), make_source_id("list.json", "json"))

    def test_filename_cannot_escape_or_inject(self):
        self.assertEqual(safe_basename("../../etc/passwd.txt"), "passwd.txt")
        self.assertEqual(safe_basename("C:\\evil\\dir\\doc.txt"), "doc.txt")
        r = self.ingest("../../x/Report.txt", "Hello.")
        self.assertEqual((r.status, r.source_id), ("success", "report-txt"))


class RejectionTests(Base):
    CASES = [
        ("empty.txt", b"", "empty"),
        ("ws.txt", b"  \n \n", "empty"),
        ("prog.exe", b"MZ", "unsupported_type"),
        ("bin.txt", b"\x00\x01abc", "binary_content"),
        ("latin1.txt", b"caf\xe9", "not_utf8"),
        ("fake.pdf", b"hello world", "malformed_pdf"),
        ("bad.json", b"{oops", "malformed_json"),
        ("obj.json", b'{"a": 1}', "unsupported_json"),
        ("scalar.json", b"[1, 2]", "unsupported_json"),
        ("noname.json", b'[{"x": 1}]', "no_records"),
        ("ragged.csv", b"name,dose\nA,1,2\n", "malformed_csv"),
        ("noname.csv", b"dose\n5 mg\n", "no_name_column"),
        ("hdr.csv", b"name,dose\n", "no_records"),
        ("dup.csv", b"name,Name\nA,B\n", "malformed_csv"),
    ]

    def test_each_malformed_input_is_rejected_cleanly_and_logged(self):
        for name, content, code in self.CASES:
            with self.subTest(file=name):
                r = self.ingest(name, content)
                self.assertEqual((r.status, r.error_code), ("error", code), r.message)
                ev = self.store.get_event(r.event_id)
                self.assertEqual((ev["status"], ev["error_code"], ev["filename"]), ("error", code, name))
                self.assertTrue(ev["message"])
        self.assertNothingStored()
        self.assertEqual(len(self.store.list_events(status="error")), len(self.CASES))

    def test_oversized_file_is_rejected(self):
        r = self.ingest("big.txt", "x" * 100, svc=self.make_service(max_bytes=50))
        self.assertEqual((r.status, r.error_code), ("error", "too_large"))
        self.assertNothingStored()

    def test_missing_file_is_reported_not_raised(self):
        r = self.svc.ingest_file(self.dir / "nope.txt", "nope.txt")
        self.assertEqual((r.status, r.error_code), ("error", "unreadable"))

    def test_scanned_pdf_without_text_and_pdf_reader_errors(self):
        self.pdf_pages = [(1, "   "), (2, "")]
        r = self.ingest("scan.pdf", b"%PDF-1.4")
        self.assertEqual(r.error_code, "no_text")

        def boom(path):
            raise IngestionError("encrypted_pdf", "PDF is password-protected.")
        r = self.ingest("locked.pdf", b"%PDF-1.4 x", svc=self.make_service(pdf_reader=boom))
        self.assertEqual(r.error_code, "encrypted_pdf")
        self.assertNothingStored()

    def test_rejected_new_version_keeps_the_existing_one(self):
        self.ingest("n.csv", "name,dose\nA,1 mg\n")
        r = self.ingest("n.csv", "name,dose\nA,1,2\n")                # malformed update
        self.assertEqual(r.status, "error")
        self.assertEqual(self.store.list_sources()[0]["version"], 1)
        self.assertEqual(self.store.list_records(name="A")[0]["fields"]["dose"], "1 mg")


class AtomicityTests(Base):
    def test_embedder_failure_leaves_nothing(self):
        r = self.ingest("n.txt", "Some text.", svc=self.make_service(embedder=FakeEmbedder(fail=True)))
        self.assertEqual((r.status, r.error_code), ("error", "internal_error"))
        self.assertNothingStored()
        self.assertEqual(self.store.get_event(r.event_id)["status"], "error")

    def test_embedder_wrong_vector_count_is_rejected(self):
        svc = self.make_service(embedder=lambda texts: [[0.1]], max_words=1)    # 2 chunks, embedder returns 1 vector
        r = self.ingest("n.txt", "Alpha.\n\nBeta.", svc=svc)
        self.assertEqual((r.status, r.error_code), ("error", "embedding_failed"))
        self.assertNothingStored()

    def test_vector_write_failure_rolls_back_and_cleans_partial_vectors(self):
        bad = MemoryIndex(fail_upsert=True)
        r = self.ingest("n.txt", "A.\n\nB.", svc=self.make_service(index=bad))
        self.assertEqual(r.status, "error")
        self.assertNothingStored(bad)
        ok = self.ingest("n.txt", "A.\n\nB.")                        # a retry works from a clean state
        self.assertEqual((ok.status, ok.version), ("success", 1))

    def test_failed_update_leaves_previous_version_active_and_searchable(self):
        self.ingest("n.txt", "Version one.")
        ids_v1 = set(self.index.items)
        bad = MemoryIndex(fail_upsert=True)
        bad.items = self.index.items                                   # same underlying vector store
        r = self.ingest("n.txt", "Version two.", svc=self.make_service(index=bad))
        self.assertEqual(r.status, "error")
        self.assertEqual(self.store.list_sources()[0]["version"], 1)
        self.assertEqual(set(self.index.items), ids_v1)
        self.assertEqual(set(self.store.get_active_chunks(list(ids_v1))), ids_v1)

    def test_failure_removing_old_vectors_is_a_warning_and_stale_ids_are_filtered(self):
        self.ingest("n.txt", "Version one.")
        old = set(self.index.items)
        flaky = MemoryIndex(fail_delete=True)
        flaky.items = self.index.items
        r = self.ingest("n.txt", "Version two.", svc=self.make_service(index=flaky))
        self.assertEqual(r.status, "success")
        self.assertTrue(any("could not be removed" in w for w in r.warnings))
        self.assertTrue(old <= set(self.index.items))                  # stale vectors still present…
        self.assertEqual(self.store.get_active_chunks(list(self.index.items)).keys() & old, set())   # …but inactive


class ConcurrencyTests(Base):
    def run_threads(self, jobs):
        out, errs = [], []

        def worker(job):
            try:
                out.append(job())
            except BaseException as e:  # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=worker, args=(j,)) for j in jobs]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        return out

    def test_distinct_files_ingested_concurrently_have_no_id_collisions(self):
        jobs = [lambda i=i: self.ingest(f"doc{i}.txt", f"Document {i}.\n\nMore text for {i}.") for i in range(8)]
        results = self.run_threads(jobs)
        self.assertEqual([r.status for r in results], ["success"] * 8)
        ids = [c["chunk_id"] for s in self.store.list_sources() for c in self.store.list_chunks(s["source_id"])]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(self.index.items))
        self.assertEqual(self.store.totals()["chunks"], len(ids))

    def test_concurrent_updates_of_one_source_end_with_exactly_one_active_version(self):
        jobs = [lambda i=i: self.ingest("shared.txt", f"Revision {i}.") for i in range(6)]
        results = self.run_threads(jobs)
        self.assertEqual(sorted(r.version for r in results), [1, 2, 3, 4, 5, 6])
        versions = self.store.get_source("shared-txt")["versions"]
        self.assertEqual([v["status"] for v in versions].count("active"), 1)
        active = [c["chunk_id"] for c in self.store.list_chunks("shared-txt")]
        self.assertEqual(set(self.index.items), set(active))

    def test_concurrent_identical_uploads_create_one_version(self):
        jobs = [lambda: self.ingest("same.txt", "Identical.") for _ in range(5)]
        results = self.run_threads(jobs)
        self.assertEqual(sorted(r.status for r in results), ["success"] + ["unchanged"] * 4)
        self.assertEqual(len(self.store.get_source("same-txt")["versions"]), 1)
        self.assertEqual(len(self.index.items), 1)


class InspectionTests(Base):
    def test_listing_filters_and_pagination(self):
        self.ingest("a.csv", "name,dose\nAlpha,1 mg\nBeta,2 mg\n")
        self.ingest("b.txt", "\n\n".join(f"Para {i}." for i in range(5)), svc=self.make_service(max_words=2))
        self.assertEqual(self.store.totals(), {"sources": 2, "chunks": 5, "records": 2})
        self.assertEqual([r["name"] for r in self.store.list_records(source_id="a-csv")], ["Alpha", "Beta"])
        self.assertEqual(self.store.list_records(name="gamma"), [])
        self.assertEqual(len(self.store.list_chunks("b-txt", limit=2, offset=1)), 2)
        self.assertIsNone(self.store.get_source("missing"))
        listed = {s["source_id"]: s for s in self.store.list_sources()}
        self.assertEqual(listed["a-csv"]["record_count"], 2)
        self.assertEqual(listed["b-txt"]["chunk_count"], 5)

    def test_events_record_every_outcome(self):
        self.ingest("a.txt", "Hi.")
        self.ingest("a.txt", "Hi.")
        self.ingest("b.txt", "Hi.")
        self.ingest("c.exe", "x")
        self.assertEqual([e["status"] for e in self.store.list_events()], ["error", "duplicate", "unchanged", "success"])


class RepositoryHygieneTests(unittest.TestCase):
    def test_video_and_whisper_path_is_gone(self):
        self.assertFalse((BACKEND / "processors" / "ingest.py").exists())
        self.assertFalse((BACKEND / "processors" / "pdf_ingest.py").exists())
        offenders = []
        for p in BACKEND.rglob("*.py"):
            if "tests" in p.parts:
                continue
            text = p.read_text(encoding="utf-8").lower()
            offenders += [f"{p.relative_to(BACKEND)}: {w}" for w in ("whisper", "ffmpeg", "upload-video") if w in text]
        self.assertEqual(offenders, [])
        self.assertNotIn("whisper", (BACKEND / "requirements.txt").read_text().lower())


if __name__ == "__main__":
    unittest.main()

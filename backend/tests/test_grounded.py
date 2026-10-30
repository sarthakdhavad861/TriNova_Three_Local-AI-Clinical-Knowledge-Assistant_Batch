"""
Phase 3 tests — hybrid retrieval, grounded prompt, verification, abstention, conflicts, LLM payload, eval harness.
All reference text below is SYNTHETIC (invented drugs/devices) — never real medical content.
Offline: toy bag-of-words embedder, in-memory vector index, injected "LLM". Dense relevance here is a toy channel;
real embedding quality (bge-m3) and threshold calibration are NOT tested here (see knowledge.eval).
Run from backend/:   python -B -m unittest discover -s tests -t . -v
"""
import asyncio
import hashlib
import math
import pathlib
import re
import socket
import sys
import types
import unittest
from unittest import mock

from knowledge.answer import (
    LLM_ABSTAIN, NO_EVIDENCE_MESSAGE, GroundedAnswerer, detect_discrepancies, prepare_grounding, quantities,
    verification_footer, verify_answer,
)
from knowledge.eval import evaluate
from knowledge.retrieval import STOPWORDS, Evidence, Retriever, query_terms, stem, tokens
from knowledge.store import KnowledgeStore
from tests.test_knowledge import Base, MemoryIndex

BACKEND = pathlib.Path(__file__).resolve().parent.parent

FICTITROL = ("# Fictitrol (SYNTHETIC TEST DATA)\n"
             "Fictitrol 25 mg tablets are indicated for synthetic hyperzorbia. The maximum dose is 100 mg per day.\n\n"
             "## Contraindications\nFictitrol is CONTRAINDICATED if eGFR < 30 mL/min/1.73m2. "
             "Do not use in the synthetic third trimester.\n")
FICT_ALT = "Fictitrol alternative leaflet (SYNTHETIC). The maximum dose of Fictitrol is 50 mg per day for adults.\n"
FICT_SAME = "Fictitrol second leaflet (SYNTHETIC). The maximum dose of Fictitrol is 100 mg per day for adults.\n"
ZORBEX = "# Zorbex (SYNTHETIC TEST DATA)\nZorbex 5 mg/kg is given for synthetic quibbleosis. Monitor serum zorb levels every 12 hours.\n"
EQUIP = "# Examplometer (SYNTHETIC)\nThe Examplometer measures synthetic pressure from 0 to 300 mmHg. Calibrate every 12 months.\n"


class BowEmbedder:
    """Toy dense channel: hashed bag-of-words, L2-normalised."""
    DIM = 128

    def one(self, text):
        v = [0.0] * self.DIM
        for tok in tokens(text) - STOPWORDS:
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def __call__(self, texts):
        return [self.one(t) for t in texts]


class QueryableIndex(MemoryIndex):
    def query(self, embedding, n):
        sims = [(cid, sum(a * b for a, b in zip(embedding, vec))) for cid, (vec, _d, _m) in self.items.items()]
        return sorted(sims, key=lambda x: -x[1])[:n]


class GroundedBase(Base):
    def setUp(self):
        super().setUp()
        self.index, self.embedder = QueryableIndex(), BowEmbedder()
        self.svc = self.make_service()
        self.retriever = self.make_retriever()

    def make_retriever(self, **kw):
        kw.setdefault("min_dense", 0.3)
        return Retriever(self.store, self.index.query, self.embedder.one, top_k=5, **kw)

    def load(self, *docs, **kw):
        for name, text in docs:
            r = self.ingest(name, text, svc=kw.get("svc"), **{k: v for k, v in kw.items() if k != "svc"})
            self.assertEqual(r.status, "success", r.message)


def ref_for(prompt, needle):
    for m in re.finditer(r"\[(S\d+)\] Source:(.*?)(?=\n\n\[S\d+\] Source:|\n\nQuestion:)", prompt, re.S):
        if needle in m.group(2):
            return m.group(1)
    raise AssertionError(f"{needle!r} not in any excerpt")


class RetrievalTests(GroundedBase):
    def test_finds_the_relevant_chunk_with_full_provenance(self):
        self.load(("fictitrol.md", FICTITROL), ("zorbex.md", ZORBEX), ("examplometer.md", EQUIP))
        res = self.retriever.retrieve("What are the contraindications of Fictitrol with low eGFR?")
        self.assertTrue(res.sufficient)
        top = res.evidence[0]
        self.assertIn("eGFR < 30 mL/min/1.73m2", top.text)
        self.assertEqual((top.display_name, top.source_id, top.section, top.version),
                         ("fictitrol.md", "fictitrol-md", "Contraindications", 1))
        self.assertNotIn("zorbex-md", {e.source_id for e in res.evidence})

    def test_exact_term_is_found_by_keyword_search_when_embeddings_are_down(self):
        self.load(("fictitrol.md", FICTITROL), ("examplometer.md", EQUIP))

        def broken(_q):
            raise ConnectionError("ollama down")
        res = Retriever(self.store, self.index.query, broken, top_k=5).retrieve("Examplometer calibration")
        self.assertEqual(res.evidence[0].source_id, "examplometer-md")
        self.assertTrue(any("keyword search only" in n for n in res.notes))

    def test_dense_only_degradation_without_fts_is_reported(self):
        self.load(("zorbex.md", ZORBEX))
        self.store.fts_enabled = False
        res = self.make_retriever(min_dense=0.2).retrieve("Zorbex quibbleosis monitoring")
        self.assertTrue(any("keyword index unavailable" in n for n in res.notes))
        self.assertTrue(res.evidence)

    def test_out_of_scope_query_yields_no_evidence(self):
        self.load(("fictitrol.md", FICTITROL), ("zorbex.md", ZORBEX), ("examplometer.md", EQUIP))
        res = self.retriever.retrieve("How do I repair a bicycle tire?")
        self.assertFalse(res.sufficient)
        self.assertEqual(res.evidence, [])

    def test_legacy_and_stale_vectors_are_never_returned(self):
        self.load(("fictitrol.md", FICTITROL))
        q = "synthetic third trimester use"
        self.index.items["123"] = (self.embedder.one(q), "legacy chunk from the old app", {})       # no provenance row
        flaky = QueryableIndex(fail_delete=True)
        flaky.items = self.index.items                                                              # old vectors survive update
        updated = FICTITROL.replace("Do not use in the synthetic third trimester.", "Use with caution in renal impairment.")
        self.load(("fictitrol.md", updated), svc=self.make_service(index=flaky))
        res = self.make_retriever().retrieve(q)
        self.assertNotIn("123", {e.chunk_id for e in res.evidence})
        self.assertTrue(all(e.version == 2 for e in res.evidence))
        self.assertNotIn("third trimester", " ".join(e.text for e in res.evidence))
        self.assertGreaterEqual(res.stats["stale_or_legacy_filtered"], 2)

    def test_category_filter(self):
        self.load(("examplometer.md", EQUIP), category="equipment")
        self.load(("fictitrol.md", FICTITROL), category="medicine")
        res = self.retriever.retrieve("Fictitrol egfr contraindicated", )
        self.assertIn("fictitrol-md", {e.source_id for e in res.evidence})
        res = self.make_retriever().retrieve("Fictitrol egfr contraindicated", categories={"equipment"})
        self.assertEqual(res.evidence, [])

    def test_query_syntax_cannot_break_the_keyword_search(self):
        self.load(("fictitrol.md", FICTITROL))
        for q in ['fictitrol" OR NOT ( NEAR', "a AND OR NOT", "*:^ \"\"", "1.73m2 ml/min", ""]:
            with self.subTest(q=q):
                self.make_retriever().retrieve(q)

    def test_keyword_index_is_rebuilt_if_missing(self):
        self.load(("zorbex.md", ZORBEX))
        import sqlite3
        c = sqlite3.connect(self.store.path); c.execute("DELETE FROM chunks_fts"); c.commit(); c.close()
        reopened = KnowledgeStore(self.store.path)
        self.assertEqual(reopened.search_lexical(["zorbex"]), self.store.search_lexical(["zorbex"]))
        self.assertTrue(reopened.search_lexical(["zorbex"]))

    def test_term_extraction(self):
        self.assertEqual(query_terms("What is the dose of ML/min 1.73m2?"), ["dose", "ml", "min", "73m2"])
        self.assertEqual(query_terms("Patient with eGFR < 30"), ["egfr", "30"])
        self.assertIn("73m2", tokens("eGFR < 30 mL/min/1.73m2"))
        self.assertEqual((stem("calibration"), stem("calibrate"), stem("doses"), stem("dose"), stem("30mg")),
                         ("calibr", "calibr", "dose", "dose", "30mg"))

    def test_word_forms_match_in_the_keyword_channel(self):
        self.load(("fictitrol.md", FICTITROL))
        self.store_fts = self.store.search_lexical(["contraindications"])        # chunk says "CONTRAINDICATED"
        self.assertTrue(self.store_fts)
        res = Retriever(self.store, lambda e, n: [], self.embedder.one, top_k=3).retrieve("Fictitrol contraindications egfr")
        self.assertIn("eGFR < 30", res.evidence[0].text)
        self.assertEqual(res.evidence[0].lexical_coverage, 1.0)


class GroundingTests(GroundedBase):
    def test_prompt_contains_the_full_chunk_text_regression_for_truncation(self):
        sentence = "CONTRAINDICATED if eGFR < 30 mL/min/1.73m2."
        body = " ".join(f"Routine statement {i} about synthetic dosing." for i in range(25)) + " " + sentence
        self.assertGreater(len(body), 300)                               # the old prompt cut every chunk at 300 chars
        self.load(("longdoc.txt", body))
        res = self.retriever.retrieve("synthetic dosing egfr contraindicated")
        plan = prepare_grounding("synthetic dosing egfr contraindicated", res)
        self.assertFalse(plan.insufficient)
        self.assertIn(sentence, plan.prompt)
        self.assertNotIn("web development", plan.prompt.lower())
        self.assertIn("[S1] Source: longdoc.txt", plan.prompt)

    def test_word_budget_drops_whole_chunks_and_never_cuts_one(self):
        self.load(("a.txt", "Zorbex alpha " + "filler " * 60 + "ENDA."), ("b.txt", "Zorbex beta " + "filler " * 60 + "ENDB."))
        res = self.retriever.retrieve("Zorbex")
        self.assertEqual(len(res.evidence), 2)
        plan = prepare_grounding("Zorbex", res, max_words=70)
        self.assertEqual((len(plan.used), plan.dropped), (1, 1))
        self.assertIn(plan.used[0].text, plan.prompt)
        tiny = prepare_grounding("Zorbex", res, max_words=1)             # a single over-budget chunk is still sent whole
        self.assertEqual(len(tiny.used), 1)
        self.assertIn(tiny.used[0].text, tiny.prompt)

    def test_no_evidence_means_no_llm_call_and_a_fixed_message(self):
        self.load(("zorbex.md", ZORBEX))
        calls = []
        ans = GroundedAnswerer(self.retriever, lambda p: calls.append(p) or "invented").answer("Explain bicycle tire repair")
        self.assertEqual((ans.status, ans.text, calls), ("insufficient_evidence", NO_EVIDENCE_MESSAGE, []))

    def test_cited_excerpts_resolve_to_stored_chunks(self):
        self.load(("fictitrol.md", FICTITROL), ("zorbex.md", ZORBEX))
        q = "What is the maximum dose of Fictitrol per day?"

        def llm(prompt):
            return f"The maximum dose is 100 mg per day [{ref_for(prompt, '100 mg per day')}]."
        ans = GroundedAnswerer(self.retriever, llm).answer(q)
        self.assertEqual(ans.status, "answered", ans.verification.issues())
        cited = [c for c in ans.citations if c["cited"]]
        self.assertEqual(len(cited), 1)
        stored = self.store.get_active_chunks([c["chunk_id"] for c in ans.citations])
        self.assertEqual(set(stored), {c["chunk_id"] for c in ans.citations})        # cited ⊂ retrieved ⊂ stored
        for c in ans.citations:
            self.assertEqual(c["text"], stored[c["chunk_id"]]["text"])
        self.assertEqual((cited[0]["display_name"], cited[0]["version"]), ("fictitrol.md", 1))

    def test_fabricated_dose_is_flagged_unverified(self):
        self.load(("fictitrol.md", FICTITROL))
        ans = GroundedAnswerer(self.retriever, lambda p: f"The maximum dose is 200 mg per day [{ref_for(p, '100 mg')}].") \
            .answer("maximum dose of Fictitrol per day")
        self.assertEqual(ans.status, "unverified")
        self.assertEqual([u["quantity"] for u in ans.verification.unsupported_quantities], ["200 mg/day"])
        self.assertIn("FAILED", verification_footer(ans.verification))

    def test_llm_abstention_is_accepted(self):
        self.load(("fictitrol.md", FICTITROL))
        ans = GroundedAnswerer(self.retriever, lambda p: LLM_ABSTAIN).answer("maximum dose of Fictitrol per day")
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertEqual(verification_footer(ans.verification), "")

    def test_conflicting_sources_produce_a_notice(self):
        self.load(("fictitrol.md", FICTITROL), ("fictitrol-leaflet.txt", FICT_ALT))
        res = self.retriever.retrieve("maximum dose of Fictitrol per day")
        plan = prepare_grounding("maximum dose of Fictitrol per day", res)
        notice = " ".join(plan.notices)
        self.assertIn("Possible conflict", notice)
        self.assertTrue("100" in notice and "50" in notice)

    def test_agreeing_or_single_source_produces_no_conflict_notice(self):
        self.load(("fictitrol.md", FICTITROL), ("fictitrol-leaflet.txt", FICT_SAME))
        plan = prepare_grounding("maximum dose of Fictitrol per day",
                                 self.retriever.retrieve("maximum dose of Fictitrol per day"))
        self.assertEqual(plan.notices, [])
        self.assertEqual(detect_discrepancies([]), [])

    def test_answering_makes_no_network_connection(self):
        self.load(("fictitrol.md", FICTITROL))
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network access attempted")), \
             mock.patch.object(socket, "create_connection", side_effect=AssertionError("network access attempted")):
            ans = GroundedAnswerer(self.retriever, lambda p: f"Max 100 mg per day [{ref_for(p, '100 mg')}].") \
                .answer("maximum dose of Fictitrol per day")
        self.assertEqual(ans.status, "answered")


    def test_embedding_outage_is_surfaced_as_a_notice(self):
        self.load(("zorbex.md", ZORBEX))

        def broken(_q):
            raise ConnectionError("down")
        res = Retriever(self.store, self.index.query, broken, top_k=5).retrieve("Zorbex monitoring")
        self.assertTrue(any("keyword search only" in n for n in prepare_grounding("q", res).notices))


class VerificationTests(unittest.TestCase):
    def ev(self, text, ref="S1"):
        return Evidence(chunk_id=f"x:v1:{ref}", source_id="x", display_name="x.txt", version=1, text=text, ref=ref)

    def test_quantity_extraction_and_normalisation(self):
        self.assertEqual(quantities("10-20 mg/kg"), [("10", "mg/kg"), ("20", "mg/kg")])
        self.assertEqual(quantities("0,50 µg and 5 mcg"), [("0.5", "mcg"), ("5", "mcg")])
        self.assertIn(("30", "<"), quantities("eGFR < 30 mL/min/1.73m2"))
        self.assertIn(("30", "ml/min"), quantities("eGFR < 30 mL/min/1.73m2"))
        self.assertIn(("12", "h"), quantities("every 12 hours"))
        self.assertEqual(quantities("chapter 12 and room 4"), [])

    def test_table_of_verification_outcomes(self):
        used = [self.ev("Give 10-20 mg/kg every 12 hours. Contraindicated if eGFR < 30 mL/min. Avoid in synthetic pregnancy.")]
        cases = [
            ("range endpoint supported", "Give 10 mg/kg every 12 hours [S1].", True),
            ("both endpoints", "Dose is 10-20 mg/kg [S1].", True),
            ("number in symbol comparison", "Avoid if eGFR < 30 [S1].", True),
            ("wrong threshold", "Avoid if eGFR < 45 [S1].", False),
            ("wrong unit", "Give 10 mg every 12 hours [S1].", False),
            ("wrong dose", "Give 15 mg/kg [S1].", False),
            ("invalid ref", "Give 10 mg/kg [S2].", False),
            ("valid plus fabricated citation", "Give 10 mg/kg [S1][S9].", False),
            ("no citation at all", "Give 10 mg/kg every 12 hours.", False),
            ("citation after full stop", "Give 10 mg/kg every 12 hours. [S1]", True),
            ("abstention", LLM_ABSTAIN, True),
            ("fixed no-evidence message", NO_EVIDENCE_MESSAGE, True),
        ]
        for label, text, ok in cases:
            with self.subTest(label):
                self.assertEqual(verify_answer(text, used).ok, ok, verify_answer(text, used).issues())

    def test_fabricated_citation_is_reported_by_id(self):
        v = verify_answer("Give 10 mg/kg [S1][S9].", [self.ev("Give 10 mg/kg every 12 hours.")])
        self.assertEqual((v.invalid_refs, v.cited_refs, v.ok), (["S9"], ["S1"], False))
        self.assertIn("[S9]", " ".join(v.issues()))

    def test_uncited_and_weakly_supported_sentences_are_warnings_not_failures(self):
        used = [self.ev("Zorbex is monitored every twelve hours in synthetic quibbleosis.")]
        v = verify_answer("Zorbex needs monitoring in quibbleosis [S1]. Mountains are tall and rivers flow downhill quickly.", used)
        self.assertTrue(v.ok)
        self.assertEqual(len(v.uncited_sentences), 1)
        v2 = verify_answer("Mountains are tall and rivers flow downhill quickly [S1].", used)
        self.assertEqual(len(v2.weakly_supported), 1)
        self.assertIn("ℹ", verification_footer(v2))

    def test_unsupported_number_without_citation_is_checked_against_all_excerpts(self):
        used = [self.ev("Dose 5 mg.", "S1"), self.ev("Interval 8 hours.", "S2")]
        self.assertTrue(verify_answer("Dose 5 mg every 8 hours [S1][S2].", used).ok)
        self.assertFalse(verify_answer("Dose 6 mg [S1].", used).ok)


class LlmAndHygieneTests(unittest.TestCase):
    def _fake_httpx(self, status, lines, captured):
        fake = types.ModuleType("httpx")

        class Resp:
            status_code = status

            async def aiter_lines(self):
                for ln in lines:
                    yield ln

        class Ctx:
            async def __aenter__(self): return Resp()
            async def __aexit__(self, *a): return False

        class Client:
            is_closed = False
            def __init__(self, **kw): pass
            def stream(self, method, url, json=None):
                captured.update(method=method, url=url, json=json)
                return Ctx()
        fake.AsyncClient, fake.Timeout = Client, lambda **kw: None
        fake.ConnectError = type("ConnectError", (Exception,), {})
        fake.TimeoutException = type("TimeoutException", (Exception,), {})
        fake.RemoteProtocolError = type("RemoteProtocolError", (Exception,), {})
        return fake

    def _collect(self, status, lines):
        captured = {}
        with mock.patch.dict(sys.modules, {"httpx": self._fake_httpx(status, lines, captured)}):
            sys.modules.pop("services.llm", None)
            import services.llm as llm

            async def run():
                return [t async for t in llm.stream_prompt("PROMPT", "qwen")]
            return captured, asyncio.run(run())

    def test_sampling_parameters_are_sent_in_options_and_tokens_stream(self):
        from config.settings import LLM_NUM_CTX, LLM_TEMPERATURE
        captured, tokens_ = self._collect(200, ['{"response":"Hel"}', "", "not json", '{"response":"lo"}', '{"done":true}'])
        self.assertEqual("".join(tokens_), "Hello")
        body = captured["json"]
        self.assertNotIn("temperature", body)
        self.assertEqual(body["options"]["temperature"], LLM_TEMPERATURE)
        self.assertLessEqual(LLM_TEMPERATURE, 0.2)
        self.assertEqual(body["options"]["num_ctx"], LLM_NUM_CTX)
        self.assertEqual((captured["url"], body["prompt"]), ("/api/generate", "PROMPT"))

    def test_missing_model_gives_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "ollama pull"):
            self._collect(404, [])

    def test_web_search_intent_and_cache_modules_are_gone(self):
        for rel in ("services/web_search.py", "services/intent.py", "services/retrieval.py"):
            self.assertFalse((BACKEND / rel).exists(), rel)
        offenders = [str(p.relative_to(BACKEND)) for p in BACKEND.rglob("*.py")
                     if "tests" not in p.parts and re.search(r"duckduckgo|web_search|ddgs", p.read_text(encoding="utf-8"), re.I)]
        self.assertEqual(offenders, [])
        self.assertNotIn("duckduckgo", (BACKEND / "requirements.txt").read_text().lower())


class EvalHarnessTests(GroundedBase):
    def test_recall_and_abstention_are_computed(self):
        self.load(("fictitrol.md", FICTITROL), ("zorbex.md", ZORBEX), ("examplometer.md", EQUIP))
        cases = [
            {"id": "c1", "query": "Fictitrol contraindicated egfr", "expect_sources": ["fictitrol-md"]},
            {"id": "c2", "query": "Examplometer calibration interval", "expect_text": ["calibrate every 12 months"]},
            {"id": "c3", "query": "bicycle tire repair", "expect_none": True},
            {"id": "c4", "query": "Zorbex monitoring", "expect_sources": ["wrong-source"]},          # deliberate miss
        ]
        rep = evaluate(self.retriever, cases, k=3)
        self.assertEqual({c["id"]: c["pass"] for c in rep["cases"]}, {"c1": True, "c2": True, "c3": True, "c4": False})
        self.assertAlmostEqual(rep["recall_at_k"], 2 / 3)
        self.assertEqual((rep["abstention_accuracy"], rep["in_scope"], rep["out_of_scope"]), (1.0, 3, 1))


if __name__ == "__main__":
    unittest.main()

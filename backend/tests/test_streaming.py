"""
Phase 6 tests — the event stream that the frontend consumes (api/streaming.py), offline, SYNTHETIC data.
Proves: event order and content, legacy text rendering unchanged, NDJSON well-formedness (newlines/unicode in tokens),
error and disconnect behaviour, on_final contract. Does NOT prove HTTP framing or any browser behaviour.
Run from backend/:   python -B -m unittest discover -s tests -t . -v
"""
import asyncio
import json

from api.streaming import NDJSON, answer_events, render_ndjson, render_text
from knowledge.clinical import NO_NARRATIVE, RECORD_DISCLAIMER, ground, plan_clinical
from knowledge.answer import NO_EVIDENCE_MESSAGE
from tests.test_clinical import ClinicalBase
from tests.test_grounded import FICTITROL, ref_for


def collect(agen):
    async def go():
        return [e async for e in agen]
    return asyncio.run(go())


def llm(fn, fail_after=None):
    async def gen(prompt):
        toks = fn(prompt).split(" ")
        for i, t in enumerate(toks):
            if fail_after is not None and i == fail_after:
                raise RuntimeError("model unavailable")
            yield t + (" " if i < len(toks) - 1 else "")
    return gen


class StreamBase(ClinicalBase):
    def run_stream(self, question, fn, **kw):
        cp = plan_clinical(self.store, question)
        plan = ground(question, cp, self.retriever.retrieve(question))
        finals = []
        events = collect(answer_events(cp, plan, llm(fn, kw.pop("fail_after", None)),
                                       on_final=lambda s, t, issues: finals.append((s, t, issues)), **kw))
        return cp, plan, events, finals


class EventTests(StreamBase):
    def setUp(self):
        super().setUp()
        self.load(("fict.md", FICTITROL))
        self.q = "What is the maximum dose of Fictitrol?"
        self.good = lambda p: f"The maximum dose is 100 mg per day [{ref_for(p, '100 mg per day')}]."

    def test_full_order_notices_records_tokens_final(self):
        _cp, _plan, ev, finals = self.run_stream("chest pain: " + self.q, self.good)
        types = [e["type"] for e in ev]
        self.assertEqual(types[0], "notices")
        self.assertEqual(types[1], "records")
        self.assertEqual(types[-1], "final")
        self.assertEqual(set(types[2:-1]), {"token"})
        self.assertTrue(ev[0]["items"][0].startswith("🚨"))
        self.assertEqual(ev[1]["disclaimer"], RECORD_DISCLAIMER)
        self.assertEqual(ev[1]["views"][0]["name"], "Fictitrol")
        self.assertIn("Maximum 100 mg per day", ev[1]["items"][0])
        self.assertEqual(ev[-1]["status"], "answered")
        self.assertEqual("".join(e["text"] for e in ev if e["type"] == "token"), ev[-1]["text"])
        self.assertEqual([f[:2] for f in finals], [("answered", ev[-1]["text"])])

    def test_fabricated_dose_yields_verification_event_before_final(self):
        _cp, _plan, ev, finals = self.run_stream(
            self.q, lambda p: f"The maximum dose is 999 mg per day [{ref_for(p, '100 mg per day')}].")
        types = [e["type"] for e in ev]
        self.assertEqual(types[-2:], ["verification", "final"])
        v = ev[-2]
        self.assertFalse(v["ok"])
        self.assertTrue(any("999" in i for i in v["issues"]))
        self.assertIn("Evidence check FAILED", v["text"])
        self.assertEqual(finals[0][0], "unverified")
        self.assertTrue(any("999" in i for i in finals[0][2]))

    def test_abstention_and_records_only_use_fixed_text_and_no_llm(self):
        calls = []

        async def boom(prompt):
            calls.append(prompt)
            yield "x"
        for q, status, text in (("how do I repair a violin", "insufficient_evidence", NO_EVIDENCE_MESSAGE),
                                ("Examplometer", "records_only", NO_NARRATIVE)):
            cp = plan_clinical(self.store, q)
            plan = ground(q, cp, self.retriever.retrieve(q))
            ev = collect(answer_events(cp, plan, boom))
            self.assertEqual((ev[-1]["status"], ev[-1]["text"]), (status, text), q)
        self.assertEqual(calls, [])

    def test_llm_failure_emits_error_and_no_final_and_stores_nothing(self):
        _cp, _plan, ev, finals = self.run_stream(self.q, self.good, fail_after=2)
        self.assertEqual(ev[-1], {"type": "error", "message": "model unavailable"})
        self.assertNotIn("final", [e["type"] for e in ev])
        self.assertEqual(finals, [])

    def test_disconnect_stops_generation_without_final(self):
        n = [0]

        async def gone():
            n[0] += 1
            return n[0] > 2
        _cp, _plan, ev, finals = self.run_stream(self.q, self.good, is_disconnected=gone)
        self.assertNotIn("final", [e["type"] for e in ev])
        self.assertEqual(finals, [])


class RenderingTests(StreamBase):
    def test_text_rendering_is_the_legacy_format(self):
        self.load(("fict.md", FICTITROL))
        q = "chest pain: What is the maximum dose of Fictitrol?"
        cp, plan, ev, _ = self.run_stream(q, lambda p: f"The maximum dose is 100 mg per day [{ref_for(p, '100 mg per day')}].")
        text = "".join(render_text(e) for e in ev)
        expected = ("\n".join(plan.notices) + "\n\n" + "\n\n".join(cp.cards) + "\n\n" + RECORD_DISCLAIMER + "\n\n"
                    + ev[-1]["text"])
        self.assertEqual(text, expected)
        self.assertEqual(render_text(ev[-1]), "")                  # final is bookkeeping, not output

    def test_ndjson_lines_are_valid_json_and_survive_newlines_unicode_and_quotes(self):
        tricky = 'line1\nline2 "quoted" µg ≥ 30 — 🚨   end'
        out = render_ndjson({"type": "token", "text": tricky})
        self.assertEqual(out.count("\n"), 1)
        self.assertTrue(out.endswith("\n"))
        self.assertEqual(json.loads(out)["text"], tricky)

    def test_ndjson_media_type_constant(self):
        self.assertEqual(NDJSON, "application/x-ndjson")

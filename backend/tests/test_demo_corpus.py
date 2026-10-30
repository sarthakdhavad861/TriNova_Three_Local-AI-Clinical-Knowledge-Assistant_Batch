"""
Phase 8 — the synthetic demo corpus (demo/) must behave as docs/DEMO_SCENARIOS.md says.
Offline: toy embedder + scripted "LLM". Verifies the deterministic parts of each scenario (cards, notices, statuses,
no-LLM paths, isolation) and the provenance recorded for every demo file. It cannot say how a real model will word
its answers — that part of the demo must be checked by hand (see docs/DEMO_SCENARIOS.md).
"""
import json
import pathlib
import unittest

from encounters.store import EncounterStore, build_context_block
from knowledge.clinical import ClinicalAnswerer, plan_clinical
from tests.test_grounded import GroundedBase, ref_for

DEMO = pathlib.Path(__file__).resolve().parents[2] / "demo"


class DemoBase(GroundedBase):
    def setUp(self):
        super().setUp()
        manifest = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            p = DEMO / item["file"]
            r = self.svc.ingest_file(p, p.name, category=item.get("category"), license=item["license"], origin=item["origin"])
            self.assertEqual(r.status, "success", (item["file"], r.message))

    def ask(self, q, reply=None, context=""):
        self.prompts = []

        def gen(p):
            self.prompts.append(p)
            return (reply(p) if callable(reply) else reply) if reply else "The reference states the value [S1]."
        cp = plan_clinical(self.store, q)
        from knowledge.clinical import ground
        retrieval = self.retriever.retrieve(q)
        plan = ground(q, cp, retrieval, context_block=context)
        from knowledge.clinical import without_llm
        skipped = without_llm(cp, plan)
        if skipped:
            return cp, plan, skipped[0], None
        from knowledge.answer import verify_answer
        text = gen(plan.prompt)
        v = verify_answer(text, plan.used)
        return cp, plan, ("insufficient_evidence" if v.abstained else "answered" if v.ok else "unverified"), text


class DemoCorpusTests(DemoBase):
    def test_every_demo_file_carries_licence_and_origin_and_is_synthetic(self):
        for s in self.store.list_sources():
            self.assertTrue(s.get("license") and s.get("origin"), s)
            self.assertIn("CC0", s["license"])
        for p in DEMO.rglob("*"):
            if p.is_file() and p.suffix in {".md", ".csv", ".json"} and p.name not in {"README.md", "patients.md", "manifest.json"}:
                text = p.read_text(encoding="utf-8")
                self.assertTrue("SYNTHETIC" in text.upper() or p.suffix in {".csv", ".json"}, p)

    def test_1_max_dose_shows_card_conflict_notice_and_verified_answer(self):
        q = "What is the maximum dose of Fictitrol per day?"
        cp, plan, status, _ = self.ask(q, lambda p: f"The maximum dose is 100 mg per day [{ref_for(p, '100 mg per day')}].")
        self.assertEqual(cp.workflow, "medicine")
        self.assertIn("Maximum 100 mg per day", cp.cards[0])
        self.assertTrue(any("Possible conflict" in n and "50" in n and "100" in n for n in plan.notices), plan.notices)
        self.assertEqual(status, "answered")

    def test_2_contraindication_question(self):
        q = "What is the eGFR cut-off below which Fictitrol is contraindicated?"
        cp, plan, status, _ = self.ask(q, lambda p: f"Contraindicated if eGFR < 30 mL/min/1.73m2 [{ref_for(p, 'CONTRAINDICATED')}].")
        self.assertIn("eGFR < 30 mL/min/1.73m2", cp.cards[0])
        self.assertEqual(status, "answered")

    def test_3_absent_safety_fields_are_stated_not_hidden(self):
        card = plan_clinical(self.store, "Zorbex").cards[0]
        self.assertEqual(card.count("Not stated in this record"), 2)

    def test_4_urgent_patient_specific_question_with_context(self):
        es = EncounterStore(self.dir / "enc.db")
        a = es.create("Demo patient A")
        es.add_note(a["encounter_id"], a["access_token"], "Synthetic: adult, eGFR 25 mL/min/1.73m2, on no other synthetic medication.")
        q = "My patient has chest pain. What is the maximum dose of Fictitrol per day?"
        es.add_message(a["encounter_id"], a["access_token"], "user", q)
        block, _ = build_context_block(es, a["encounter_id"], a["access_token"])
        cp, plan, status, _ = self.ask(q, "Give 75 mg per day [S1].", context=block)
        self.assertTrue(plan.notices[0].startswith("\U0001F6A8"))                       # urgent banner first
        self.assertTrue(any("individual patient" in n for n in plan.notices))
        self.assertIn("eGFR 25", self.prompts[0])
        self.assertEqual(status, "unverified")                                            # invented 75 mg is flagged

    def test_4b_long_patient_narrative_may_lose_narrative_evidence_but_keeps_safety_output(self):
        """Documented limit (PROJECT_STATUS): a long patient story dilutes keyword coverage. The card and banners must remain."""
        cp, plan, status, text = self.ask("My patient has chest pain and takes Fictitrol every morning with breakfast and tea. What dose should I give?")
        self.assertTrue(plan.notices[0].startswith("\U0001F6A8"))
        self.assertTrue(cp.cards and "Maximum 100 mg per day" in cp.cards[0])
        self.assertIn(status, {"records_only", "answered", "unverified"})

    def test_5_equipment_calibration(self):
        q = "How often should the Examplometer be calibrated?"
        cp, plan, status, _ = self.ask(q, lambda p: f"Calibrate every 12 months [{ref_for(p, 'Calibrate every 12 months')}].")
        self.assertEqual(cp.workflow, "equipment")
        self.assertIn("Every 12 months", cp.cards[0])
        self.assertEqual(status, "answered")

    def test_6_unrelated_question_abstains_without_llm(self):
        cp, plan, status, text = self.ask("How do I repair a violin?")
        self.assertEqual((status, text, self.prompts), ("insufficient_evidence", None, []))

    def test_7_other_encounters_context_never_reaches_the_prompt(self):
        es = EncounterStore(self.dir / "enc.db")
        a, b = es.create("Demo patient A"), es.create("Demo patient B")
        es.add_note(a["encounter_id"], a["access_token"], "PATIENT-A-ONLY eGFR 25")
        es.add_note(b["encounter_id"], b["access_token"], "PATIENT-B-ONLY history of synthetic wobble")
        q = "What is the maximum dose of Fictitrol per day?"
        es.add_message(b["encounter_id"], b["access_token"], "user", q)
        block, _ = build_context_block(es, b["encounter_id"], b["access_token"])
        self.ask(q, context=block)
        self.assertIn("PATIENT-B-ONLY", self.prompts[0])
        self.assertNotIn("PATIENT-A-ONLY", self.prompts[0])
        self.assertFalse(es.authorize(a["encounter_id"], b["access_token"]))

    def test_8_variant_name_gets_check_the_product_notice(self):
        cp = plan_clinical(self.store, "What is the dose of Fictitrol XR?")
        self.assertTrue(any("exact product" in n for n in cp.safety_notices))

    def test_9_symptom_record_routes_to_symptom_workflow_and_shows_red_flags_first(self):
        cp = plan_clinical(self.store, "What are the red flags for synthetic wobble?")
        self.assertEqual(cp.workflow, "symptom")
        self.assertIn("loss of synthetic balance", cp.cards[0])


if __name__ == "__main__":
    unittest.main()

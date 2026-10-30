"""
Phase 4 tests — workflow routing, exact-name record lookup/cards, warnings & absent-data wording, urgent-symptom and
patient-specific safety rules, no-LLM paths, record-vs-document conflicts.
All reference data is SYNTHETIC (invented drugs/devices/symptoms). Offline: toy embedder, injected "LLM".
These tests prove the deterministic logic only; they say nothing about clinical correctness of any real content.
Run from backend/:   python -B -m unittest discover -s tests -t . -v
"""
import json
import unittest

from knowledge.clinical import (
    NOT_STATED, NO_NARRATIVE, PATIENT_RULE, ClinicalAnswerer, classify, ground, match_record_ids, plan_clinical,
    records_text, render_record, without_llm,
)
from knowledge.red_flags import detect_red_flags, is_patient_specific, red_flag_banner
from tests.test_grounded import FICT_ALT, FICTITROL, GroundedBase

MEDS = ("Name,Dose,Contraindications,Warnings\n"
        'Fictitrol,Maximum 100 mg per day,eGFR < 30 mL/min/1.73m2,Monitor synthetic zorb levels\n'
        "Zorbex,5 mg/kg,,\n"
        "Quibbleplex,10 mg,Synthetic liver failure,\n")
EQUIP = "Device,Manufacturer,Range\nExamplometer,Acme (synthetic),0-300 mmHg\nBP cuff,Acme (synthetic),20-250 mmHg\nBP,Acme,x\n"
SYMPTOMS = json.dumps([{"name": "Synthetic wobble", "associated_with": "synthetic hyperzorbia", "red_flags": "none listed"}])


class ClinicalBase(GroundedBase):
    def setUp(self):
        super().setUp()
        self.load(("meds.csv", MEDS), ("devices.csv", EQUIP))
        self.load(("symptoms.json", SYMPTOMS), category="symptom")     # symptoms are never inferred: tag them explicitly

    def answerer(self, generate=None):
        self.calls = []

        def gen(prompt):
            self.calls.append(prompt)
            return (generate or (lambda p: "The maximum dose is 100 mg per day [S1]."))(prompt)
        return ClinicalAnswerer(self.store, self.retriever, gen)


class RecordLookupTests(ClinicalBase):
    def test_exact_name_card_is_verbatim_with_provenance_and_warnings_first(self):
        cp = plan_clinical(self.store, "What is the maximum dose of Fictitrol?")
        self.assertEqual((cp.workflow, [r["name"] for r in cp.matched]), ("medicine", ["Fictitrol"]))
        card = cp.cards[0]
        self.assertIn("Maximum 100 mg per day", card)
        self.assertIn("eGFR < 30 mL/min/1.73m2", card)                        # symbols and compound units untouched
        self.assertLess(card.index("Contraindications"), card.index("Dose"))
        self.assertLess(card.index("Warnings"), card.index("Dose"))
        self.assertIn("meds.csv (v1, row 2)", card)

    def test_structured_view_matches_the_text_card_and_marks_warnings_and_absence(self):
        from knowledge.clinical import record_view
        cp = plan_clinical(self.store, "Zorbex")
        v = cp.views[0]
        self.assertEqual((v["name"], v["category"]), ("Zorbex", "medicine"))
        by = {r["key"]: r for r in v["rows"]}
        self.assertTrue(by["Contraindications"]["warning"] and by["Contraindications"]["not_stated"])
        self.assertEqual(by["Contraindications"]["value"], NOT_STATED)
        self.assertEqual(by["Dose"]["value"], "5 mg/kg")
        self.assertFalse(by["Dose"]["warning"])
        self.assertIn("meds.csv (v1, row 3)", v["source"])
        text = cp.cards[0]
        for r in v["rows"]:
            self.assertIn(("⚠ " if r["warning"] else "") + f"{r['key']}: {r['value']}", text)
        self.assertEqual(plan_clinical(self.store, "Fictitrol").views[0]["rows"][0]["value"], "eGFR < 30 mL/min/1.73m2")

    def test_blank_or_missing_safety_fields_say_not_stated_never_none(self):
        card = plan_clinical(self.store, "Zorbex").cards[0]
        self.assertIn(f"Contraindications: {NOT_STATED}", card)
        self.assertIn(f"Warnings / precautions: {NOT_STATED}", card)
        self.assertNotIn("None", card)
        self.assertIn(f"Warnings / precautions: {NOT_STATED}", plan_clinical(self.store, "Examplometer").cards[0])

    def test_equipment_and_symptom_records_route_by_category(self):
        self.assertEqual(plan_clinical(self.store, "Examplometer range").workflow, "equipment")
        self.assertEqual(plan_clinical(self.store, "Tell me about synthetic wobble").workflow, "symptom")

    def test_untagged_records_still_get_a_card_but_route_to_general(self):
        self.load(("other.json", json.dumps([{"name": "Plain item", "note": "x"}])))
        cp = plan_clinical(self.store, "Plain item")
        self.assertEqual((cp.workflow, len(cp.cards)), ("general", 1))

    def test_no_fuzzy_matching_or_partial_words(self):
        for q in ("dose of Fictitrl", "dose of Fictitrolish", "dose of Fictit", "Fictitrols"):
            self.assertEqual(plan_clinical(self.store, q).cards, [], q)

    def test_case_punctuation_and_possessive_still_match(self):
        for q in ("FICTITROL?", "fictitrol's dose", "(Fictitrol)", "dose-of-fictitrol"):
            self.assertEqual(len(plan_clinical(self.store, q).matched), 1, q)

    def test_longest_name_wins_and_contained_name_does_not_double_match(self):
        names = [r["name"] for r in plan_clinical(self.store, "range of the BP cuff").matched]
        self.assertEqual(names, ["BP cuff"])
        self.assertEqual([r["name"] for r in plan_clinical(self.store, "what is BP").matched], ["BP"])

    def test_two_named_medicines_both_shown(self):
        cp = plan_clinical(self.store, "Can Fictitrol be combined with Zorbex?")
        self.assertEqual(sorted(r["name"] for r in cp.matched), ["Fictitrol", "Zorbex"])

    def test_superseded_record_values_are_never_shown(self):
        r = self.ingest("meds.csv", MEDS.replace("Maximum 100 mg per day", "Maximum 80 mg per day"))
        self.assertEqual(r.status, "success", r.message)
        card = plan_clinical(self.store, "Fictitrol").cards[0]
        self.assertIn("80 mg", card)
        self.assertNotIn("100 mg", card)
        self.assertIn("(v2,", card)

    def test_non_string_values_and_blank_cells_render_without_loss(self):
        rec = {"name": "X", "category": "other", "display_name": "x.json", "version": 1, "row_number": 1,
               "license": None, "origin": None, "fields": {"name": "X", "range": [1, 2.5], "note": "", "n": 0}}
        card = render_record(rec)
        self.assertIn("range: 1; 2.5", card)
        self.assertIn(f"note: {NOT_STATED} (blank in source)", card)
        self.assertIn("n: 0", card)


class RoutingTests(unittest.TestCase):
    def test_cue_routing_table(self):
        table = [("What are the symptoms of a synthetic rash?", "symptom"),
                 ("calibration interval of the monitor", "equipment"),
                 ("maximum dose and contraindications", "medicine"),
                 ("hello there", "general"),
                 ("", "general"),
                 ("dose of the monitor", "general")]            # tie between cues → general, not a guess
        for q, expected in table:
            self.assertEqual(classify(q, [], detect_red_flags(q)), expected, q)

    def test_red_flag_alone_routes_to_symptom(self):
        self.assertEqual(classify("patient with chest pain", [], detect_red_flags("chest pain")), "symptom")


class SafetyRuleTests(unittest.TestCase):
    def test_red_flag_table(self):
        positives = {
            "Patient has crushing chest pain": "chest_pain", "sudden shortness of breath": "breathing",
            "slurred speech and facial droop": "stroke", "he collapsed and is unresponsive": "consciousness",
            "heavy bleeding after surgery": "bleeding", "swelling of the lips after the injection": "anaphylaxis",
            "worst headache of my life": "severe_headache", "possible overdose": "overdose",
            "no pulse": "sepsis_shock", "says he wants to die": "self_harm"}
        for q, code in positives.items():
            self.assertIn(code, [f.code for f in detect_red_flags(q)], q)
        for q in ("What is the shelf life of the Examplometer?", "maximum dose of Fictitrol", "blood pressure cuff size",
                  "mild seasonal rash"):
            self.assertEqual(detect_red_flags(q), [], q)

    def test_no_negation_handling_is_deliberate(self):
        self.assertTrue(detect_red_flags("no chest pain reported"))

    def test_banner_names_the_flag_and_tells_the_clinician_to_follow_local_protocol(self):
        banner = red_flag_banner(detect_red_flags("chest pain"))
        self.assertIn("chest pain", banner)
        self.assertIn("local emergency", banner)
        self.assertEqual(red_flag_banner([]), "")

    def test_patient_specific_table(self):
        yes = ["My patient is 67 years old, what dose should I give?", "How much should I give a 70 kg adult?",
               "a 45-year-old male with fever", "Should I prescribe Fictitrol", "She weighs 52 kg",
               "calculate the dose for him", "diagnose this rash"]
        no = ["What is the maximum dose of Fictitrol?", "contraindications of Zorbex", "How often to calibrate the Examplometer?",
              "symptoms of synthetic hyperzorbia"]
        for q in yes:
            self.assertTrue(is_patient_specific(q), q)
        for q in no:
            self.assertFalse(is_patient_specific(q), q)


class AnswerFlowTests(ClinicalBase):
    def test_notices_order_urgent_then_patient_and_prompt_has_workflow_and_patient_rules(self):
        self.load(("fict.md", FICTITROL))
        cp = plan_clinical(self.store, "My patient has chest pain, what dose of Fictitrol should I give?")
        plan = ground("x Fictitrol dose", cp, self.retriever.retrieve("Fictitrol maximum dose"))
        self.assertTrue(plan.notices[0].startswith("🚨"))
        self.assertTrue(plan.notices[1].startswith("ℹ"))
        self.assertIn(PATIENT_RULE, plan.prompt)
        self.assertIn("MEDICINE reference question", plan.prompt)

    def test_safety_notices_precede_conflict_notices(self):
        self.load(("alt.txt", FICT_ALT))
        q = "chest pain; maximum dose of Fictitrol?"
        plan = ground(q, plan_clinical(self.store, q), self.retriever.retrieve("maximum dose of Fictitrol"))
        self.assertTrue(any("conflict" in n for n in plan.notices), plan.notices)
        self.assertTrue(plan.notices[0].startswith("🚨"))
        self.assertIn("conflict", plan.notices[1])

    def test_general_question_adds_no_extra_rules(self):
        self.load(("fict.md", FICTITROL))
        cp = plan_clinical(self.store, "hello")
        plan = ground("Fictitrol dose", cp, self.retriever.retrieve("Fictitrol maximum dose"))
        self.assertNotIn("\n7.", plan.prompt)
        self.assertEqual(cp.safety_notices, [])

    def test_records_only_when_no_narrative_evidence_and_the_llm_is_not_called(self):
        a = self.answerer()
        ans = a.answer("What is the maximum dose of Fictitrol?")
        self.assertEqual((ans.status, ans.text, self.calls), ("records_only", NO_NARRATIVE, []))
        self.assertIn("Maximum 100 mg per day", ans.record_cards[0])
        self.assertEqual(ans.clinical["workflow"], "medicine")

    def test_nothing_known_abstains_without_llm(self):
        ans = self.answerer().answer("how do I repair a violin")
        self.assertEqual((ans.status, self.calls, ans.record_cards), ("insufficient_evidence", [], []))

    def test_red_flag_banner_survives_abstention(self):
        ans = self.answerer().answer("chest pain zzzzqqq")
        self.assertEqual(ans.status, "insufficient_evidence")
        self.assertTrue(ans.notices and ans.notices[0].startswith("🚨"))

    def test_narrative_answer_with_record_card_is_verified_and_workflow_not_used_as_filter(self):
        self.load(("fict.md", FICTITROL))                         # document has NO category → must still be retrievable
        ans = self.answerer().answer("What is the maximum dose of Fictitrol?")
        self.assertEqual((ans.status, len(self.calls)), ("answered", 1), ans.verification and ans.verification.issues())
        self.assertEqual(ans.clinical["records"][0]["name"], "Fictitrol")
        self.assertIn("Maximum 100 mg per day", ans.record_cards[0])
        self.assertNotIn("Maximum 100 mg per day", self.calls[0])  # records are rendered by code, never fed to the model

    def test_computed_patient_dose_is_flagged_by_verification(self):
        self.load(("fict.md", FICTITROL))
        ans = self.answerer(lambda p: "For a 70 kg patient give 350 mg per day [S1].").answer(
            "My patient weighs 70 kg; what Fictitrol dose should I give?")
        self.assertEqual(ans.status, "unverified")
        self.assertTrue(ans.verification.unsupported_quantities)
        self.assertTrue(ans.clinical["patient_specific"])

    def test_record_vs_document_numeric_conflict_is_reported(self):
        self.load(("alt.txt", FICT_ALT))
        cp = plan_clinical(self.store, "maximum dose of Fictitrol")
        plan = ground("maximum dose of Fictitrol", cp, self.retriever.retrieve("maximum dose of Fictitrol"))
        conflict = [n for n in plan.notices if "conflict" in n]
        self.assertTrue(conflict, plan.notices)
        self.assertIn("R1", conflict[0])
        self.assertIn("100", conflict[0])
        self.assertIn("50", conflict[0])

    def test_records_text_has_disclaimer_only_when_cards_exist(self):
        self.assertIn("not a prescription", records_text(plan_clinical(self.store, "Fictitrol")))
        self.assertEqual(records_text(plan_clinical(self.store, "hello")), "")

    def test_without_llm_helper_matrix(self):
        cp_hit, cp_miss = plan_clinical(self.store, "Fictitrol"), plan_clinical(self.store, "violin")
        empty = ground("violin", cp_miss, self.retriever.retrieve("violin"))
        self.assertEqual(without_llm(cp_hit, empty)[0], "records_only")
        self.assertEqual(without_llm(cp_miss, empty)[0], "insufficient_evidence")
        self.load(("fict.md", FICTITROL))
        full = ground("Fictitrol", cp_hit, self.retriever.retrieve("Fictitrol maximum dose"))
        self.assertIsNone(without_llm(cp_hit, full))

    def test_get_records_refuses_ids_of_superseded_versions(self):
        old_id = match_record_ids(self.store, "Fictitrol")
        self.assertEqual(len(self.store.get_records(old_id)), 1)
        self.ingest("meds.csv", MEDS.replace("Maximum 100 mg per day", "Maximum 80 mg per day"))
        self.assertEqual(self.store.get_records(old_id), [])

    def test_match_record_ids_uses_only_active_records(self):
        ids_before = match_record_ids(self.store, "Fictitrol")
        self.ingest("meds.csv", MEDS.replace("Fictitrol,", "Fictitrol2,"))
        self.assertEqual(match_record_ids(self.store, "Fictitrol"), [])
        self.assertEqual(len(ids_before), 1)


if __name__ == "__main__":
    unittest.main()

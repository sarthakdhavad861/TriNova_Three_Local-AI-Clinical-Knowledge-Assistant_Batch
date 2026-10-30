"""
knowledge/clinical.py
Phase 4 — clinical query workflows (stdlib only, deterministic; no model involved in routing or record rendering).

  plan_clinical(store, question) → ClinicalPlan
      * workflow: medicine | equipment | symptom | general
        - an EXACT (whole-word, case-insensitive) match of an ingested record name decides the workflow by that
          record's category; otherwise keyword cues vote. There is NO fuzzy name matching: guessing a "similar" drug
          name is unsafe, so an unknown or misspelt name simply yields no record card.
      * record cards: stored fields rendered VERBATIM (units, ranges, symbols untouched), warnings/contraindications
        first, explicit "Not stated in this record" where absent (absence is never presented as "none"), full provenance.
      * urgent-symptom banner and patient-specific notice (see red_flags.py)
      * workflow-specific prompt rules for the grounded LLM answer

The router never filters retrieval by category (documents may carry no category); it only decides which record cards
to show, which prompt rules apply and what the UI is told in X-Intent.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from typing import Callable

from knowledge.answer import (
    NO_EVIDENCE_MESSAGE, Answer, GroundingPlan, citations_of, prepare_grounding, verify_answer,
)
from knowledge.red_flags import PATIENT_NOTICE, RedFlag, detect_red_flags, is_patient_specific, red_flag_banner
from knowledge.retrieval import Evidence

WORKFLOWS = ("medicine", "equipment", "symptom", "general")
NOT_STATED = "Not stated in this record"
RECORD_DISCLAIMER = ("Reference information copied from the knowledge base — not a prescription or a diagnosis. "
                     "Verify against the primary label / manual before clinical use.")

# ── routing cues (used only when no record name matches) ──────────────────────
_CUES = {
    "symptom": re.compile(r"\b(?:symptoms?|signs?\s+of|presents?\s+with|presenting|differential|pain|fever|cough|rash|"
                          r"nausea|vomiting|dizziness|headache|fatigue|swelling|diarrh\w+|dyspn\w+|causes?\s+of)\b", re.I),
    "medicine": re.compile(r"\b(?:dos(?:e|es|age)|\d+\s*(?:mg|mcg|g|ml)\b|contraindicat\w+|side[- ]effects?|adverse|"
                           r"interactions?|tablets?|capsules?|drugs?|medicines?|medications?|prescrib\w+|indications?|"
                           r"pregnan\w+)", re.I),
    "equipment": re.compile(r"\b(?:calibrat\w+|equipment|devices?|monitors?|ventilators?|steril\w+|maintenance|probes?|"
                            r"sensors?|analy[sz]ers?|defibrillators?|oximeters?|catheters?|machines?|instruments?)\b", re.I),
}

_WARN_CONTRA = {"contraindication", "contraindications"}
_WARN_CORE = {"warning", "warnings", "precaution", "precautions", "boxed_warning", "black_box_warning",
              "safety", "safety_notes", "cautions", "caution"}
_WARN_EXTRA = {"interactions", "drug_interactions", "adverse_effects", "side_effects", "pregnancy"}

WORKFLOW_RULES = {
    "medicine": ("This is a MEDICINE reference question. When the excerpts state them, cover: indication, dose and "
                 "route, contraindications, warnings/precautions, interactions. For any of these the excerpts do not "
                 "state, write \"not stated in the excerpts\" — never fill the gap from memory."),
    "equipment": ("This is a MEDICAL EQUIPMENT reference question. When the excerpts state them, cover: purpose, "
                  "operating range/specifications, setup or use, calibration and maintenance intervals, safety "
                  "warnings. For any the excerpts do not state, write \"not stated in the excerpts\"."),
    "symptom": ("This is a SYMPTOM reference question. Report only what the excerpts say about the symptom "
                "(associated conditions, red flags, suggested work-up). Do not diagnose, do not rank conditions by "
                "likelihood, and do not suggest that the patient has any condition."),
    "general": "",
}
PATIENT_RULE = ("The question concerns an individual patient. Do NOT calculate, adjust, convert or recommend a dose, "
                "and do not diagnose or choose a treatment. Quote the reference dosing/guidance text exactly as "
                "written in the excerpts and leave the decision to the clinician.")


@dataclass
class ClinicalPlan:
    workflow: str = "general"
    matched: list[dict] = field(default_factory=list)          # active records matched by exact name
    cards: list[str] = field(default_factory=list)             # rendered, parallel to `matched`
    views: list[dict] = field(default_factory=list)            # structured twins of `cards` (for the UI)
    record_evidence: list[Evidence] = field(default_factory=list)   # for conflict detection only (never a prompt source)
    red_flags: list[RedFlag] = field(default_factory=list)
    patient_specific: bool = False
    prompt_rules: str = ""
    variants: list[str] = field(default_factory=list)          # "Fictitrol XR" etc.: the question names more than the record

    @property
    def safety_notices(self) -> list[str]:
        out = []
        if self.red_flags:
            out.append(red_flag_banner(self.red_flags))
        if self.patient_specific:
            out.append(PATIENT_NOTICE)
        if self.variants:
            out.append(variant_notice(self.variants, self.matched))
        return out

    def summary(self) -> dict:
        return {"workflow": self.workflow, "records": [{"record_id": r["record_id"], "name": r["name"],
                                                         "source_id": r["source_id"], "version": r["version"]}
                                                        for r in self.matched],
                "urgent_flags": [f.code for f in self.red_flags], "patient_specific": self.patient_specific}


# ── name matching ─────────────────────────────────────────────────────────────
def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def match_record_ids(store, question: str) -> list:
    """Record ids whose name occurs in the question as a whole-word phrase (exact, no fuzziness); longest names first,
    and a name wholly inside a longer matched name does not match separately."""
    work = f" {_norm(question)} "
    names: dict[str, list] = {}
    for r in store.record_index():
        n = _norm(r["name"])
        if len(n) >= 2:
            names.setdefault(n, []).append(r["record_id"])
    hits: list = []
    for n in sorted(names, key=lambda x: (-len(x), x)):
        needle = f" {n} "
        if needle in work:
            hits.extend(names[n])
            work = work.replace(needle, " " * len(needle))
    return hits


# A record matches by exact name, but a question may name a *different product* that merely contains it
# ("Fictitrol XR", "Fictitrol-5", "non-Fictitrol"). Formulation/strength can change dose and safety information, so the
# card is still shown but the clinician is told to confirm it applies.
_VARIANT_WORDS = (r"xr|sr|er|cr|xl|la|iv|im|sc|pr|dr|mr|odt|forte|plus|junior|jr|paediatric|pediatric|infant|neonatal|"
                  r"topical|ophthalmic|nasal|inhaled|injection|injectable|syrup|suspension|cream|gel|ointment|drops|patch|"
                  r"combination|combo|max|extra|rapid|retard|depot")


def find_variants(question: str, matched: list[dict]) -> list[str]:
    found: list[str] = []
    for r in matched:
        name = re.escape(str(r["name"]).strip())
        if not name:
            continue
        pat = re.compile(rf"(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[-‐–])?{name}(?:[-‐–][A-Za-z0-9]+|\s+(?:{_VARIANT_WORDS})(?![A-Za-z0-9]))?(?![A-Za-z0-9])",
                         re.I)
        for m in pat.finditer(question or ""):
            phrase = m.group(0).strip()
            if phrase.lower() != str(r["name"]).strip().lower() and phrase not in found:
                found.append(phrase)
    return found


def variant_notice(variants: list[str], matched: list[dict]) -> str:
    names = ", ".join(f"“{r['name']}”" for r in matched)
    asked = ", ".join(f"“{v}”" for v in variants)
    return (f"⚠ Check the exact product: the question mentions {asked}, but the record found is {names}. "
            "Formulations, strengths and indications can differ — confirm that the record shown applies before relying on it.")


# ── rendering ─────────────────────────────────────────────────────────────────
def _key(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")


def _show(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return "; ".join(_show(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else str(v)


def record_view(rec: dict) -> dict:
    """Structured form of a record card (the UI renders this; `render_record` is its plain-text twin).
    Warnings/contraindications come first; absent or blank ones are explicit rows saying so."""
    shown = {k: _show(v).strip() for k, v in rec["fields"].items()}
    cat = rec["category"]
    rows: list[dict] = []
    used: set[str] = set()

    def group(label: str, keys: set[str], mandatory: bool):
        present = [(k, v) for k, v in shown.items() if _key(k) in keys]
        used.update(k for k, _ in present)
        filled = [(k, v) for k, v in present if v]
        if filled:
            rows.extend({"key": k, "value": v, "warning": True, "not_stated": False} for k, v in filled)
        elif mandatory:
            rows.append({"key": label, "value": NOT_STATED, "warning": True, "not_stated": True})

    group("Contraindications", _WARN_CONTRA, cat == "medicine")
    group("Warnings / precautions", _WARN_CORE, cat in ("medicine", "equipment"))
    group("", _WARN_EXTRA, False)
    for k, v in shown.items():
        if k not in used:
            rows.append({"key": k, "value": v if v else NOT_STATED + " (blank in source)", "warning": False,
                         "not_stated": not v})
    source = (f"{rec['display_name']} (v{rec['version']}, row {rec['row_number']})"
              + (f" · licence: {rec['license']}" if rec.get("license") else "")
              + (f" · origin: {rec['origin']}" if rec.get("origin") else ""))
    return {"name": rec["name"], "category": cat, "source": source, "rows": rows}


def render_record(rec: dict) -> str:
    """Verbatim plain-text card (same content as record_view)."""
    v = record_view(rec)
    lines = [f"**{v['name']}** — {v['category']} record", f"Source: {v['source']}"]
    lines += [("⚠ " if r["warning"] else "") + f"{r['key']}: {r['value']}" for r in v["rows"]]
    return "\n".join(lines)


def _as_evidence(rec: dict, n: int) -> Evidence:
    text = "; ".join(f"{k}: {_show(v)}" for k, v in rec["fields"].items())
    return Evidence(chunk_id=f"record:{rec['record_id']}", source_id=rec["source_id"] + "#record",
                    display_name=rec["display_name"], version=rec["version"], text=text, kind="record",
                    category=rec["category"], lexical_coverage=1.0, ref=f"R{n}")


# ── planning ──────────────────────────────────────────────────────────────────
def classify(question: str, matched: list[dict], flags: list[RedFlag]) -> str:
    if matched:
        cats = [r["category"] for r in matched if r["category"] in ("medicine", "equipment", "symptom")]
        if cats:
            return max(set(cats), key=lambda c: (cats.count(c), c == "medicine"))
    score = {w: len(p.findall(question or "")) for w, p in _CUES.items()}
    if flags:
        score["symptom"] += 1
    best = max(score.values())
    winners = [w for w, s in score.items() if s == best]
    return winners[0] if best > 0 and len(winners) == 1 else "general"


def plan_clinical(store, question: str) -> ClinicalPlan:
    matched = store.get_records(match_record_ids(store, question))
    flags = detect_red_flags(question)
    patient = is_patient_specific(question)
    workflow = classify(question, matched, flags)
    rules = [r for r in (WORKFLOW_RULES[workflow], PATIENT_RULE if patient else "") if r]
    return ClinicalPlan(
        workflow=workflow, matched=matched, cards=[render_record(r) for r in matched],
        views=[record_view(r) for r in matched],
        record_evidence=[_as_evidence(r, i) for i, r in enumerate(matched, start=1)],
        red_flags=flags, patient_specific=patient, prompt_rules="\n".join(rules),
        variants=find_variants(question, matched))


NO_NARRATIVE = ("No narrative excerpts in the knowledge base matched this question, so no generated summary is given. "
                "The record(s) above are the only match.")


def records_text(cp: ClinicalPlan) -> str:
    """Record cards plus the disclaimer (empty string if none matched)."""
    if not cp.cards:
        return ""
    return "\n\n".join(cp.cards) + "\n\n" + RECORD_DISCLAIMER


def ground(question: str, cp: ClinicalPlan, retrieval, *, max_chunks: int = 5, max_words: int = 1400,
           context_block: str = "") -> GroundingPlan:
    """Grounded prompt with this workflow's rules; urgent/patient notices come first, structured records take part in
    numeric-conflict detection. Retrieval is NOT filtered by workflow."""
    plan = prepare_grounding(question, retrieval, max_chunks=max_chunks, max_words=max_words,
                             extra_rules=cp.prompt_rules, reference=cp.record_evidence,
                             context_block=context_block)
    plan.notices = cp.safety_notices + plan.notices
    return plan


def without_llm(cp: ClinicalPlan, plan: GroundingPlan) -> tuple[str, str] | None:
    """(status, text) when no model call is made: nothing retrieved from narrative sources."""
    if not plan.insufficient:
        return None
    return ("records_only", NO_NARRATIVE) if cp.cards else ("insufficient_evidence", NO_EVIDENCE_MESSAGE)


class ClinicalAnswerer:
    """Sync orchestration for tests/eval; the API composes the same functions around async streaming."""

    def __init__(self, store, retriever, generate: Callable[[str], str], *, max_chunks: int = 5, max_words: int = 1400):
        self.store, self.retriever, self.generate = store, retriever, generate
        self.max_chunks, self.max_words = max_chunks, max_words

    def answer(self, question: str) -> Answer:
        cp = plan_clinical(self.store, question)
        retrieval = self.retriever.retrieve(question)
        plan = ground(question, cp, retrieval, max_chunks=self.max_chunks, max_words=self.max_words)
        common = dict(notices=plan.notices, retrieval=retrieval.stats, clinical=cp.summary(), record_cards=cp.cards)
        skipped = without_llm(cp, plan)
        if skipped:                                              # the LLM is never called without narrative evidence
            return Answer(skipped[0], skipped[1], **common)
        text = self.generate(plan.prompt).strip()
        v = verify_answer(text, plan.used)
        status = "insufficient_evidence" if v.abstained else "answered" if v.ok else "unverified"
        return Answer(status, text, citations_of(plan.used, v.cited_refs), v, dropped_excerpts=plan.dropped, **common)

"""
knowledge/red_flags.py
Rule-based safety detectors (stdlib only, no model involved, fully deterministic).

  detect_red_flags(text)       → emergency-type phrases found in the question
  is_patient_specific(text)    → question appears to be about an individual patient (dose / diagnosis / treatment)

Design choices (deliberate, documented in PROJECT_STATUS.md):
* Over-trigger rather than under-trigger. There is NO negation handling: "no chest pain" still shows the banner,
  because guessing negation wrongly ("no improvement, chest pain persists") is worse than an unneeded reminder.
* The banner never replaces or blocks the reference answer, and it never gives treatment instructions: it tells the
  clinician to follow their local emergency protocol. This list is a SAFETY NET, not a triage tool, and it is NOT
  clinically validated or exhaustive — a clinician must review/extend it before any real use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedFlag:
    code: str
    label: str
    matched: str


_F = re.IGNORECASE
_RULES: list[tuple[str, str, re.Pattern]] = [
    ("chest_pain", "chest pain / pressure",
     re.compile(r"\bchest\s+(?:pain|pressure|tightness|discomfort)\b|\bcrushing\s+chest\b", _F)),
    ("breathing", "severe difficulty breathing",
     re.compile(r"\b(?:short(?:ness)?\s+of\s+breath|difficulty\s+breathing|trouble\s+breathing|can'?t\s+breathe|"
                r"cannot\s+breathe|respiratory\s+(?:distress|arrest|failure)|stridor|gasping|choking)\b", _F)),
    ("stroke", "possible stroke signs",
     re.compile(r"\b(?:facial\s+droop|face\s+drooping|slurred\s+speech|sudden\s+(?:weakness|numbness|confusion|"
                r"loss\s+of\s+vision|vision\s+loss)|one[- ]sided\s+weakness|stroke)\b", _F)),
    ("consciousness", "loss of consciousness / seizure",
     re.compile(r"\b(?:unconscious|unresponsive|collapsed?|passed\s+out|fainted|syncope|seizures?|convulsions?|"
                r"status\s+epilepticus)\b", _F)),
    ("bleeding", "severe or uncontrolled bleeding",
     re.compile(r"\b(?:severe|heavy|massive|uncontrolled|profuse)\s+(?:bleeding|haemorrhage|hemorrhage)\b|"
                r"\b(?:haemorrhage|hemorrhage|hematemesis|vomiting\s+blood|coughing\s+(?:up\s+)?blood)\b", _F)),
    ("anaphylaxis", "possible anaphylaxis",
     re.compile(r"\b(?:anaphyla\w+|swelling\s+of\s+(?:the\s+)?(?:lips|tongue|throat|face)|throat\s+(?:closing|swelling))\b",
                _F)),
    ("severe_headache", "sudden severe headache",
     re.compile(r"\bthunderclap\b|\bworst\s+headache\b|\bsudden\s+severe\s+headache\b", _F)),
    ("overdose", "overdose / poisoning",
     re.compile(r"\b(?:overdos\w+|poisoning|ingested\s+too\s+much|took\s+too\s+many)\b", _F)),
    ("sepsis_shock", "shock / sepsis signs",
     re.compile(r"\b(?:sepsis|septic\s+shock|cardiac\s+arrest|cardiogenic\s+shock|hypotensive\s+shock|"
                r"not\s+breathing|no\s+pulse|pulseless)\b", _F)),
    ("self_harm", "suicidal thoughts / self-harm",
     re.compile(r"\b(?:suicid\w+|self[- ]harm\w*|want(?:s|ed)?\s+to\s+die|kill(?:ing)?\s+(?:him|her|them|my)self)\b", _F)),
]


def detect_red_flags(text: str) -> list[RedFlag]:
    found: dict[str, RedFlag] = {}
    for code, label, pat in _RULES:
        m = pat.search(text or "")
        if m and code not in found:
            found[code] = RedFlag(code, label, m.group(0))
    return list(found.values())


def red_flag_banner(flags: list[RedFlag]) -> str:
    if not flags:
        return ""
    what = "; ".join(f"{f.label} (“{f.matched}”)" for f in flags)
    return ("🚨 URGENT-SYMPTOM KEYWORDS DETECTED: " + what + ".\n"
            "If this concerns a patient who is unwell right now, follow your local emergency protocol / call the local "
            "emergency number immediately — do not wait for this tool. This assistant gives reference information "
            "only; it cannot assess an emergency (keyword check, not a clinical triage).")


_PATIENT_PATTERNS = [
    r"\bmy\s+patient\b", r"\bthis\s+patient\b", r"\bthe\s+patient\b", r"\bour\s+patient\b",
    r"\bpatient\s+(?:is|has|with|weighs|presents)\b",
    r"\b\d{1,3}\s*[- ]?\s*(?:year|yr|y)s?[- ]?\s*(?:old|o)\b", r"\b\d{1,3}\s*y/?o\b", r"\b\d{1,3}\s*(?:yo|y\.o\.)",
    r"\b\d{1,3}\s*(?:month|week)s?[- ]?old\b", r"\b(?:he|she|they)\s+(?:is|has|weighs|presents|takes|developed)\b",
    r"\bweighs?\s+\d", r"\bweighing\s+\d", r"\bhis\s+(?:weight|egfr|creatinine)\b", r"\bher\s+(?:weight|egfr|creatinine)\b",
    r"\bshould\s+i\s+(?:give|prescribe|start|stop|increase|reduce|administer|use)\b",
    r"\bwhat\s+(?:dose|dosage)\s+should\b", r"\bhow\s+much\s+(?:should|do)\s+i\s+(?:give|prescribe)\b",
    r"\b(?:calculate|compute|work\s+out|adjust)\s+(?:the\s+|a\s+|his\s+|her\s+|their\s+)?(?:dose|dosage)\b",
    r"\bdiagnos(?:e|is)\s+(?:this|my|the|him|her|them)\b", r"\bwhat\s+(?:does|do)\s+(?:he|she|they|this\s+patient)\s+have\b",
    r"\bis\s+it\s+safe\s+(?:for|to\s+give)\s+(?:him|her|them|my|this)\b",
]
_PATIENT_RE = re.compile("|".join(_PATIENT_PATTERNS), _F)

PATIENT_NOTICE = ("ℹ This looks like a question about an individual patient. This assistant provides reference "
                  "information only: it does not diagnose, choose treatment, or calculate or adjust doses. "
                  "Reference text from the knowledge base is shown below for your own clinical judgement.")


def is_patient_specific(text: str) -> bool:
    return bool(_PATIENT_RE.search(text or ""))

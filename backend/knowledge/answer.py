"""
knowledge/answer.py
Grounded answering for a clinical *reference* assistant (stdlib only; the LLM is injected).

  prepare_grounding()  retrieved evidence → numbered, UNTRUNCATED excerpts + rules (or "insufficient")
  verify_answer()      deterministic post-check of the generated text against the excerpts
  detect_discrepancies() possible numeric conflicts between different sources
  GroundedAnswerer     sync orchestration used by tests/eval; the API uses the same pure functions

What verification can and cannot do: it proves that cited ids exist and that every dose-like quantity
(number + unit, or symbol comparison such as "< 30") in a sentence appears in the excerpts it cites. It does NOT
prove that a sentence is clinically entailed by its excerpt; weak keyword support is reported as a warning only.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Callable

from knowledge.retrieval import Evidence, RetrievalResult, coverage, query_terms, tokens

NO_EVIDENCE_MESSAGE = ("The knowledge base does not contain enough information to answer this question. "
                       "No answer is given rather than guessing — please consult the primary references.")
LLM_ABSTAIN = "The provided sources do not contain enough information to answer this."

RULES = """You are a clinical REFERENCE assistant for doctors. You are not a diagnostic or prescribing system.
Answer the question using ONLY the numbered excerpts below. Rules:
1. Cite every factual statement with the excerpt number in square brackets, e.g. [S1] or [S1][S3], placed right after the statement.
2. Copy doses, units, ranges, contraindications and warnings exactly as written in the excerpt. Never convert, round, or add figures.
3. Do not use outside knowledge. If the excerpts do not contain the answer, reply with exactly: """ + LLM_ABSTAIN + """
4. If excerpts disagree, say that they disagree and report each with its citation; do not choose between them.
5. Do not give patient-specific diagnoses, treatment decisions or doses. Present reference information for the clinician's judgment.
6. Be concise."""

# ── quantities ────────────────────────────────────────────────────────────────
_UNITS = (r"(?:mg|mcg|µg|μg|ug|kg|g|ml|l|iu|units?|mmol|mol|meq|%|mmhg|bpm|°c|°f|hours?|hrs?|h|days?|weeks?|"
          r"months?|years?|minutes?|mins?|min|seconds?|secs?|times|x)")
_QTY = re.compile(rf"(?<![\w.])(\d+(?:[.,]\d+)?)(?:\s*[-–—]\s*(\d+(?:[.,]\d+)?))?\s*({_UNITS}(?:/[a-z²][a-z0-9²]*)*)(?![a-z0-9])",
                  re.I)
_CMP = re.compile(r"(<=|>=|<|>|≤|≥)\s*(\d+(?:[.,]\d+)?)")
_UNIT_ALIASES = {"µg": "mcg", "μg": "mcg", "ug": "mcg", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
                 "mins": "min", "minute": "min", "minutes": "min", "sec": "s", "secs": "s", "second": "s",
                 "seconds": "s", "days": "day", "weeks": "week", "months": "month", "years": "year", "units": "unit"}


def _num(s: str) -> str:
    try:
        return format(Decimal(s.replace(",", ".")).normalize(), "f")
    except InvalidOperation:
        return s


def _unit(u: str) -> str:
    head, *rest = u.lower().split("/")
    return "/".join([_UNIT_ALIASES.get(head, head), *rest])


def quantities(text: str) -> list[tuple[str, str]]:
    """(value, unit) pairs, e.g. '10-20 mg/kg' → [('10','mg/kg'), ('20','mg/kg')]; symbol comparisons → ('30','<')."""
    out: list[tuple[str, str]] = []
    for m in _QTY.finditer(text or ""):
        unit = _unit(m.group(3))
        out += [(_num(v), unit) for v in (m.group(1), m.group(2)) if v]
    for m in _CMP.finditer(text or ""):
        op = {"<=": "≤", ">=": "≥"}.get(m.group(1), m.group(1))
        out.append((_num(m.group(2)), op))
    return out


def _qty_tokens(text: str) -> set[str]:
    return {f"{v}{u}" for v, u in quantities(text)}


# ── grounding ─────────────────────────────────────────────────────────────────
@dataclass
class GroundingPlan:
    insufficient: bool
    prompt: str = ""
    used: list[Evidence] = field(default_factory=list)
    dropped: int = 0
    notices: list[str] = field(default_factory=list)


def detect_discrepancies(evidence: list[Evidence], min_coverage: float = 0.5) -> list[dict]:
    """Different sources giving disjoint values for the same unit on a topic matching the query. Heuristic."""
    found, seen = [], set()
    for a, b in itertools.combinations(evidence, 2):
        if a.source_id == b.source_id or min(a.lexical_coverage, b.lexical_coverage) < min_coverage:
            continue
        qa, qb = _by_unit(a.text), _by_unit(b.text)
        for unit in sorted(qa.keys() & qb.keys()):
            if unit in "<>≤≥" or qa[unit] & qb[unit] or len(qa[unit]) > 3 or len(qb[unit]) > 3:
                continue
            if (a.ref, b.ref, unit) in seen:
                continue
            seen.add((a.ref, b.ref, unit))
            found.append({"unit": unit, "a": {"ref": a.ref, "values": sorted(qa[unit])},
                          "b": {"ref": b.ref, "values": sorted(qb[unit])}})
    return found


def _by_unit(text: str) -> dict[str, set[str]]:
    d: dict[str, set[str]] = {}
    for v, u in quantities(text):
        d.setdefault(u, set()).add(v)
    return d


def prepare_grounding(question: str, retrieval: RetrievalResult, *, max_chunks: int = 5,
                      max_words: int = 1400, extra_rules: str = "",
                      reference: list[Evidence] | None = None, context_block: str = "") -> GroundingPlan:
    """Whole chunks only: chunks that do not fit the word budget are dropped, never truncated.
    `extra_rules` (Phase 4 workflow/patient rules) is appended to RULES; `reference` evidence (structured records) takes
    part in numeric-conflict detection but is never put into the prompt. `context_block` (Phase 5, one encounter's private
    context) goes between the excerpts and the question; it is not a source and is never used by verification."""
    notices = [f"Note: {n}." for n in retrieval.notes]
    if not retrieval.evidence:
        return GroundingPlan(insufficient=True, notices=notices)
    used: list[Evidence] = []
    total = dropped = 0
    for ev in retrieval.evidence[:max_chunks]:
        w = len(ev.text.split())
        if used and total + w > max_words:
            dropped += 1
            continue
        used.append(replace(ev, ref=f"S{len(used) + 1}"))
        total += w
    dropped += max(0, len(retrieval.evidence) - max_chunks)
    for d in detect_discrepancies([*(reference or []), *used]):
        notices.append(f"⚠ Possible conflict between sources (automatic check): [{d['a']['ref']}] gives "
                       f"{', '.join(d['a']['values'])} {d['unit']} while [{d['b']['ref']}] gives "
                       f"{', '.join(d['b']['values'])} {d['unit']}. Verify against the original sources.")
    blocks = []
    for ev in used:
        meta = [f"Source: {ev.display_name}"] + ([f"page {ev.page}"] if ev.page else []) \
            + ([f"section: {ev.section}"] if ev.section else []) + [f"version {ev.version}"]
        blocks.append(f"[{ev.ref}] " + " | ".join(meta) + f"\n{ev.text}")
    rules = RULES + (f"\n7. {extra_rules}" if extra_rules else "")
    ctx = f"\n\n{context_block.strip()}" if context_block.strip() else ""
    prompt = f"{rules}\n\nExcerpts:\n\n" + "\n\n".join(blocks) + f"{ctx}\n\nQuestion: {question.strip()}\n\nAnswer:"
    return GroundingPlan(insufficient=False, prompt=prompt, used=used, dropped=dropped, notices=notices)


# ── verification ──────────────────────────────────────────────────────────────
_REF = re.compile(r"\[S(\d+)\]")


@dataclass
class Verification:
    ok: bool
    abstained: bool = False
    cited_refs: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    unsupported_quantities: list[dict] = field(default_factory=list)
    uncited_sentences: list[str] = field(default_factory=list)
    weakly_supported: list[str] = field(default_factory=list)

    def issues(self) -> list[str]:
        out = [f"citation [{r}] does not match any provided source" for r in self.invalid_refs]
        out += [f"“{u['quantity']}” is not in the cited source(s): {u['sentence'][:120]}"
                for u in self.unsupported_quantities]
        if not self.ok and not self.cited_refs and not self.invalid_refs:
            out.append("the answer cites no source")
        out += [f"no citation: {s[:120]}" for s in self.uncited_sentences]
        out += [f"weak keyword support for its citation: {s[:120]}" for s in self.weakly_supported]
        return out

    def as_dict(self) -> dict:
        d = asdict(self)
        d["issues"] = self.issues()
        return d


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for frag in (f.strip() for f in re.split(r"(?<=[.!?])\s+|\n+", text or "")):
        if not frag:
            continue
        if out and re.fullmatch(r"(?:\[S\d+\]\s*)+", frag):
            out[-1] += " " + frag
        else:
            out.append(frag)
    return out


def verify_answer(answer: str, used: list[Evidence]) -> Verification:
    plain = _REF.sub("", answer or "").strip()
    if plain in (NO_EVIDENCE_MESSAGE, LLM_ABSTAIN) or plain.startswith(LLM_ABSTAIN):
        return Verification(ok=True, abstained=True)
    by_ref = {e.ref: e for e in used}
    v = Verification(ok=False)
    cited: set[str] = set()
    for sentence in split_sentences(answer):
        refs = _REF.findall(sentence)
        good = [f"S{r}" for r in refs if f"S{r}" in by_ref]
        v.invalid_refs += [f"S{r}" for r in refs if f"S{r}" not in by_ref and f"S{r}" not in v.invalid_refs]
        cited.update(good)
        basis = [by_ref[r] for r in good] or used
        basis_text = " ".join(e.text for e in basis)
        body = _REF.sub("", sentence)
        supported = _qty_tokens(basis_text)
        for val, unit in quantities(body):
            if f"{val}{unit}" not in supported:
                v.unsupported_quantities.append({"sentence": body.strip(), "quantity": f"{val} {unit}",
                                                 "cited": good})
        terms = query_terms(body)
        if len(terms) >= 3:
            if not refs:
                v.uncited_sentences.append(body.strip())
            elif good and coverage(terms, tokens(basis_text)) < 0.34:
                v.weakly_supported.append(body.strip())
    v.cited_refs = sorted(cited, key=lambda r: int(r[1:]))
    v.ok = bool(v.cited_refs) and not v.invalid_refs and not v.unsupported_quantities
    return v


def verification_footer(v: Verification) -> str:
    """Text appended to a streamed answer when the post-check found something the doctor should know."""
    if v.abstained or (v.ok and not v.uncited_sentences and not v.weakly_supported):
        return ""
    head = ("⚠ Evidence check FAILED — do not rely on this answer without checking the sources:" if not v.ok
            else "ℹ Evidence check notes:")
    return "\n\n---\n" + head + "\n" + "\n".join(f"- {i}" for i in v.issues())


# ── orchestration (sync; used by tests and the eval harness) ─────────────────
def citations_of(used: list[Evidence], cited_refs: list[str]) -> list[dict]:
    return [{"ref": e.ref, "chunk_id": e.chunk_id, "source_id": e.source_id, "display_name": e.display_name,
             "label": e.label(), "version": e.version, "page": e.page, "section": e.section, "text": e.text,
             "score": e.score, "category": e.category, "license": e.license, "origin": e.origin,
             "cited": e.ref in cited_refs} for e in used]


@dataclass
class Answer:
    status: str                       # answered | unverified | insufficient_evidence | records_only
    text: str
    citations: list[dict] = field(default_factory=list)
    verification: Verification | None = None
    notices: list[str] = field(default_factory=list)
    retrieval: dict = field(default_factory=dict)
    dropped_excerpts: int = 0
    clinical: dict = field(default_factory=dict)          # Phase 4: workflow, matched records, urgent flags
    record_cards: list[str] = field(default_factory=list)  # Phase 4: verbatim structured-record cards

    def as_dict(self) -> dict:
        d = asdict(self)
        d["verification"] = self.verification.as_dict() if self.verification else None
        return d


class GroundedAnswerer:
    def __init__(self, retriever, generate: Callable[[str], str], *, max_chunks: int = 5, max_words: int = 1400):
        self.retriever, self.generate = retriever, generate
        self.max_chunks, self.max_words = max_chunks, max_words

    def answer(self, question: str) -> Answer:
        result = self.retriever.retrieve(question)
        plan = prepare_grounding(question, result, max_chunks=self.max_chunks, max_words=self.max_words)
        if plan.insufficient:                                    # the LLM is never called without evidence
            return Answer("insufficient_evidence", NO_EVIDENCE_MESSAGE, notices=plan.notices, retrieval=result.stats)
        text = self.generate(plan.prompt).strip()
        v = verify_answer(text, plan.used)
        status = "insufficient_evidence" if v.abstained else "answered" if v.ok else "unverified"
        return Answer(status, text, citations_of(plan.used, v.cited_refs), v, plan.notices, result.stats, plan.dropped)

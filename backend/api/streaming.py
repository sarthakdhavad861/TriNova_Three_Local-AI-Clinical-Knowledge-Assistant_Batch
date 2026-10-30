"""
api/streaming.py
Turns one clinical answer into an ordered stream of typed events, and renders them as the legacy plain-text stream or as
NDJSON (one JSON object per line) for the Phase 6 frontend. No FastAPI/httpx imports — unit-testable offline.

Event order:  [notices] [records] token* [verification] final        (or: error — no final)
  notices      {"items": [str]}                      urgent-symptom / patient-specific / conflict / budget notices
  records      {"items": [card str], "views": [structured card], "disclaimer"}   verbatim structured-record cards (rendered by code, not the LLM)
  token        {"text"}                              generated text (or the fixed abstention / records-only message)
  verification {"ok", "issues": [str], "text"}       only when the post-check has something to report
  final        {"status", "text"}                    status: answered | unverified | insufficient_evidence | records_only
  error        {"message"}                           generation failed; nothing is stored
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Awaitable, Callable

from knowledge.answer import verification_footer, verify_answer
from knowledge.clinical import RECORD_DISCLAIMER, ClinicalPlan, without_llm

NDJSON = "application/x-ndjson"


async def answer_events(cp: ClinicalPlan, plan, llm_stream: Callable[[str], AsyncIterator[str]], *,
                        is_disconnected: Callable[[], Awaitable[bool]] | None = None,
                        on_final: Callable[[str, str, list], None] | None = None) -> AsyncIterator[dict]:
    if plan.notices:
        yield {"type": "notices", "items": list(plan.notices)}
    if cp.cards:
        yield {"type": "records", "items": list(cp.cards), "views": list(cp.views), "disclaimer": RECORD_DISCLAIMER}
    skipped = without_llm(cp, plan)
    if skipped:
        status, text = skipped
        yield {"type": "token", "text": text}
        if on_final:
            on_final(status, text, [])
        yield {"type": "final", "status": status, "text": text}
        return
    acc: list[str] = []
    try:
        async for tok in llm_stream(plan.prompt):
            if is_disconnected is not None and await is_disconnected():
                return
            acc.append(tok)
            yield {"type": "token", "text": tok}
    except RuntimeError as e:
        yield {"type": "error", "message": str(e)}
        return
    text = "".join(acc)
    v = verify_answer(text, plan.used)
    footer = verification_footer(v)
    if footer:
        yield {"type": "verification", "ok": v.ok, "issues": v.issues(), "text": footer}
    status = "insufficient_evidence" if v.abstained else "answered" if v.ok else "unverified"
    if on_final:
        on_final(status, text, v.issues() if not v.abstained else [])
    yield {"type": "final", "status": status, "text": text}


def render_text(ev: dict) -> str:
    """Legacy text/plain rendering (identical to the pre-Phase-6 stream)."""
    t = ev["type"]
    if t == "notices":
        return "\n".join(ev["items"]) + "\n\n"
    if t == "records":
        return "\n\n".join(ev["items"]) + "\n\n" + ev["disclaimer"] + "\n\n"
    if t == "token":
        return ev["text"]
    if t == "verification":
        return ev["text"]
    if t == "error":
        return f"\n\n⚠️ {ev['message']}"
    return ""


def render_ndjson(ev: dict) -> str:
    return json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n"

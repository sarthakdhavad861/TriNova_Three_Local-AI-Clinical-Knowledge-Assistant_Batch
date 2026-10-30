"""
api/routes.py
FastAPI routes — async, streaming, non-blocking uploads.
Phase 2: video ingestion removed; documents are ingested via knowledge/ (see /sources, /ingestion-events).
Phase 5: patient data lives only under /encounters/{id}/… (separate DB, secret X-Encounter-Token, uniform 404). The
         stateless /query and /ask never read encounter data.
Phase 4: questions are routed to a medicine / equipment / symptom / general workflow; exact-name records are shown as
         verbatim cards; urgent-symptom and patient-specific notices come first (knowledge/clinical.py, red_flags.py).
Phase 3: /query and /ask answer ONLY from retrieved, active knowledge-base excerpts, with numbered citations and a
         deterministic post-check; web search, the regex intent router and the retrieval cache were removed.
"""
import uuid, asyncio, json as _json
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from config.settings import (
    BASE_DIR, ALLOWED_DOC_EXTS, MAX_DOC_BYTES, MAX_CTX_CHUNKS, MAX_CONTEXT_WORDS,
    OLLAMA_BASE, MODEL_REGISTRY, DEFAULT_LLM, resolve_model,
)
from services.llm       import stream_prompt
from knowledge.answer   import (
    Answer, citations_of, prepare_grounding, verify_answer, verification_footer,
)
from knowledge.clinical import plan_clinical, ground, without_llm
from api.streaming import NDJSON, answer_events, render_ndjson, render_text
from knowledge.ingest   import safe_basename
from knowledge.runtime  import get_encounters, get_retriever, get_service, get_store
from encounters.store   import InvalidInput, NotFound, build_context_block
import concurrent.futures

router = APIRouter()

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="ingest")


# ── Request schema ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str   = Field(..., min_length=1, max_length=4000)
    model: str | None = Field(default=None)

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        if v is None:
            return v
        try:
            resolve_model(v)
            return v.strip().lower()
        except ValueError as e:
            raise ValueError(str(e))


# ── Health ─────────────────────────────────────────────────────────────────────
@router.get("/")
def health():
    totals = get_store().totals()
    return {
        "status":        "ok",
        "version":       "3.3.0",
        "total_chunks":  totals["chunks"],
        "knowledge":     totals,
        "default_model": DEFAULT_LLM,
    }


# ── Model listing ──────────────────────────────────────────────────────────────
@router.get("/models")
async def list_models():
    return list(MODEL_REGISTRY.values())


# ── Knowledge base inspection (Phase 2) ───────────────────────────────────────
# Plain `def` endpoints: FastAPI runs them in its thread pool (SQLite calls are blocking).
@router.get("/sources")
def list_sources():
    """All ingested sources with their active version, provenance and warnings."""
    store = get_store()
    return {"totals": store.totals(), "sources": store.list_sources()}


@router.get("/sources/{source_id}")
def get_source(source_id: str):
    src = get_store().get_source(source_id)
    if src is None:
        raise HTTPException(404, f"Unknown source '{source_id}'")
    return src


@router.get("/sources/{source_id}/chunks")
def source_chunks(source_id: str, version: int | None = None, limit: int = 50, offset: int = 0):
    if get_store().get_source(source_id) is None:
        raise HTTPException(404, f"Unknown source '{source_id}'")
    return get_store().list_chunks(source_id, version=version, limit=limit, offset=offset)


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    """Full text and provenance of a cited excerpt (active versions only)."""
    row = get_store().get_active_chunks([chunk_id]).get(chunk_id)
    if row is None:
        raise HTTPException(404, f"No active chunk '{chunk_id}'")
    return row


@router.get("/records")
def list_records(source_id: str | None = None, category: str | None = None,
                 name: str | None = None, limit: int = 50):
    """Structured medicine/equipment records (active versions only; name = exact, case-insensitive)."""
    return get_store().list_records(source_id=source_id, category=category, name=name, limit=limit)


@router.get("/ingestion-events")
def ingestion_events(limit: int = 50, status: str | None = None):
    """Persisted ingestion log, including rejected files and their reasons."""
    return get_store().list_events(limit=limit, status=status)


# ── Grounded question answering (Phase 3) ──────────────────────────────────────
_HEADER_EXCERPT_CHARS = 240      # response headers stay small; full text is at GET /chunks/{id}


def _source_payload(ev) -> dict:
    kind = "pdf" if ev.kind == "pdf" else "document"
    text = ev.text if len(ev.text) <= _HEADER_EXCERPT_CHARS else ev.text[:_HEADER_EXCERPT_CHARS].rstrip() + "…"
    return {
        "id": ev.chunk_id, "ref": ev.ref, "title": ev.label(), "number": ev.ref, "start": 0, "end": 0,
        "text": text, "score": ev.score, "type": kind, "source_type": kind, "filename": ev.display_name,
        "page_number": ev.page or 0, "section": ev.section, "version": ev.version, "source_id": ev.source_id,
        "url": None, "full_text_url": f"/chunks/{ev.chunk_id}",
    }


async def _require_ollama():
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=3.0) as hc:
            r = await hc.get(OLLAMA_BASE + "/api/tags")
            r.raise_for_status()
    except Exception:
        raise HTTPException(
            503,
            f"Ollama is not running or unreachable. Start it with: ollama serve (expected at {OLLAMA_BASE})"
        )


def _retrieve_and_plan(query: str):
    """Blocking work (SQLite + embedding call) — run in a worker thread. Retrieval sees ONLY the question text."""
    return plan_clinical(get_store(), query), get_retriever().retrieve(query)


def _encounter_block(encounter_id: str, token: str | None, question: str):
    """Authorised read of ONE encounter: records the question, returns (prompt block, notices). Blocking → worker thread."""
    store = get_encounters()
    store.add_message(encounter_id, token, "user", question)
    return build_context_block(store, encounter_id, token)


async def _ground(req: QueryRequest, enc: tuple[str, str | None] | None = None):
    """Route the question, retrieve, and build the grounded prompt. Returns (clinical plan, retrieval, grounding plan).
    `enc` = (encounter_id, token), already authorised by the caller; adds that encounter's private context to the prompt."""
    try:
        resolve_model(req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    loop = asyncio.get_running_loop()
    block, ctx_notices = "", []
    if enc:
        try:
            block, ctx_notices = await loop.run_in_executor(None, _encounter_block, enc[0], enc[1], req.query)
        except NotFound:
            raise HTTPException(404, "Encounter not found")
        except InvalidInput as e:
            raise HTTPException(422, str(e))
    cp, retrieval = await loop.run_in_executor(None, _retrieve_and_plan, req.query)
    plan = ground(req.query, cp, retrieval, max_chunks=MAX_CTX_CHUNKS, max_words=MAX_CONTEXT_WORDS, context_block=block)
    plan.notices += ctx_notices
    if not plan.insufficient:                       # no narrative evidence → the LLM is never called
        await _require_ollama()
    return cp, retrieval, plan


def _remember(enc, text: str, status: str, cp, plan, issues=()) -> None:
    """Store the assistant turn of an encounter: generated text + what the clinician saw around it (notices, verbatim
    record cards, source references). Knowledge-base text only — never patient context, never excerpts."""
    if not enc or not text.strip():
        return
    try:
        get_encounters().add_message(enc[0], enc[1], "assistant", text, {
            "status": status, "workflow": cp.workflow, "notices": plan.notices, "issues": list(issues), "record_cards": cp.cards, "record_views": cp.views,
            "urgent_flags": [f.code for f in cp.red_flags], "patient_specific": cp.patient_specific,
            "sources": [{"ref": e.ref, "source_id": e.source_id, "version": e.version, "chunk_id": e.chunk_id,
                         "label": e.label(), "score": e.score, "page": e.page, "section": e.section} for e in plan.used]})
    except (NotFound, InvalidInput):
        pass                                          # encounter erased mid-request: nothing to remember


async def _stream_answer(req: QueryRequest, request: Request, enc=None):
    """Streaming answer. `Accept: application/x-ndjson` → typed JSON events (see api/streaming.py); anything else →
    the legacy text/plain stream."""
    cp, retrieval, plan = await _ground(req, enc)
    ndjson = NDJSON in (request.headers.get("accept") or "").lower()
    sources = [_source_payload(e) for e in plan.used]

    async def token_generator():
        if ndjson:
            yield render_ndjson({"type": "meta", "workflow": cp.workflow, "model": resolve_model(req.model),
                                 "urgent_flags": [f.code for f in cp.red_flags], "patient_specific": cp.patient_specific,
                                 "sources": sources, "encounter": bool(enc)})
        render = render_ndjson if ndjson else render_text
        async for ev in answer_events(
                cp, plan, lambda prompt: stream_prompt(prompt, req.model), is_disconnected=request.is_disconnected,
                on_final=lambda status, text, issues: _remember(enc, text, status, cp, plan, issues)):
            out = render(ev)
            if out:
                yield out

    headers = {
        "X-Sources":     _json.dumps(sources),
        "X-Video":       "null",            # legacy header (kept so older clients keep working)
        "X-Web-Sources": "[]",              # web search was removed (local-first)
        "X-Intent":      cp.workflow,       # medicine | equipment | symptom | general
        "X-Model":       resolve_model(req.model),
        "Cache-Control": "no-store",
        "Access-Control-Expose-Headers": "X-Sources, X-Video, X-Web-Sources, X-Intent, X-Model",
    }
    return StreamingResponse(token_generator(), media_type=(NDJSON if ndjson else "text/plain") + "; charset=utf-8",
                             headers=headers)


async def _json_answer(req: QueryRequest, enc=None):
    cp, retrieval, plan = await _ground(req, enc)
    common = dict(notices=plan.notices, retrieval=retrieval.stats, clinical=cp.summary(), record_cards=cp.cards, record_views=cp.views)
    skipped = without_llm(cp, plan)
    if skipped:
        _remember(enc, skipped[1], skipped[0], cp, plan)
        return Answer(skipped[0], skipped[1], **common).as_dict() | {"model": None}
    parts = []
    try:
        async for token in stream_prompt(plan.prompt, req.model):
            parts.append(token)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    text = "".join(parts).strip()
    v = verify_answer(text, plan.used)
    status = "insufficient_evidence" if v.abstained else "answered" if v.ok else "unverified"
    _remember(enc, text, status, cp, plan, v.issues() if not v.abstained else [])
    return Answer(status, text, citations_of(plan.used, v.cited_refs), v, dropped_excerpts=plan.dropped,
                  **common).as_dict() | {"model": resolve_model(req.model)}


@router.post("/query")
async def query(req: QueryRequest, request: Request):
    """
    Stateless streaming answer (reads no patient data). Pipeline: workflow routing → exact-name record cards (verbatim)
    + hybrid retrieval over ACTIVE chunks → numbered untruncated excerpts → local LLM → deterministic post-check.
    Stream order: urgent / patient-specific / conflict notices, record cards, generated answer.
    No narrative evidence → fixed abstention (or "records only"), no LLM call.
    Headers: X-Sources (excerpt previews + provenance; full text at GET /chunks/{id}), X-Intent (workflow), X-Model.
    """
    return await _stream_answer(req, request)


@router.post("/ask")
async def ask(req: QueryRequest):
    """Same pipeline as /query (stateless), returned as one JSON document: status, text, citations, verification,
    notices, verbatim record cards and the clinical routing summary."""
    return await _json_answer(req)


# ── Patient encounters (Phase 5) ───────────────────────────────────────────────
class EncounterCreate(BaseModel):
    label: str = Field(default="", max_length=80)


class NoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


def _auth(encounter_id: str, request: Request) -> tuple[str, str | None]:
    """Backend enforcement point: valid (id, X-Encounter-Token) or a uniform 404 — unknown id, wrong token and erased
    encounter are indistinguishable. The token is only ever read from a header (never a URL, so it stays out of logs)."""
    token = request.headers.get("X-Encounter-Token")
    if not get_encounters().authorize(encounter_id, token):
        raise HTTPException(404, "Encounter not found")
    return encounter_id, token


def _guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except NotFound:
        raise HTTPException(404, "Encounter not found")
    except InvalidInput as e:
        raise HTTPException(422, str(e))


@router.post("/encounters", status_code=201)
def create_encounter(body: EncounterCreate):
    """Start a patient encounter. The access token is returned ONCE and cannot be recovered. Use synthetic or
    non-identifying labels only. There is intentionally no endpoint that lists encounters."""
    out = _guard(get_encounters().create, body.label)
    out["notice"] = "Keep access_token secret; send it as the X-Encounter-Token header. It cannot be recovered."
    return out


@router.get("/encounters/{encounter_id}")
def encounter_info(encounter_id: str, request: Request):
    enc = _auth(encounter_id, request)
    return _guard(get_encounters().metadata, *enc)


@router.delete("/encounters/{encounter_id}", status_code=204)
def erase_encounter(encounter_id: str, request: Request):
    """Permanently erase the encounter's history and context."""
    enc = _auth(encounter_id, request)
    _guard(get_encounters().erase, *enc)


@router.get("/encounters/{encounter_id}/messages")
def encounter_messages(encounter_id: str, request: Request, limit: int = 200):
    enc = _auth(encounter_id, request)
    return {"messages": _guard(get_encounters().messages, *enc, limit=limit)}


@router.post("/encounters/{encounter_id}/context", status_code=201)
def add_context(encounter_id: str, body: NoteRequest, request: Request):
    enc = _auth(encounter_id, request)
    return {"note_id": _guard(get_encounters().add_note, *enc, body.text)}


@router.get("/encounters/{encounter_id}/context")
def list_context(encounter_id: str, request: Request):
    enc = _auth(encounter_id, request)
    return {"notes": _guard(get_encounters().notes, *enc)}


@router.delete("/encounters/{encounter_id}/context/{note_id}", status_code=204)
def delete_context(encounter_id: str, note_id: int, request: Request):
    enc = _auth(encounter_id, request)
    _guard(get_encounters().delete_note, *enc, note_id)


@router.post("/encounters/{encounter_id}/query")
async def encounter_query(encounter_id: str, req: QueryRequest, request: Request):
    """/query with this encounter's context and earlier questions in the prompt; the turn is stored in the encounter."""
    return await _stream_answer(req, request, _auth(encounter_id, request))


@router.post("/encounters/{encounter_id}/ask")
async def encounter_ask(encounter_id: str, req: QueryRequest, request: Request):
    return await _json_answer(req, _auth(encounter_id, request))


# ── Upload + ingest (Phase 2) ─────────────────────────────────────────────────
async def _receive_upload(file: UploadFile) -> tuple[Path, str]:
    """Stream the upload to a server-chosen temp name (the client filename is never used as a path)."""
    name = safe_basename(file.filename or "")
    ext  = Path(name).suffix.lower()
    if ext not in ALLOWED_DOC_EXTS:
        raise HTTPException(
            400, f"Unsupported file type '{ext or name}'. Supported: {', '.join(sorted(ALLOWED_DOC_EXTS))}")
    save_path = BASE_DIR / "uploads" / f"{uuid.uuid4().hex}{ext}"
    written = 0
    try:
        with open(save_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_DOC_BYTES:
                    raise HTTPException(413, f"File too large (max {MAX_DOC_BYTES // 1024**2} MB)")
                out.write(chunk)
    except BaseException:
        save_path.unlink(missing_ok=True)
        raise
    return save_path, name


def _ingest_and_cleanup(path: str, name: str, event_id: int, category, license, origin):
    try:
        get_service().ingest_file(path, name, category=category, license=license,
                                  origin=origin, event_id=event_id)
    finally:
        Path(path).unlink(missing_ok=True)


@router.post("/sources", status_code=202)
async def upload_source(
    file:     UploadFile  = File(...),
    category: str | None  = Form(None),
    license:  str | None  = Form(None),
    origin:   str | None  = Form(None),
):
    """
    Ingest a PDF, TXT, Markdown, CSV or JSON file in the background.
    Poll GET /jobs/{job_id}; the outcome (including rejection reasons) is persisted in /ingestion-events.
    """
    save_path, name = await _receive_upload(file)
    category, license, origin = ((v or "").strip() or None for v in (category, license, origin))   # blank form fields = not given
    event_id = get_store().begin_event(name)
    asyncio.get_running_loop().run_in_executor(
        _pool, _ingest_and_cleanup, str(save_path), name, event_id, category, license, origin)
    return {
        "status":  "accepted",
        "job_id":  str(event_id),
        "message": f"'{name}' received. Processing in background.",
        "poll":    f"/jobs/{event_id}",
    }


@router.post("/upload-pdf", status_code=202, deprecated=True)
async def upload_pdf(file: UploadFile = File(...)):
    """Deprecated alias kept for the current frontend; use POST /sources."""
    if Path(safe_basename(file.filename or "")).suffix.lower() != ".pdf":
        raise HTTPException(400, "Only .pdf files are supported on this endpoint; use POST /sources")
    return await upload_source(file, None, None, None)


def _job_payload(job_id: str) -> dict:
    store  = get_store()
    totals = store.totals()
    try:
        event = store.get_event(int(job_id))
    except ValueError:
        event = None
    if event is None:
        return {"job_id": job_id, "status": "not_found", "message": "Job not found.",
                "total_chunks": totals["chunks"]}
    # Frontend contract: processing | success | error. Rejections and duplicates are reported as errors.
    status = {"processing": "processing", "success": "success", "unchanged": "success"}.get(event["status"], "error")
    return {
        "job_id":       job_id,
        "status":       status,
        "outcome":      event["status"],
        "message":      event["message"] or "Processing…",
        "error_code":   event["error_code"],
        "source_id":    event["source_id"],
        "version":      event["version"],
        "total_chunks": totals["chunks"],
    }


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    return _job_payload(job_id)


@router.get("/jobs/pdf/{job_id}")
def pdf_job_status(job_id: str):
    return _job_payload(job_id)

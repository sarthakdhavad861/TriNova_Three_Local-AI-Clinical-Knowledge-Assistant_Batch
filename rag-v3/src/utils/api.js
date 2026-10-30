import { REQUEST_TIMEOUT_MS, ERROR_MESSAGES } from './constants.js'
import { createNdjsonParser } from './ndjson.js'

// Empty string = same origin (nginx or the Vite proxy). Optional chaining keeps this module importable under Node tests.
const BASE = (import.meta.env?.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class APIError extends Error {
  constructor(message, status, { retryable = false, code = null } = {}) {
    super(message)
    this.name = 'APIError'; this.status = status; this.retryable = retryable; this.code = code
  }
}

const encHeaders = (enc) => (enc ? { 'X-Encounter-Token': enc.token } : {})

async function fetchWithTimeout(url, opts = {}, ms = REQUEST_TIMEOUT_MS) {
  const timeoutCtrl = new AbortController()
  const tid = setTimeout(() => timeoutCtrl.abort(), ms)
  const { signal: callerSignal, ...rest } = opts
  const onCallerAbort = () => timeoutCtrl.abort()
  callerSignal?.addEventListener('abort', onCallerAbort, { once: true })
  try {
    return await fetch(url, { ...rest, signal: timeoutCtrl.signal })
  } catch (e) {
    if (e.name === 'AbortError') {
      if (callerSignal?.aborted) throw e                                     // user pressed stop
      throw new APIError(ERROR_MESSAGES.TIMEOUT, 408, { retryable: true, code: 'timeout' })
    }
    throw new APIError(ERROR_MESSAGES.NETWORK, 0, { retryable: true, code: 'network' })
  } finally {
    clearTimeout(tid)
    callerSignal?.removeEventListener('abort', onCallerAbort)
  }
}

/** Turn a non-2xx response into an APIError with the most useful message the backend gave. */
async function failure(res, { encounter = false } = {}) {
  let detail = `Server error ${res.status}`
  try {
    const b = await res.json()
    const d = b.detail ?? b.message
    detail = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg ?? JSON.stringify(x)).join('; ') : detail
  } catch { /* not JSON */ }
  if (encounter && res.status === 404) return new APIError(ERROR_MESSAGES.GONE, 404, { code: 'encounter_gone' })
  if (res.status === 503 && /ollama/i.test(detail)) return new APIError(ERROR_MESSAGES.OLLAMA, 503, { code: 'ollama_down' })
  return new APIError(detail, res.status, { retryable: res.status === 429 || res.status >= 500 })
}

async function json(path, { method = 'GET', body, enc, signal, timeout = 30_000, encounter = Boolean(enc) } = {}) {
  const res = await fetchWithTimeout(BASE + path, {
    method, signal,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...encHeaders(enc),
               'X-Request-ID': globalThis.crypto?.randomUUID?.() ?? String(Date.now()) },
    body: body ? JSON.stringify(body) : undefined,
  }, timeout)
  if (!res.ok) throw await failure(res, { encounter })
  if (res.status === 204) return null
  return res.json()
}

// ── backend status ─────────────────────────────────────────────────────────────
/** → { ok, sources, chunks, records } ; never throws. */
export async function checkHealth() {
  try {
    const h = await json('/', { timeout: 5000 })
    const k = h.knowledge ?? {}
    return { ok: true, sources: k.sources ?? 0, chunks: k.chunks ?? h.total_chunks ?? 0, records: k.records ?? 0 }
  } catch { return { ok: false, sources: 0, chunks: 0, records: 0 } }
}

// ── encounters ─────────────────────────────────────────────────────────────────
export async function createEncounter(label = '') {
  const r = await json('/encounters', { method: 'POST', body: { label }, encounter: false })
  return { id: r.encounter_id, token: r.access_token, label: r.label ?? label, createdAt: Date.now() }
}
export const eraseEncounter  = (enc) => json(`/encounters/${enc.id}`, { method: 'DELETE', enc })
export const getMessages     = async (enc) => (await json(`/encounters/${enc.id}/messages?limit=500`, { enc })).messages
export const listContext     = async (enc) => (await json(`/encounters/${enc.id}/context`, { enc })).notes
export const addContext      = (enc, text) => json(`/encounters/${enc.id}/context`, { method: 'POST', body: { text }, enc })
export const deleteContext   = (enc, noteId) => json(`/encounters/${enc.id}/context/${noteId}`, { method: 'DELETE', enc })

// ── questions ──────────────────────────────────────────────────────────────────
/**
 * Ask a question and consume the NDJSON event stream (backend/api/streaming.py).
 * `enc` = { id, token } to ask inside an encounter (private context + history), or omit for a stateless question.
 * onEvent(ev) is called for every event in order; resolves with the final event ({status, text}) or rejects.
 */
export async function askStreaming({ question, model, enc, signal, onEvent }) {
  const res = await fetchWithTimeout(BASE + (enc ? `/encounters/${enc.id}/query` : '/query'), {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson', ...encHeaders(enc),
               'X-Request-ID': globalThis.crypto?.randomUUID?.() ?? String(Date.now()) },
    body: JSON.stringify({ query: question.trim(), ...(model ? { model } : {}) }),
  }, REQUEST_TIMEOUT_MS)
  if (!res.ok) throw await failure(res, { encounter: Boolean(enc) })

  let last = null, failed = null
  const parser = createNdjsonParser((ev) => {
    if (ev.type === 'final') last = ev
    if (ev.type === 'error') failed = ev
    onEvent?.(ev)
  })
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      parser.push(decoder.decode(value, { stream: true }))
    }
    parser.push(decoder.decode())
    parser.end()
  } finally { try { reader.releaseLock() } catch { /* already released */ } }
  if (failed) throw new APIError(failed.message || ERROR_MESSAGES.UNKNOWN, 502, { code: 'stream_error' })
  if (!last) throw new APIError(ERROR_MESSAGES.BAD_EVENT, 502, { code: 'no_final' })
  return last
}

// ── knowledge base ─────────────────────────────────────────────────────────────
export const listKnowledge = () => json('/sources')
export async function getChunk(path) {                       // path from source.fullTextPath, e.g. /chunks/<id>
  return json(path)
}
export async function uploadSource({ file, category, license, origin }) {
  const form = new FormData()
  form.append('file', file)
  if (category) form.append('category', category)
  form.append('license', license.trim())
  form.append('origin', origin.trim())
  const res = await fetchWithTimeout(BASE + '/sources', { method: 'POST', body: form }, 120_000)
  if (!res.ok) throw await failure(res)
  return res.json()                                         // { job_id, ... }
}
export const jobStatus = (jobId) => json(`/jobs/${encodeURIComponent(jobId)}`)

/** Poll an ingestion job until it finishes. Resolves with the job; rejects with the persisted rejection reason. */
export async function waitForJob(jobId, { intervalMs = 1500, maxPolls = 200, signal, onProgress, sleep } = {}) {
  const wait = sleep ?? ((ms) => new Promise((res, rej) => {
    const t = setTimeout(res, ms)
    signal?.addEventListener('abort', () => { clearTimeout(t); rej(Object.assign(new Error('Aborted'), { name: 'AbortError' })) }, { once: true })
  }))
  for (let i = 0; i < maxPolls; i++) {
    const job = await jobStatus(jobId)
    if (job.status === 'success') return job
    if (job.status === 'error' || job.status === 'not_found')
      throw new APIError(job.message || 'Ingestion failed', 422, { code: job.error_code ?? job.status })
    onProgress?.(job)
    await wait(intervalMs)
  }
  throw new APIError('Processing timed out — check the backend log.', 408, { code: 'timeout' })
}

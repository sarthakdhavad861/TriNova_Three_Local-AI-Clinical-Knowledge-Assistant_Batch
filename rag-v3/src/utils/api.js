import {
  REQUEST_TIMEOUT_MS, CACHE_TTL_MS,
  ACCEPTED_VIDEO_TYPES, ACCEPTED_VIDEO_MIME,
  ACCEPTED_PDF_TYPES, ACCEPTED_PDF_MIME,
  MAX_UPLOAD_BYTES, ERROR_MESSAGES,
} from './constants.js'

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export class APIError extends Error {
  constructor(message, status, retryable = false) {
    super(message)
    this.name = 'APIError'; this.status = status; this.retryable = retryable
  }
}

// Request deduplication
const INFLIGHT = new Map()

// LRU Cache
const CACHE = new Map()
const MAX_CACHE = 80

function cacheKey(question, model = '') { return model + '::' + question.trim().toLowerCase() }

function cacheGet(k) {
  const e = CACHE.get(k)
  if (!e) return null
  if (Date.now() - e.ts > CACHE_TTL_MS) { CACHE.delete(k); return null }
  CACHE.delete(k); CACHE.set(k, e)
  return e.v
}

function cacheSet(k, v) {
  if (CACHE.size >= MAX_CACHE) CACHE.delete(CACHE.keys().next().value)
  CACHE.set(k, { v, ts: Date.now() })
}

export function clearCache() { CACHE.clear() }

async function fetchWithTimeout(url, opts = {}, ms = REQUEST_TIMEOUT_MS) {
  const timeoutCtrl = new AbortController()
  const tid = setTimeout(() => timeoutCtrl.abort(), ms)
  const { signal: callerSignal, ...rest } = opts
  try {
    const res = await fetch(url, { ...rest, signal: timeoutCtrl.signal })
    if (callerSignal?.aborted) { const e = new Error('Aborted'); e.name = 'AbortError'; throw e }
    return res
  } catch (e) {
    if (e.name === 'AbortError') {
      if (timeoutCtrl.signal.aborted && !callerSignal?.aborted)
        throw new APIError(ERROR_MESSAGES.TIMEOUT, 408, true)
      throw e
    }
    throw e
  } finally { clearTimeout(tid) }
}

async function withRetry(fn, tries = 3, delay = 700) {
  let last
  for (let i = 0; i < tries; i++) {
    try { return await fn() }
    catch (e) {
      last = e
      if (e.name === 'AbortError') throw e
      if (e instanceof APIError && !e.retryable) throw e
      if (i < tries - 1) await new Promise(r => setTimeout(r, delay * 2 ** i))
    }
  }
  throw last
}

async function safeJson(res) {
  const ct = res.headers.get('content-type') ?? ''
  if (!ct.includes('application/json')) {
    const text = await res.text()
    throw new APIError('Unexpected response: ' + text.slice(0, 120), res.status, false)
  }
  return res.json()
}

function detectType(raw) {
  if (raw.type)        return raw.type
  if (raw.source_type) return raw.source_type
  const url = raw.url ?? raw.source_url ?? ''
  if (url.includes('youtube') || url.includes('youtu.be')) return 'video'
  if (url.match(/\.(pdf)$/i))                               return 'pdf'
  if (url.match(/\.(mp4|mkv|mov|avi|webm)$/i))             return 'video'
  if (url.startsWith('http'))                               return 'web'
  const start = parseFloat(raw.start ?? raw.Start ?? 0)
  if (start > 0) return 'video'
  return 'document'
}

export function normaliseSource(raw, i) {
  const type        = detectType(raw)
  const srcType     = raw.source_type ?? type
  const rawTitle    = raw.title ?? raw.Title ?? 'Unknown Source'
  const number      = raw.number ?? '?'
  const start       = parseFloat(raw.start ?? raw.Start ?? 0)
  const end         = parseFloat(raw.end ?? 0)
  const score       = typeof raw.score === 'number' ? raw.score : 0

  // Build display title per modality
  let title
  if (srcType === 'pdf') {
    const fn   = raw.filename ?? rawTitle
    const page = raw.page_number ?? '?'
    title = `PDF: ${fn} — p.${page}`
  } else if (srcType === 'web') {
    title = `Web: ${rawTitle}`
  } else {
    title = number !== '?' ? `Video ${number} \u2014 ${rawTitle}` : rawTitle
  }

  return {
    id:          raw.id ?? raw.chunk_id ?? ('src-' + i + '-' + Date.now()),
    title,
    score,
    excerpt:     (raw.text ?? raw.excerpt ?? '').trim(),
    type:        srcType,
    sourceUrl:   raw.url ?? raw.source_url ?? null,
    _start:      start,
    _end:        end,
    _number:     number,
    _rawTitle:   rawTitle,
    _page:       raw.page_number ?? null,
    _filename:   raw.filename ?? null,
  }
}

export function normaliseVideo(rawVideo, sources) {
  const videoSources = sources.filter(s => s.type === 'video')
  if (!rawVideo && videoSources.length === 0) return null
  if (rawVideo) {
    return {
      url: rawVideo.url ?? null,
      title: rawVideo.title ?? (rawVideo.number ? 'Video ' + rawVideo.number : 'Video'),
      timestamps: (rawVideo.timestamps ?? []).map(ts => ({
        time:  typeof ts.time === 'number' ? Math.floor(ts.time) : 0,
        label: String(ts.label ?? '').slice(0, 80),
      })),
    }
  }
  const top = videoSources[0] ?? sources[0]
  return {
    url: top.sourceUrl ?? null, title: top.title,
    timestamps: videoSources.slice(0, 5).map(s => ({
      time:  Math.floor(s._start),
      label: s.excerpt.slice(0, 70) + (s.excerpt.length > 70 ? '\u2026' : ''),
    })),
  }
}

export async function checkHealth() {
  try { return (await fetchWithTimeout(BASE + '/', {}, 5000)).ok }
  catch { return false }
}

// v2: Upload PDF file
export async function uploadPdf(file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetchWithTimeout(
    `${BASE}/upload-pdf`,
    { method: 'POST', body: form },
    120_000,
  )
  if (!res.ok) {
    let msg = `Server error ${res.status}`
    try { const b = await res.json(); msg = b.detail ?? b.message ?? msg } catch {}
    throw new APIError(msg, res.status, false)
  }
  return res.json()
}

// existing video upload — unchanged
export async function uploadVideo(file, onProgress) {
  const form = new FormData()
  form.append('file', file)

  // Use XMLHttpRequest for upload progress
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/upload-video`)
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) onProgress?.(Math.round(e.loaded / e.total * 100))
    })
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) }
        catch { resolve({}) }
      } else {
        let msg = `Upload failed: ${xhr.status}`
        try { msg = JSON.parse(xhr.responseText).detail ?? msg } catch {}
        reject(new APIError(msg, xhr.status, false))
      }
    }
    xhr.onerror  = () => reject(new APIError(ERROR_MESSAGES.NETWORK, 0, true))
    xhr.ontimeout= () => reject(new APIError(ERROR_MESSAGES.TIMEOUT, 408, true))
    xhr.send(form)
  })
}

export async function askQuestionStreaming({
  question, model = 'llama3.1', signal,
  onChunk, onComplete, onSourcesReady,
}) {
  const res = await fetchWithTimeout(`${BASE}/query`, {
    method:  'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': crypto.randomUUID?.() ?? String(Date.now()),
    },
    body:    JSON.stringify({ query: question.trim(), model }),
    signal,
  }, REQUEST_TIMEOUT_MS)

  if (!res.ok) {
    const retryable = res.status === 429 || res.status >= 500
    let msg = `Server error ${res.status}`
    try { const b = await res.json(); msg = b.detail ?? b.message ?? msg } catch {}
    throw new APIError(msg, res.status, retryable)
  }

  // Parse local sources (video + pdf) from X-Sources header
  let ragSources = [], video = null
  try {
    const srcHeader = res.headers.get('X-Sources')
    if (srcHeader) {
      const raw = JSON.parse(srcHeader)
      ragSources = raw.map(normaliseSource)
    }
  } catch {}

  try {
    const vidHeader = res.headers.get('X-Video')
    if (vidHeader) {
      const rawVid = JSON.parse(vidHeader)
      video = normaliseVideo(rawVid, ragSources)
    }
  } catch {}

  // v2: parse web sources from X-Web-Sources header
  let webSources = []
  try {
    const webHeader = res.headers.get('X-Web-Sources')
    if (webHeader) {
      const raw = JSON.parse(webHeader)
      webSources = raw.map((w, i) => normaliseSource(w, i + 1000))
    }
  } catch {}

  // v2: parse intent from X-Intent header
  let intent = 'video'
  try {
    intent = res.headers.get('X-Intent') ?? 'video'
  } catch {}

  const modelUsed = res.headers.get('X-Model') ?? null

  // Fire onSourcesReady with all source types
  if (ragSources.length > 0 || video || webSources.length > 0) {
    onSourcesReady?.(ragSources, video, modelUsed, webSources, intent)
  }

  // Stream body tokens
  const reader  = res.body.getReader()
  const decoder = new TextDecoder()
  let fullText  = ''

  try {
    while (true) {
      if (signal?.aborted) break
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      fullText += chunk
      onChunk?.(chunk, fullText)
    }
  } catch (e) {
    if (e.name !== 'AbortError') throw e
  } finally {
    reader.releaseLock()
  }

  const result = { answer: fullText, ragSources, video, webSources, intent, modelUsed }
  onComplete?.(result)
  return result
}

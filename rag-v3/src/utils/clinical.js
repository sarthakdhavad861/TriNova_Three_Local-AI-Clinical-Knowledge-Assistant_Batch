// Pure helpers (no React, no DOM): building UI messages from backend events/stored messages, and input validation.
import {
  MAX_INPUT_CHARS, MAX_NOTE_CHARS, MAX_LABEL_CHARS, MAX_LICENSE_CHARS, MAX_ORIGIN_CHARS, MAX_UPLOAD_BYTES, ACCEPTED_DOC_TYPES, CATEGORIES,
} from './constants.js'

export function normaliseSource(raw = {}, i = 0) {
  const label = raw.label ?? raw.title ?? raw.filename ?? 'Unknown source'
  return {
    id:        raw.id ?? raw.chunk_id ?? `src-${i}`,
    chunkId:   raw.chunk_id ?? raw.id ?? null,
    ref:       raw.ref ?? raw.number ?? String(i + 1),
    title:     label,
    sourceId:  raw.source_id ?? null,
    version:   raw.version ?? null,
    page:      raw.page_number || raw.page || null,
    section:   raw.section || '',
    score:     typeof raw.score === 'number' ? raw.score : 0,
    excerpt:   (raw.text ?? raw.excerpt ?? '').trim(),
    fullTextPath: raw.full_text_url ?? (raw.chunk_id ?? raw.id ? `/chunks/${raw.chunk_id ?? raw.id}` : null),
  }
}

export function emptyAssistant(id, timestamp = Date.now()) {
  return {
    id, role: 'assistant', content: '', timestamp, isStreaming: true, error: null,
    status: null, workflow: null, notices: [], recordCards: [], recordViews: [], disclaimer: '', urgentFlags: [],
    patientSpecific: false, verification: null, sources: [], modelUsed: null,
  }
}

/** Apply one backend event (see backend/api/streaming.py) to an assistant message; returns a new object. */
export function applyEvent(msg, ev) {
  switch (ev?.type) {
    case 'meta':
      return { ...msg, workflow: ev.workflow ?? msg.workflow, modelUsed: ev.model ?? msg.modelUsed,
               urgentFlags: ev.urgent_flags ?? [], patientSpecific: Boolean(ev.patient_specific),
               sources: (ev.sources ?? []).map(normaliseSource) }
    case 'notices':      return { ...msg, notices: ev.items ?? [] }
    case 'records':      return { ...msg, recordCards: ev.items ?? [], disclaimer: ev.disclaimer ?? '',
                          recordViews: ev.views?.length ? ev.views : (ev.items ?? []).map(parseRecordCard) }
    case 'token':        return { ...msg, content: msg.content + (ev.text ?? '') }
    case 'verification': return { ...msg, verification: { ok: Boolean(ev.ok), issues: ev.issues ?? [], text: ev.text ?? '' } }
    case 'final':        return { ...msg, content: ev.text ?? msg.content, status: ev.status ?? msg.status, isStreaming: false }
    case 'error':        return { ...msg, error: ev.message || 'Error', isStreaming: false }
    default:             return msg
  }
}

export const RECORD_DISCLAIMER_FALLBACK = 'Reference information copied from the knowledge base — not a prescription or a diagnosis. Verify against the primary label / manual before clinical use.'

/** Backend stored message ({message_id, role, content, meta, created_at}) → UI message. */
export function fromStored(m) {
  const base = { id: `m${m.message_id}`, role: m.role, content: m.content, timestamp: (m.created_at ?? 0) * 1000 }
  if (m.role !== 'assistant') return base
  const meta = m.meta ?? {}
  return {
    ...emptyAssistant(base.id, base.timestamp), content: m.content, isStreaming: false,
    status: meta.status ?? null, workflow: meta.workflow ?? null, notices: meta.notices ?? [],
    recordCards: meta.record_cards ?? [],
    recordViews: meta.record_views?.length ? meta.record_views : (meta.record_cards ?? []).map(parseRecordCard), urgentFlags: meta.urgent_flags ?? [], patientSpecific: Boolean(meta.patient_specific),
    verification: meta.issues?.length ? { ok: meta.status !== 'unverified', issues: meta.issues, text: '' } : null,
    sources: (meta.sources ?? []).map(normaliseSource),
  }
}

// ── validation (mirrors backend limits; the backend re-validates everything) ──
export function validateQuestion(text) {
  const t = (text ?? '').trim()
  if (!t) return 'Type a question first.'
  if (t.length > MAX_INPUT_CHARS) return `Question is too long (${t.length}/${MAX_INPUT_CHARS} characters).`
  return null
}
export function validateNote(text) {
  const t = (text ?? '').trim()
  if (!t) return 'Note is empty.'
  if (t.length > MAX_NOTE_CHARS) return `Note is too long (${t.length}/${MAX_NOTE_CHARS} characters).`
  return null
}
export function validateLabel(text) {
  return (text ?? '').trim().length > MAX_LABEL_CHARS ? `Label is limited to ${MAX_LABEL_CHARS} characters.` : null
}
/** Reference-document upload: provenance (licence + origin) is mandatory in the UI. */
export function validateUpload({ file, category = '', license = '', origin = '' }) {
  if (!file) return 'Choose a file.'
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (!ACCEPTED_DOC_TYPES.includes(ext)) return `Unsupported file type "${ext || file.name}". Accepted: ${ACCEPTED_DOC_TYPES.join(', ')}`
  if (file.size > MAX_UPLOAD_BYTES) return `File is larger than ${Math.round(MAX_UPLOAD_BYTES / 1024 ** 2)} MB.`
  if (file.size === 0) return 'File is empty.'
  if (!CATEGORIES.some(c => c.id === category)) return 'Unknown category.'
  if (!license.trim()) return 'Licence is required (e.g. "CC BY 4.0", "public domain", "own work").'
  if (!origin.trim()) return 'Origin is required (URL or description of where the document came from).'
  if (license.trim().length > MAX_LICENSE_CHARS) return `Licence is limited to ${MAX_LICENSE_CHARS} characters.`
  if (origin.trim().length > MAX_ORIGIN_CHARS) return `Origin is limited to ${MAX_ORIGIN_CHARS} characters.`
  return null
}

/** Short sentence for the clinician about how far an answer can be trusted. */
export function trustLine(msg) {
  if (msg.error) return null
  switch (msg.status) {
    case 'answered':              return 'Answer checked against the cited sources (numbers and citation ids). The check cannot prove clinical correctness — verify against the source.'
    case 'unverified':            return 'The automatic evidence check FAILED. Do not rely on this answer without reading the sources.'
    case 'insufficient_evidence': return 'The knowledge base has nothing reliable on this. No answer was generated.'
    case 'records_only':          return 'Shown directly from a structured record; no narrative source matched, so no summary was generated.'
    default:                      return null
  }
}

/**
 * Parse a verbatim record card produced by backend knowledge/clinical.render_record() into display parts.
 * Values are kept EXACTLY as sent (never trimmed inside, converted or reformatted).
 */
export function parseRecordCard(text = '') {
  const lines = String(text).split('\n')
  const head = /^\*\*(.+)\*\* — (\S+) record$/.exec(lines[0] ?? '')
  const card = { name: head ? head[1] : (lines[0] ?? ''), category: head ? head[2] : '', source: '', rows: [] }
  let i = 1
  if ((lines[1] ?? '').startsWith('Source: ')) { card.source = lines[1].slice(8); i = 2 }
  for (; i < lines.length; i++) {
    const m = /^(⚠ )?([^:\n]{1,80}): ?(.*)$/.exec(lines[i])
    if (m) card.rows.push({ warning: Boolean(m[1]), key: m[2], value: m[3] })
    else if (card.rows.length) card.rows[card.rows.length - 1].value += '\n' + lines[i]      // continuation of a multi-line value
  }
  for (const r of card.rows) r.not_stated = r.value.startsWith('Not stated in this record')
  return card
}

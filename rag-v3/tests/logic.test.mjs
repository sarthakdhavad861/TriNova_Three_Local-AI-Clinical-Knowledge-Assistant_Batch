// Phase 6 frontend logic tests — plain Node (node --test tests/), no npm install needed.
// Covers the NON-React logic: NDJSON parsing, the streaming client against a fake fetch, event→message reduction,
// validation, and the encounter store. It does NOT test rendering, styling or a real browser.
import test from 'node:test'
import assert from 'node:assert/strict'

import { createNdjsonParser } from '../src/utils/ndjson.js'
import {
  askStreaming, createEncounter, getMessages, eraseEncounter, uploadSource, waitForJob, checkHealth, APIError,
} from '../src/utils/api.js'
import { parseRecordCard, applyEvent, emptyAssistant, fromStored, validateQuestion, validateNote, validateUpload, validateLabel, trustLine }
  from '../src/utils/clinical.js'
import { loadEncounters, saveEncounters, addEncounter, removeEncounter } from '../src/utils/encounterStore.js'

// ── helpers ───────────────────────────────────────────────────────────────────
const enc = new TextEncoder()
function streamOf(str, sizes = [7]) {                       // split BYTES at arbitrary positions (also inside characters)
  const bytes = enc.encode(str); const chunks = []
  for (let i = 0, k = 0; i < bytes.length; k++) { const n = sizes[k % sizes.length]; chunks.push(bytes.slice(i, i + n)); i += n }
  return new ReadableStream({ start(c) { chunks.forEach(x => c.enqueue(x)); c.close() } })
}
const lines = (...evs) => evs.map(e => JSON.stringify(e)).join('\n') + '\n'
const GOOD = lines(
  { type: 'meta', workflow: 'medicine', model: 'llama3.1:latest', urgent_flags: ['chest_pain'], patient_specific: true,
    sources: [{ id: 'c1', chunk_id: 'fict:v1:0', ref: 'S1', label: 'fict.md, v1', source_id: 'fict-md', version: 1, text: 'excerpt…', score: 0.9, full_text_url: '/chunks/fict:v1:0' }] },
  { type: 'notices', items: ['🚨 URGENT-SYMPTOM KEYWORDS DETECTED: chest pain'] },
  { type: 'records', items: ['**Fictitrol** — medicine record\nDose: 25 mg µg ≥ 30'], disclaimer: 'Not a prescription.',
    views: [{ name: 'Fictitrol', category: 'medicine', source: 'meds.csv', rows: [{ key: 'Dose', value: '25 mg µg ≥ 30', warning: false, not_stated: false }] }] },
  { type: 'token', text: 'Max is 100 mg ' }, { type: 'token', text: 'per day [S1].\nNext ✓' },
  { type: 'verification', ok: false, issues: ['“999 mg” is not in the cited source(s)'], text: '---' },
  { type: 'final', status: 'unverified', text: 'Max is 100 mg per day [S1].\nNext ✓' },
)
const okResponse = (body, status = 200) => ({ ok: status < 400, status, headers: new Headers(), body, json: async () => JSON.parse(body) })
function fakeFetch(handler) {
  const calls = []
  globalThis.fetch = async (url, opts = {}) => { calls.push({ url, opts }); return handler(url, opts, calls.length) }
  return calls
}
const jsonRes = (obj, status = 200) => ({ ok: status < 400, status, headers: new Headers({ 'content-type': 'application/json' }),
  json: async () => obj, body: null })

// ── NDJSON parser ─────────────────────────────────────────────────────────────
test('ndjson: lines split anywhere, blank lines ignored, tail flushed on end()', () => {
  const got = []; const p = createNdjsonParser(e => got.push(e))
  const text = '{"a":1}\n\n{"b":"x\\ny"}\n{"c":3}'
  for (const ch of text) p.push(ch)                         // worst case: one character at a time
  assert.deepEqual(got, [{ a: 1 }, { b: 'x\ny' }]); p.end()
  assert.deepEqual(got.at(-1), { c: 3 })
})
test('ndjson: a malformed line becomes an error event, later lines still parse', () => {
  const got = []; const p = createNdjsonParser(e => got.push(e))
  p.push('{bad\n{"ok":true}\n'); p.end()
  assert.equal(got[0].type, 'error'); assert.equal(got[0].malformed, true); assert.deepEqual(got[1], { ok: true })
})

// ── streaming client ──────────────────────────────────────────────────────────
test('askStreaming: events in order, bytes split inside multibyte characters, returns the final event', async () => {
  const calls = fakeFetch(() => okResponse(streamOf(GOOD, [5, 3, 11])))
  const seen = []
  const final = await askStreaming({ question: ' dose? ', model: 'llama', onEvent: e => seen.push(e.type) })
  assert.deepEqual(seen, ['meta', 'notices', 'records', 'token', 'token', 'verification', 'final'])
  assert.equal(final.status, 'unverified'); assert.match(final.text, /Next ✓$/)
  assert.equal(calls[0].url, '/query'); assert.equal(calls[0].opts.headers.Accept, 'application/x-ndjson')
  assert.deepEqual(JSON.parse(calls[0].opts.body), { query: 'dose?', model: 'llama' })
  assert.equal(calls[0].opts.headers['X-Encounter-Token'], undefined)
})
test('askStreaming: inside an encounter the token travels in a header, never in the URL or body', async () => {
  const calls = fakeFetch(() => okResponse(streamOf(GOOD)))
  await askStreaming({ question: 'q', enc: { id: 'e'.repeat(32), token: 'SECRET-TOKEN' } })
  assert.equal(calls[0].url, `/encounters/${'e'.repeat(32)}/query`)
  assert.equal(calls[0].opts.headers['X-Encounter-Token'], 'SECRET-TOKEN')
  assert.ok(!calls[0].url.includes('SECRET')); assert.ok(!calls[0].opts.body.includes('SECRET'))
})
test('askStreaming: error event rejects; stream without final rejects; HTTP errors are mapped', async () => {
  fakeFetch(() => okResponse(streamOf(lines({ type: 'token', text: 'a' }, { type: 'error', message: 'model unavailable' }))))
  await assert.rejects(askStreaming({ question: 'q' }), e => e instanceof APIError && /model unavailable/.test(e.message))
  fakeFetch(() => okResponse(streamOf(lines({ type: 'token', text: 'a' }))))
  await assert.rejects(askStreaming({ question: 'q' }), e => e.code === 'no_final')
  fakeFetch(() => jsonRes({ detail: 'Encounter not found' }, 404))
  await assert.rejects(askStreaming({ question: 'q', enc: { id: 'x', token: 't' } }), e => e.code === 'encounter_gone')
  fakeFetch(() => jsonRes({ detail: 'Ollama is not running or unreachable.' }, 503))
  await assert.rejects(askStreaming({ question: 'q' }), e => e.code === 'ollama_down')
  fakeFetch(() => jsonRes({ detail: [{ msg: 'String should have at most 4000 characters' }] }, 422))
  await assert.rejects(askStreaming({ question: 'q' }), e => /at most 4000/.test(e.message))
})
test('askStreaming: network failure → APIError(network); user abort → AbortError (not a timeout)', async () => {
  fakeFetch(() => { throw new TypeError('fetch failed') })
  await assert.rejects(askStreaming({ question: 'q' }), e => e.code === 'network' && e.retryable)
  globalThis.fetch = (url, { signal }) => new Promise((_, rej) => signal.addEventListener('abort', () => rej(Object.assign(new Error('x'), { name: 'AbortError' }))))
  const ctrl = new AbortController(); const p = askStreaming({ question: 'q', signal: ctrl.signal }); ctrl.abort()
  await assert.rejects(p, e => e.name === 'AbortError')
})

// ── other API calls ───────────────────────────────────────────────────────────
test('encounter calls: create/messages/erase use the right paths, headers and error mapping', async () => {
  const calls = fakeFetch((url, o) => {
    if (url === '/encounters') return jsonRes({ encounter_id: 'a'.repeat(32), access_token: 'TOK', label: 'synthetic' }, 201)
    if (url.endsWith('/messages?limit=500')) return jsonRes({ messages: [{ message_id: 1, role: 'user', content: 'hi', meta: {}, created_at: 1 }] })
    return { ok: true, status: 204, headers: new Headers(), json: async () => { throw new Error('no body') } }
  })
  const e = await createEncounter('synthetic')
  assert.deepEqual([e.id, e.token], ['a'.repeat(32), 'TOK'])
  assert.deepEqual(JSON.parse(calls[0].opts.body), { label: 'synthetic' })
  assert.equal((await getMessages(e))[0].content, 'hi')
  assert.equal(calls[1].opts.headers['X-Encounter-Token'], 'TOK')
  assert.equal(await eraseEncounter(e), null); assert.equal(calls[2].opts.method, 'DELETE')
  fakeFetch(() => jsonRes({ detail: 'Encounter not found' }, 404))
  await assert.rejects(getMessages(e), x => x.code === 'encounter_gone')
})
test('checkHealth never throws and reports counts', async () => {
  fakeFetch(() => jsonRes({ status: 'ok', knowledge: { sources: 2, chunks: 9, records: 4 } }))
  assert.deepEqual(await checkHealth(), { ok: true, sources: 2, chunks: 9, records: 4 })
  fakeFetch(() => { throw new Error('down') })
  assert.equal((await checkHealth()).ok, false)
})
test('uploadSource sends provenance fields; waitForJob resolves on success and surfaces rejection reasons', async () => {
  const calls = fakeFetch(() => jsonRes({ job_id: '7' }, 202))
  const f = new File(['name,dose\nA,1 mg\n'], 'm.csv', { type: 'text/csv' })
  await uploadSource({ file: f, category: 'medicine', license: ' CC0 ', origin: ' synthetic ' })
  const form = calls[0].opts.body
  assert.deepEqual([form.get('category'), form.get('license'), form.get('origin')], ['medicine', 'CC0', 'synthetic'])
  let n = 0; const progress = []
  fakeFetch(() => jsonRes(++n < 3 ? { status: 'processing', message: 'Embedding…' } : { status: 'success', message: 'done' }))
  assert.equal((await waitForJob('7', { sleep: async () => {}, onProgress: j => progress.push(j.message) })).status, 'success')
  assert.deepEqual(progress, ['Embedding…', 'Embedding…'])
  fakeFetch(() => jsonRes({ status: 'error', message: 'No name column found', error_code: 'no_name_column' }))
  await assert.rejects(waitForJob('8', { sleep: async () => {} }), e => e.code === 'no_name_column' && /No name column/.test(e.message))
  fakeFetch(() => jsonRes({ status: 'processing' }))
  await assert.rejects(waitForJob('9', { sleep: async () => {}, maxPolls: 3 }), e => e.code === 'timeout')
})

// ── event reduction ───────────────────────────────────────────────────────────
test('applyEvent builds the clinical message exactly as the stream describes it', () => {
  let m = emptyAssistant('a1')
  createNdjsonParser(ev => { m = applyEvent(m, ev) }).push(GOOD)
  assert.equal(m.workflow, 'medicine'); assert.deepEqual(m.urgentFlags, ['chest_pain']); assert.equal(m.patientSpecific, true)
  assert.equal(m.recordCards[0].split('\n')[0], '**Fictitrol** — medicine record'); assert.match(m.recordCards[0], /µg ≥ 30/)
  assert.equal(m.recordViews[0].rows[0].value, '25 mg µg ≥ 30')
  const legacy = applyEvent(emptyAssistant('x'), { type: 'records', items: ['**A** — equipment record\nSource: s\n⚠ Warnings / precautions: Not stated in this record'], disclaimer: 'd' })
  assert.equal(legacy.recordViews[0].rows[0].warning, true); assert.equal(legacy.recordViews[0].rows[0].not_stated, true)
  assert.equal(m.notices.length, 1); assert.equal(m.content, 'Max is 100 mg per day [S1].\nNext ✓')
  assert.equal(m.status, 'unverified'); assert.equal(m.isStreaming, false); assert.equal(m.verification.ok, false)
  assert.equal(m.sources[0].ref, 'S1'); assert.equal(m.sources[0].fullTextPath, '/chunks/fict:v1:0'); assert.equal(m.sources[0].version, 1)
  assert.equal(trustLine(m).startsWith('The automatic evidence check FAILED'), true)
})
test('applyEvent: tokens accumulate while streaming (before any final event) and the record disclaimer is kept', () => {
  let m = emptyAssistant('s1')
  for (const t of ['Max ', 'is 100', ' mg']) m = applyEvent(m, { type: 'token', text: t })
  assert.equal(m.content, 'Max is 100 mg'); assert.equal(m.isStreaming, true)
  m = applyEvent(m, { type: 'records', items: [], views: [{ name: 'A', category: 'medicine', source: 's', rows: [] }], disclaimer: 'Not a prescription.' })
  assert.equal(m.disclaimer, 'Not a prescription.'); assert.equal(m.content, 'Max is 100 mg')
})
test('applyEvent: unknown events are ignored; error ends streaming; objects are not mutated', () => {
  const m = emptyAssistant('a2'); const before = JSON.stringify(m)
  assert.equal(applyEvent(m, { type: 'future-thing' }), m)
  const e = applyEvent(m, { type: 'error', message: 'boom' })
  assert.equal(e.error, 'boom'); assert.equal(e.isStreaming, false); assert.equal(JSON.stringify(m), before)
  assert.equal(trustLine(e), null)
})
test('fromStored restores a stored assistant turn with notices, cards, sources and issues', () => {
  const m = fromStored({ message_id: 5, role: 'assistant', content: 'Text [S1].', created_at: 100, meta: {
    status: 'unverified', workflow: 'medicine', notices: ['n'], record_cards: ['card'], urgent_flags: ['breathing'], issues: ['bad'],
    sources: [{ ref: 'S1', source_id: 's', version: 2, chunk_id: 's:v2:0', label: 'x, v2', score: 0.5, page: 3, section: '' }] } })
  assert.deepEqual([m.id, m.status, m.recordCards, m.urgentFlags, m.verification.issues], ['m5', 'unverified', ['card'], ['breathing'], ['bad']])
  assert.equal(m.recordViews[0].name, 'card')
  assert.equal(m.sources[0].page, 3); assert.equal(m.sources[0].fullTextPath, '/chunks/s:v2:0'); assert.equal(m.timestamp, 100000)
  assert.equal(fromStored({ message_id: 6, role: 'user', content: 'q', created_at: 1 }).role, 'user')
})

// ── validation ────────────────────────────────────────────────────────────────
test('validation mirrors backend limits', () => {
  assert.ok(validateQuestion('   ')); assert.ok(validateQuestion('x'.repeat(4001))); assert.equal(validateQuestion('ok'), null)
  assert.ok(validateNote('')); assert.ok(validateNote('x'.repeat(2001))); assert.equal(validateNote('x'.repeat(2000)), null)
  assert.ok(validateLabel('x'.repeat(81))); assert.equal(validateLabel('x'.repeat(80)), null)
  const f = (name, size = 10) => ({ name, size })
  const base = { category: '', license: 'CC0', origin: 'synthetic' }
  assert.equal(validateUpload({ ...base, file: f('a.csv') }), null)
  assert.match(validateUpload({ ...base, file: f('a.mp4') }), /Unsupported/)
  assert.match(validateUpload({ ...base, file: f('noext') }), /Unsupported/)
  assert.match(validateUpload({ ...base, file: f('a.pdf', 60 * 1024 ** 2) }), /larger/)
  assert.match(validateUpload({ ...base, file: f('a.pdf', 0) }), /empty/)
  assert.match(validateUpload({ ...base, file: f('a.pdf'), license: '  ' }), /Licence/)
  assert.match(validateUpload({ ...base, file: f('a.pdf'), origin: '' }), /Origin/)
  assert.match(validateUpload({ ...base, file: f('a.pdf'), category: 'x' }), /category/)
  assert.match(validateUpload({ ...base, file: f('a.pdf'), license: 'L'.repeat(301) }), /Licence is limited/)
  assert.match(validateUpload({ ...base, file: f('a.pdf'), origin: 'O'.repeat(1001) }), /Origin is limited/)
  assert.equal(validateUpload({ ...base, file: f('a.pdf'), license: 'L'.repeat(300), origin: 'O'.repeat(1000) }), null)
  assert.ok(validateUpload({ ...base, file: null }))
})

// ── encounter store ───────────────────────────────────────────────────────────
const memStore = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), raw: m } }
test('encounterStore persists ids/tokens/labels only and tolerates corrupt or hostile data', () => {
  const s = memStore()
  const list = addEncounter([], { id: 'a', token: 't', label: 'L', createdAt: 5, messages: ['PATIENT TEXT'], notes: ['N'] })
  saveEncounters(list, s)
  const raw = [...s.raw.values()][0]
  assert.ok(!raw.includes('PATIENT TEXT') && !raw.includes('"notes"'))
  assert.deepEqual(loadEncounters(s), [{ id: 'a', token: 't', label: 'L', createdAt: 5 }])
  s.setItem('rag_encounters_v1', '{not json'); assert.deepEqual(loadEncounters(s), [])
  s.setItem('rag_encounters_v1', JSON.stringify([{ id: 1 }, null, 'x', { id: 'ok', token: 'tt' }]))
  assert.deepEqual(loadEncounters(s).map(e => e.id), ['ok'])
  assert.deepEqual(removeEncounter(addEncounter(addEncounter([], { id: 'a', token: 't' }), { id: 'b', token: 'u' }), 'a').map(e => e.id), ['b'])
  assert.deepEqual(loadEncounters(null), [])
  assert.doesNotThrow(() => saveEncounters([], { setItem() { throw new Error('quota') } }))
})

test('parseRecordCard keeps values verbatim, flags warnings and absent data, joins multi-line values', () => {
  const c = parseRecordCard('**Fictitrol** — medicine record\nSource: meds.csv (v1, row 2) · licence: CC0\n⚠ Contraindications: eGFR < 30 mL/min/1.73m2\n⚠ Warnings / precautions: Not stated in this record\nDose: Maximum 100 mg per day\nNotes: line one\nline two: with colon\nBlank: Not stated in this record (blank in source)')
  assert.deepEqual([c.name, c.category, c.source], ['Fictitrol', 'medicine', 'meds.csv (v1, row 2) · licence: CC0'])
  const by = Object.fromEntries(c.rows.map(r => [r.key, r]))
  assert.equal(by['Contraindications'].value, 'eGFR < 30 mL/min/1.73m2'); assert.equal(by['Contraindications'].warning, true)
  assert.equal(by['Warnings / precautions'].not_stated, true)
  assert.equal(by['Dose'].value, 'Maximum 100 mg per day'); assert.equal(by['Dose'].warning, false)
  assert.equal(by['Notes'].value, 'line one'); assert.equal(by['line two'].value, 'with colon')   // documented limitation: a continuation line that itself looks like "key: value" becomes its own row
  assert.equal(by['Blank'].not_stated, true)
  assert.deepEqual(parseRecordCard('weird').rows, [])
})

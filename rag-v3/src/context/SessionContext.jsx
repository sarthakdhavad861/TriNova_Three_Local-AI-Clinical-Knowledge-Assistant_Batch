import React, { createContext, useContext, useCallback, useEffect, useRef, useMemo, useState } from 'react'
import { useLocalStorage } from '../hooks/useLocalStorage.js'
import { useUI } from './UIContext.jsx'
import {
  askStreaming, checkHealth, createEncounter, eraseEncounter, getMessages, listContext, addContext, deleteContext,
  listKnowledge, uploadSource, waitForJob, APIError,
} from '../utils/api.js'
import { applyEvent, emptyAssistant, fromStored, validateQuestion, validateNote, validateUpload } from '../utils/clinical.js'
import { loadEncounters, saveEncounters, addEncounter, removeEncounter } from '../utils/encounterStore.js'
import { uid } from '../utils/formatters.js'
import { MAX_MESSAGES, SUGGESTION_PROMPTS, ERROR_MESSAGES, LS_MODEL_KEY } from '../utils/constants.js'

/*
 * Source of truth for conversations is the BACKEND encounter (history + private context notes). The browser keeps only
 * the list of {id, token, label} in sessionStorage; messages live in memory for this tab and are re-fetched on demand.
 */
const SessionContext = createContext(null)
const EMPTY = { messages: [], notes: [], loaded: false, loading: false }

export function SessionProvider({ children }) {
  const ui = useUI()
  const [encounters, setEncounters] = useState(() => loadEncounters())
  const [activeId,   setActiveId]   = useState(() => loadEncounters()[0]?.id ?? null)
  const [data,       setData]       = useState({})                       // { [encounterId]: { messages, notes, loaded, loading } }
  const [model,      setModel]      = useLocalStorage(LS_MODEL_KEY, 'llama')
  const [health,     setHealth]     = useState({ ok: null, sources: 0, chunks: 0, records: 0 })
  const [knowledge,  setKnowledge]  = useState({ sources: [], totals: null, loading: false, error: null })

  const abortRef = useRef(null)
  const rafRef = useRef(null)
  const liveRef = useRef(null)           // { encId, msg } — the assistant message being streamed
  const encountersRef = useRef(encounters)
  encountersRef.current = encounters

  useEffect(() => { saveEncounters(encounters) }, [encounters])

  const activeEncounter = useMemo(() => encounters.find(e => e.id === activeId) ?? null, [encounters, activeId])
  const active = (activeId && data[activeId]) || EMPTY

  const patch = useCallback((id, fn) => setData(prev => ({ ...prev, [id]: fn(prev[id] ?? EMPTY) })), [])

  const dropEncounter = useCallback((id) => {
    setEncounters(prev => removeEncounter(prev, id))
    setData(prev => { const { [id]: _gone, ...rest } = prev; return rest })
    setActiveId(cur => (cur === id ? (encountersRef.current.find(e => e.id !== id)?.id ?? null) : cur))
  }, [])

  const reportError = useCallback((e, encId) => {
    if (e instanceof APIError && e.code === 'encounter_gone' && encId) dropEncounter(encId)
    ui.setError(e instanceof APIError ? e.message : ERROR_MESSAGES.UNKNOWN)
  }, [ui, dropEncounter])

  // ── backend status + knowledge list ──────────────────────────────────────────
  const refreshHealth = useCallback(async () => setHealth(await checkHealth()), [])
  const refreshKnowledge = useCallback(async () => {
    setKnowledge(k => ({ ...k, loading: true, error: null }))
    try {
      const r = await listKnowledge()
      setKnowledge({ sources: r.sources ?? [], totals: r.totals ?? null, loading: false, error: null })
    } catch (e) { setKnowledge(k => ({ ...k, loading: false, error: e.message })) }
  }, [])
  useEffect(() => { refreshHealth(); const t = setInterval(refreshHealth, 30_000); return () => clearInterval(t) }, [refreshHealth])

  // ── encounters ───────────────────────────────────────────────────────────────
  const loadEncounter = useCallback(async (enc) => {
    patch(enc.id, d => ({ ...d, loading: true }))
    try {
      const [msgs, notes] = await Promise.all([getMessages(enc), listContext(enc)])
      patch(enc.id, d => ({ ...d, loading: false, loaded: true, notes,
        // keep rich in-memory messages from this tab if we already have them; otherwise rebuild from storage
        messages: d.messages.length ? d.messages : msgs.map(fromStored) }))
    } catch (e) { patch(enc.id, d => ({ ...d, loading: false })); reportError(e, enc.id) }
  }, [patch, reportError])

  useEffect(() => {
    if (activeEncounter && !(data[activeEncounter.id]?.loaded || data[activeEncounter.id]?.loading)) loadEncounter(activeEncounter)
  }, [activeEncounter, data, loadEncounter])

  const newEncounter = useCallback(async (label) => {
    ui.setError(null)
    try {
      const enc = await createEncounter((label ?? '').trim() || `Encounter ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`)
      setEncounters(prev => addEncounter(prev, enc))
      setData(prev => ({ ...prev, [enc.id]: { ...EMPTY, loaded: true } }))
      setActiveId(enc.id)
      return enc
    } catch (e) { reportError(e); return null }
  }, [ui, reportError])

  const selectEncounter = useCallback((id) => setActiveId(id), [])

  const eraseEncounterById = useCallback(async (id) => {
    const enc = encountersRef.current.find(e => e.id === id)
    if (!enc) return
    try { await eraseEncounter(enc) }
    catch (e) { if (!(e instanceof APIError && e.code === 'encounter_gone')) { reportError(e); return } }
    dropEncounter(id)
  }, [dropEncounter, reportError])

  // ── private context notes ────────────────────────────────────────────────────
  const refreshNotes = useCallback(async (enc) => {
    const notes = await listContext(enc)
    patch(enc.id, d => ({ ...d, notes }))
  }, [patch])
  const addNote = useCallback(async (text) => {
    const problem = validateNote(text)
    if (problem) { ui.setError(problem); return false }
    if (!activeEncounter) { ui.setError('Start an encounter first.'); return false }
    try { await addContext(activeEncounter, text.trim()); await refreshNotes(activeEncounter); return true }
    catch (e) { reportError(e, activeEncounter.id); return false }
  }, [activeEncounter, ui, refreshNotes, reportError])
  const removeNote = useCallback(async (noteId) => {
    if (!activeEncounter) return
    try { await deleteContext(activeEncounter, noteId); await refreshNotes(activeEncounter) }
    catch (e) { reportError(e, activeEncounter.id) }
  }, [activeEncounter, refreshNotes, reportError])

  // ── asking ───────────────────────────────────────────────────────────────────
  const flushLive = useCallback(() => {
    rafRef.current = null
    const live = liveRef.current
    if (!live) return
    patch(live.encId, d => ({ ...d, messages: d.messages.map(m => (m.id === live.msg.id ? live.msg : m)) }))
  }, [patch])

  const sendMessage = useCallback(async (content) => {
    const problem = validateQuestion(content)
    if (problem) { ui.setError(problem); return }
    if (abortRef.current) return          // a request is already in flight (the input is disabled meanwhile) — no time-based debounce, which would silently drop a question
    const now = Date.now()
    ui.setError(null)

    const ctrl = new AbortController()
    abortRef.current = ctrl                // claimed before any await so a double send cannot start two requests
    const enc = activeEncounter ?? await newEncounter()
    if (!enc) { abortRef.current = null; return }
    const userMsg = { id: uid(), role: 'user', content: content.trim(), timestamp: now }
    const asst = emptyAssistant(uid(), now)
    patch(enc.id, d => ({ ...d, loaded: true, messages: [...d.messages, userMsg, asst].slice(-MAX_MESSAGES) }))
    liveRef.current = { encId: enc.id, msg: asst }
    ui.setLoading(true); ui.setStreaming(true)

    try {
      await askStreaming({
        question: content, model, enc, signal: ctrl.signal,
        onEvent: (ev) => {
          liveRef.current = { ...liveRef.current, msg: applyEvent(liveRef.current.msg, ev) }
          if (ev.type === 'token') { if (!rafRef.current) rafRef.current = requestAnimationFrame(flushLive) }
          else flushLive()
        },
      })
    } catch (e) {
      if (e.name === 'AbortError') liveRef.current = { ...liveRef.current, msg: { ...liveRef.current.msg, isStreaming: false, interrupted: true } }
      else {
        liveRef.current = { ...liveRef.current, msg: { ...liveRef.current.msg, isStreaming: false,
          error: e instanceof APIError ? e.message : ERROR_MESSAGES.UNKNOWN } }
        reportError(e, enc.id)
      }
    } finally {
      if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
      if (liveRef.current?.msg) {
        const fin = { ...liveRef.current.msg, isStreaming: false }
        liveRef.current = null
        patch(enc.id, d => ({ ...d, messages: d.messages.map(m => (m.id === fin.id ? fin : m)) }))
      }
      ui.setLoading(false); ui.setStreaming(false); abortRef.current = null
    }
  }, [activeEncounter, model, ui, patch, newEncounter, flushLive, reportError])

  const stopGeneration = useCallback(() => { abortRef.current?.abort() }, [])

  const retryLast = useCallback(() => {
    if (!activeEncounter) return
    const msgs = data[activeEncounter.id]?.messages ?? []
    const lastUser = [...msgs].reverse().find(m => m.role === 'user')
    if (!lastUser) return
    const cut = msgs.lastIndexOf(lastUser)
    patch(activeEncounter.id, d => ({ ...d, messages: d.messages.slice(0, cut) }))
    sendMessage(lastUser.content)
  }, [activeEncounter, data, patch, sendMessage])

  // ── reference documents ──────────────────────────────────────────────────────
  const uploadDocument = useCallback(async (form) => {
    const problem = validateUpload(form)
    if (problem) { ui.setUpload({ uploadStatus: 'error', uploadMessage: problem }); return false }
    ui.setUpload({ uploadStatus: 'uploading', uploadProgress: 0, uploadMessage: `Uploading ${form.file.name}…`, totalChunks: 0 })
    try {
      const { job_id } = await uploadSource(form)
      ui.setUpload({ uploadStatus: 'processing', uploadProgress: 100, uploadMessage: 'Extracting, chunking and embedding…' })
      const job = await waitForJob(job_id, { onProgress: (j) => ui.setUpload({ uploadMessage: j.message ?? 'Processing…' }) })
      ui.setUpload({ uploadStatus: 'success', uploadProgress: 100, uploadMessage: job.message ?? 'Indexed.', totalChunks: job.total_chunks ?? 0 })
      refreshHealth(); refreshKnowledge()
      return true
    } catch (e) {
      ui.setUpload({ uploadStatus: 'error', uploadMessage: e.message ?? 'Upload failed' })
      refreshKnowledge()
      return false
    }
  }, [ui, refreshHealth, refreshKnowledge])

  const value = useMemo(() => ({
    encounters, activeEncounter, messages: active.messages, notes: active.notes, loadingEncounter: active.loading,
    model, setModel, health, knowledge,
    newEncounter, selectEncounter, eraseEncounter: eraseEncounterById, addNote, removeNote,
    sendMessage, stopGeneration, retryLast, uploadDocument, refreshHealth, refreshKnowledge,
    suggestions: SUGGESTION_PROMPTS,
  }), [encounters, activeEncounter, active, model, setModel, health, knowledge, newEncounter, selectEncounter,
    eraseEncounterById, addNote, removeNote, sendMessage, stopGeneration, retryLast, uploadDocument, refreshHealth, refreshKnowledge])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be inside SessionProvider')
  return ctx
}

import React, { createContext, useContext, useCallback, useEffect, useRef, useMemo } from 'react'
import { useLocalStorage } from '../hooks/useLocalStorage.js'
import { useUI } from './UIContext.jsx'
import { askQuestionStreaming, uploadVideo, uploadPdf, APIError } from '../utils/api.js'
import { titleFromMessage, uid } from '../utils/formatters.js'
import { MAX_SESSIONS, MAX_MESSAGES, SUGGESTION_PROMPTS, ERROR_MESSAGES, SEND_DEBOUNCE_MS } from '../utils/constants.js'

function makeSession(overrides = {}) {
  const now = Date.now()
  return { id: uid(), title: 'New Chat', createdAt: now, updatedAt: now, messages: [], ...overrides }
}
function makeMsg(role, content, extras = {}) {
  return { id: uid(), role, content, timestamp: Date.now(), ...extras }
}

const DEMO_SESSION = makeSession({
  id: 'demo-session-v3', title: 'Welcome',
  messages: [makeMsg('assistant',
    '## Welcome to RAGTutor v2 \uD83D\uDC4B\n\nAsk me anything about your **video library** or **uploaded PDFs**.\n\nI can also search the web for current information automatically.\n\n> Upload a **video** or **PDF** using the \uD83D\uDCCE button to add it to your knowledge base.',
    {
      ragSources: [{ id: 'demo-src-0', title: 'Video 01 \u2014 Getting Started', score: 0.97, excerpt: 'Welcome to the course.', type: 'video', _start: 0, _end: 45, _number: '01', _rawTitle: 'Getting Started', sourceUrl: null }],
      webSources: [],
      intent: 'video',
      video: { url: null, title: 'Video 01 \u2014 Getting Started', timestamps: [{ time: 0, label: 'Introduction' }] },
    }
  )],
})

function getDemoResponse(q) {
  const ql = q.toLowerCase()
  if (ql.includes('flex') || ql.includes('center') || ql.includes('css')) {
    return {
      content: 'Go to **Video 03 \u2014 CSS Flexbox** and watch from **02:14**.\n\n```css\n.container {\n  display: flex;\n  justify-content: center;\n  align-items: center;\n}\n```',
      ragSources: [
        { id: 'd0', title: 'Video 03 \u2014 CSS Flexbox', score: 0.94, excerpt: 'Centering with flexbox requires display flex and justify-content center.', type: 'video', _start: 134, _end: 178, _number: '03', _rawTitle: 'CSS Flexbox', sourceUrl: null },
        { id: 'd1', title: 'Video 05 \u2014 CSS Grid',    score: 0.76, excerpt: 'place-items center is the most concise centering solution.', type: 'video', _start: 52, _end: 89, _number: '05', _rawTitle: 'CSS Grid', sourceUrl: null },
      ],
      webSources: [], intent: 'video',
      video: { url: null, title: 'Video 03 \u2014 CSS Flexbox', timestamps: [{ time: 134, label: 'Flexbox centering' }, { time: 52, label: 'Grid shorthand' }] },
    }
  }
  if (ql.includes('async') || ql.includes('promise') || ql.includes('await')) {
    return {
      content: 'Go to **Video 07 \u2014 JavaScript Async** and watch from **03:45**.\n\n```javascript\nasync function fetchData(url) {\n  const res = await fetch(url)\n  return res.json()\n}\n```',
      ragSources: [{ id: 'd2', title: 'Video 07 \u2014 JavaScript Async', score: 0.93, excerpt: 'async/await makes asynchronous code readable.', type: 'video', _start: 225, _end: 290, _number: '07', _rawTitle: 'JavaScript Async', sourceUrl: null }],
      webSources: [], intent: 'video',
      video: { url: null, title: 'Video 07 \u2014 JavaScript Async', timestamps: [{ time: 225, label: 'async/await syntax' }] },
    }
  }
  return {
    content: '**Demo mode** \u2014 connect your FastAPI backend:\n\n```bash\nVITE_API_BASE_URL=http://localhost:8000 npm run dev\n```',
    ragSources: [{ id: 'd3', title: 'Video 01 \u2014 Introduction', score: 0.88, excerpt: 'Connect your backend to see real results.', type: 'video', _start: 0, _end: 45, _number: '01', _rawTitle: 'Introduction', sourceUrl: null }],
    webSources: [], intent: 'video',
    video: { url: null, title: 'Video 01 \u2014 Introduction', timestamps: [{ time: 0, label: 'Getting started' }] },
  }
}

const SessionContext = createContext(null)

export function SessionProvider({ children }) {
  const ui = useUI()
  const [sessions,  setSessions] = useLocalStorage('rag_sessions_v3', [DEMO_SESSION])
  const [activeId,  setActiveId] = useLocalStorage('rag_active_v3',   DEMO_SESSION.id)
  const [model,     setModel]    = useLocalStorage('rag_model_v3',    'llama')

  const streamAccumRef       = useRef('')
  const streamRafRef         = useRef(null)
  const abortRef             = useRef(null)
  const activeSendSessionRef = useRef(null)
  const pollAbortRef         = useRef(null)
  const lastSendRef          = useRef(0)

  const activeSession = useMemo(
    () => sessions.find(s => s.id === activeId) ?? sessions[0] ?? null,
    [sessions, activeId],
  )

  const newSession    = useCallback(() => {
    const s = makeSession()
    setSessions(prev => [s, ...prev].slice(0, MAX_SESSIONS))
    setActiveId(s.id)
  }, [setSessions, setActiveId])

  const selectSession = useCallback((id) => setActiveId(id), [setActiveId])

  const deleteSession = useCallback((id) => {
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id)
      if (next.length === 0) { const fresh = makeSession(); setActiveId(fresh.id); return [fresh] }
      if (id === activeId) setActiveId(next[0].id)
      return next
    })
  }, [activeId, setSessions, setActiveId])

  const renameSession = useCallback((id, title) => {
    setSessions(prev => prev.map(s =>
      s.id === id ? { ...s, title: (title.trim().slice(0, 80) || 'Untitled'), updatedAt: Date.now() } : s
    ))
  }, [setSessions])

  const clearChat = useCallback(() => {
    setSessions(prev => prev.map(s =>
      s.id === activeId ? { ...s, messages: [], updatedAt: Date.now() } : s
    ))
  }, [activeId, setSessions])

  const appendMsg = useCallback((msg) => {
    setSessions(prev => prev.map(s => {
      if (s.id !== activeId) return s
      const isFirst = s.messages.length === 0 && msg.role === 'user'
      return {
        ...s,
        title:     isFirst ? titleFromMessage(msg.content) : s.title,
        updatedAt: Date.now(),
        messages:  [...s.messages, msg].slice(-MAX_MESSAGES),
      }
    }))
  }, [activeId, setSessions])

  const flushStream = useCallback(() => {
    streamRafRef.current = null
    const content = streamAccumRef.current
    setSessions(prev => prev.map(s => {
      if (s.id !== activeId) return s
      const msgs = [...s.messages]
      const idx  = msgs.length - 1
      if (msgs[idx]?.role === 'assistant' && msgs[idx]?.isStreaming)
        msgs[idx] = { ...msgs[idx], content }
      return { ...s, messages: msgs }
    }))
  }, [activeId, setSessions])

  const scheduleFlush = useCallback(() => {
    if (!streamRafRef.current) streamRafRef.current = requestAnimationFrame(flushStream)
  }, [flushStream])

  const finaliseStream = useCallback((patch) => {
    if (streamRafRef.current) { cancelAnimationFrame(streamRafRef.current); streamRafRef.current = null }
    setSessions(prev => prev.map(s => {
      if (s.id !== activeId) return s
      const msgs = [...s.messages]
      const idx  = msgs.length - 1
      if (msgs[idx]?.role === 'assistant') msgs[idx] = { ...msgs[idx], ...patch, isStreaming: false }
      return { ...s, messages: msgs, updatedAt: Date.now() }
    }))
  }, [activeId, setSessions])

  const sendMessageInternal = useCallback(async (content) => {
    if (!content.trim()) return
    const now = Date.now()
    if (now - lastSendRef.current < SEND_DEBOUNCE_MS) return
    lastSendRef.current = now

    ui.setError(null)
    ui.setLoading(true)
    appendMsg(makeMsg('user', content.trim()))
    appendMsg(makeMsg('assistant', '', { isStreaming: true, webSources: [], intent: 'video' }))
    streamAccumRef.current = ''
    activeSendSessionRef.current = activeId

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      if (!import.meta.env.VITE_API_BASE_URL) {
        // Demo mode
        ui.setStreaming(true)
        const demo  = getDemoResponse(content)
        const words = demo.content.split(' ')
        for (let i = 0; i < words.length; i++) {
          if (ctrl.signal.aborted) break
          streamAccumRef.current += (i === 0 ? '' : ' ') + words[i]
          scheduleFlush()
          await new Promise(r => setTimeout(r, 14 + Math.random() * 10))
        }
        finaliseStream({
          content:    demo.content,
          ragSources: demo.ragSources,
          webSources: demo.webSources ?? [],
          intent:     demo.intent ?? 'video',
          video:      demo.video,
        })
      } else {
        ui.setStreaming(true)
        await askQuestionStreaming({
          question: content.trim(),
          model,
          signal:   ctrl.signal,
          onChunk:  (token, accumulated) => {
            streamAccumRef.current = accumulated
            scheduleFlush()
          },
          // v2: onSourcesReady now receives webSources + intent
          onSourcesReady: (ragSources, video, modelUsed, webSources, intent) => {
            const targetId = activeSendSessionRef.current
            setSessions(prev => prev.map(s => {
              if (s.id !== targetId) return s
              const msgs = [...s.messages]
              const idx  = msgs.length - 1
              if (msgs[idx]?.role === 'assistant')
                msgs[idx] = {
                  ...msgs[idx],
                  ragSources,
                  video,
                  webSources: webSources ?? [],
                  intent:     intent ?? 'video',
                  modelUsed,
                }
              return { ...s, messages: msgs }
            }))
          },
          onComplete: (result) => {
            finaliseStream({
              content:    result.answer,
              ragSources: result.ragSources,
              webSources: result.webSources ?? [],
              intent:     result.intent ?? 'video',
              video:      result.video,
              modelUsed:  result.modelUsed,
            })
          },
        })
      }
    } catch (e) {
      if (e.name === 'AbortError') { finaliseStream({ content: streamAccumRef.current || '' }); return }
      const msg = e instanceof APIError ? e.message : ERROR_MESSAGES.NETWORK
      finaliseStream({ content: '', error: msg })
      ui.setError(msg)
    } finally {
      ui.setLoading(false)
      ui.setStreaming(false)
    }
  }, [activeId, model, ui, appendMsg, scheduleFlush, finaliseStream]) // eslint-disable-line

  const sendMessage   = useCallback((content) => { sendMessageInternal(content) }, [sendMessageInternal])
  const stopGeneration = useCallback(() => {
    abortRef.current?.abort()
    ui.setLoading(false); ui.setStreaming(false)
  }, [ui])

  const retryLast = useCallback(() => {
    let lastUserContent = null
    setSessions(prev => prev.map(s => {
      if (s.id !== activeId) return s
      const msgs = [...s.messages]
      if (msgs[msgs.length - 1]?.role === 'assistant') msgs.pop()
      lastUserContent = [...msgs].reverse().find(m => m.role === 'user')?.content ?? null
      return { ...s, messages: msgs }
    }))
    setTimeout(() => { if (lastUserContent) sendMessageInternal(lastUserContent) }, 60)
  }, [activeId, setSessions, sendMessageInternal])

  /* ── Video upload (unchanged logic) ── */
  const uploadVideoFile = useCallback(async (file) => {
    ui.setUpload({ uploadStatus: 'uploading', uploadProgress: 0, uploadMessage: 'Uploading ' + file.name + '…' })
    ui.setError(null)
    try {
      const result = await uploadVideo(file, (pct) => {
        ui.setUpload({ uploadProgress: pct })
        if (pct === 100) ui.setUpload({ uploadStatus: 'processing', uploadMessage: 'Transcribing & indexing…' })
      })
      if (result.job_id) {
        const BASE         = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
        const pollInterval = 3000
        const maxPolls     = 120
        const pollAbort    = new AbortController()
        pollAbortRef.current = pollAbort
        try {
          for (let i = 0; i < maxPolls; i++) {
            await new Promise((res, rej) => {
              const tid = setTimeout(res, pollInterval)
              pollAbort.signal.addEventListener('abort',
                () => { clearTimeout(tid); rej(Object.assign(new Error('Aborted'), { name: 'AbortError' })) },
                { once: true },
              )
            })
            if (pollAbort.signal.aborted) return
            try {
              const resp = await fetch(`${BASE}/jobs/${result.job_id}`, { signal: pollAbort.signal })
              if (!resp.ok) continue
              const job = await resp.json()
              if (job.status === 'success') {
                ui.setUpload({ uploadStatus: 'success', uploadProgress: 100, uploadMessage: job.message ?? 'Video indexed!', totalChunks: job.total_chunks ?? 0 })
                setTimeout(() => ui.resetUpload(), 4500)
                return
              }
              if (job.status === 'error')     throw new Error(job.message ?? 'Ingestion failed')
              if (job.status === 'not_found') throw new Error(job.message ?? 'Job lost — please re-upload.')
              ui.setUpload({ uploadMessage: job.message ?? 'Processing…' })
            } catch (pollErr) {
              if (pollErr.name === 'AbortError') return
              if (/Ingestion|lost|restart/i.test(pollErr.message)) throw pollErr
            }
          }
          throw new Error('Processing timed out — check server logs.')
        } finally { pollAbortRef.current = null }
      } else {
        ui.setUpload({ uploadStatus: 'success', uploadProgress: 100, uploadMessage: result.message ?? 'Video indexed!', totalChunks: result.total_chunks ?? 0 })
        setTimeout(() => ui.resetUpload(), 4500)
      }
    } catch (e) {
      if (e.name === 'AbortError') { ui.resetUpload(); return }
      ui.setUpload({ uploadStatus: 'error', uploadMessage: e.message ?? 'Upload failed' })
      ui.setError(e.message ?? ERROR_MESSAGES.NETWORK)
    }
  }, [ui])

  /* ── PDF upload (v2 — new) ── */
  const uploadPdfFile = useCallback(async (file) => {
    ui.setUpload({ uploadStatus: 'uploading', uploadProgress: 0, uploadMessage: 'Uploading ' + file.name + '…' })
    ui.setError(null)
    try {
      const result = await uploadPdf(file)
      ui.setUpload({ uploadStatus: 'processing', uploadProgress: 100, uploadMessage: 'Extracting & indexing PDF…' })

      if (result.job_id) {
        const BASE         = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
        const pollInterval = 2000
        const maxPolls     = 90           // 3 min max for large PDFs
        const pollAbort    = new AbortController()
        pollAbortRef.current = pollAbort
        try {
          for (let i = 0; i < maxPolls; i++) {
            await new Promise((res, rej) => {
              const tid = setTimeout(res, pollInterval)
              pollAbort.signal.addEventListener('abort',
                () => { clearTimeout(tid); rej(Object.assign(new Error('Aborted'), { name: 'AbortError' })) },
                { once: true },
              )
            })
            if (pollAbort.signal.aborted) return
            try {
              const resp = await fetch(`${BASE}/jobs/pdf/${result.job_id}`, { signal: pollAbort.signal })
              if (!resp.ok) continue
              const job = await resp.json()
              if (job.status === 'success') {
                ui.setUpload({
                  uploadStatus:  'success',
                  uploadProgress: 100,
                  uploadMessage:  job.message ?? 'PDF indexed!',
                  totalChunks:   job.total_chunks ?? 0,
                })
                setTimeout(() => ui.resetUpload(), 4500)
                return
              }
              if (job.status === 'error')     throw new Error(job.message ?? 'PDF ingestion failed')
              if (job.status === 'not_found') throw new Error('PDF job lost — please re-upload.')
              ui.setUpload({ uploadMessage: job.message ?? 'Processing PDF…' })
            } catch (pollErr) {
              if (pollErr.name === 'AbortError') return
              throw pollErr
            }
          }
          throw new Error('PDF processing timed out — check server logs.')
        } finally { pollAbortRef.current = null }
      } else {
        ui.setUpload({ uploadStatus: 'success', uploadProgress: 100, uploadMessage: result.message ?? 'PDF indexed!', totalChunks: result.total_chunks ?? 0 })
        setTimeout(() => ui.resetUpload(), 4500)
      }
    } catch (e) {
      if (e.name === 'AbortError') { ui.resetUpload(); return }
      ui.setUpload({ uploadStatus: 'error', uploadMessage: e.message ?? 'PDF upload failed' })
      ui.setError(e.message ?? ERROR_MESSAGES.NETWORK)
    }
  }, [ui])

  // Cleanup polling on unmount
  useEffect(() => { return () => { pollAbortRef.current?.abort() } }, [])

  const value = useMemo(() => ({
    sessions, activeSession, model, setModel,
    newSession, selectSession, deleteSession, renameSession, clearChat,
    sendMessage, stopGeneration, retryLast,
    uploadVideoFile, uploadPdfFile,             // v2: expose uploadPdfFile
    suggestions: SUGGESTION_PROMPTS,
  }), [sessions, activeSession, model, setModel,
    newSession, selectSession, deleteSession, renameSession, clearChat,
    sendMessage, stopGeneration, retryLast, uploadVideoFile, uploadPdfFile])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be inside SessionProvider')
  return ctx
}

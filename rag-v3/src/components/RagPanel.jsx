import React, { memo, useMemo, useState, useCallback } from 'react'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import { getChunk } from '../utils/api.js'
import ContextPanel from './ContextPanel.jsx'

/* One cited excerpt. The preview comes with the answer; the FULL text and provenance are fetched on demand
   (GET /chunks/{id}) so nothing the clinician reads is truncated. */
const SourceCard = memo(function SourceCard({ source }) {
  const [open, setOpen] = useState(false)
  const [full, setFull] = useState({ state: 'idle', row: null, error: null })

  const toggle = useCallback(async () => {
    const next = !open
    setOpen(next)
    if (next && full.state === 'idle' && source.fullTextPath) {
      setFull({ state: 'loading', row: null, error: null })
      try { setFull({ state: 'done', row: await getChunk(source.fullTextPath), error: null }) }
      catch (e) { setFull({ state: 'error', row: null, error: e.message }) }
    }
  }, [open, full.state, source.fullTextPath])

  const row = full.row
  return (
    <div className="rounded-xl border border-void-500 bg-void-800 overflow-hidden" data-testid="source-card">
      <button onClick={toggle} aria-expanded={open} className="w-full text-left p-3 focus-visible:ring-2 focus-visible:ring-violet rounded-xl">
        <div className="flex items-start gap-2">
          <span className="w-6 h-5 rounded-md bg-violet/20 border border-violet/30 flex items-center justify-center shrink-0 text-[9px] font-bold text-violet-light mt-0.5">{source.ref}</span>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-medium text-ink leading-tight break-words">{source.title}</p>
            <p className="text-[10px] text-ink-faint mt-0.5">
              match {Math.round((source.score ?? 0) * 100)}%{source.page ? ` · page ${source.page}` : ''}{source.section ? ` · § ${source.section}` : ''}
            </p>
          </div>
          <span className={`shrink-0 text-ink-faint transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true">▾</span>
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3">
          <div className="h-px bg-void-600 mb-2.5" />
          {full.state === 'loading' && <div className="skeleton h-16 rounded" role="status" aria-label="Loading full excerpt" />}
          {full.state === 'error' && <p className="text-[11px] text-rose" role="alert">Could not load the full excerpt: {full.error}</p>}
          {full.state === 'done' && (
            <>
              <p className="text-[11px] text-ink leading-relaxed whitespace-pre-wrap break-words">{row.text}</p>
              <dl className="mt-2 grid grid-cols-[4.5rem_1fr] gap-x-2 gap-y-0.5 text-[10px] text-ink-faint">
                <dt>Document</dt><dd className="break-words">{row.display_name}</dd>
                <dt>Version</dt><dd>v{row.version}</dd>
                {row.page ? (<><dt>Page</dt><dd>{row.page}</dd></>) : null}
                <dt>Licence</dt><dd className="break-words">{row.license || 'not recorded'}</dd>
                <dt>Origin</dt><dd className="break-words">{row.origin || 'not recorded'}</dd>
              </dl>
            </>
          )}
          {full.state === 'idle' && <p className="text-[11px] text-ink-muted whitespace-pre-wrap break-words">{source.excerpt || 'No excerpt available.'}</p>}
          {(full.state === 'error') && source.excerpt && <p className="mt-2 text-[11px] text-ink-muted whitespace-pre-wrap break-words">Preview: {source.excerpt}</p>}
        </div>
      )}
    </div>
  )
})

function SourcesTab({ message, isLoading }) {
  const sources = message?.sources ?? []
  return (
    <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2" aria-label="Cited sources">
      {isLoading && sources.length === 0 && [0, 1].map(i => <div key={i} className="skeleton h-14 rounded-xl" />)}
      {!isLoading && sources.length === 0 && (
        <div className="text-center px-4 py-10">
          <p className="text-xs font-medium text-ink-muted mb-1">No sources for this answer</p>
          <p className="text-[10px] text-ink-faint leading-relaxed">
            {message?.recordViews?.length ? 'This answer comes from a structured record; its provenance is shown on the card.' : 'Ask a question to see the excerpts it was based on.'}
          </p>
        </div>
      )}
      {sources.map(s => <SourceCard key={s.id} source={s} />)}
    </div>
  )
}

function PanelBody({ onClose }) {
  const { messages, activeEncounter } = useSession()
  const { isLoading, sourcesMessageId } = useUI()
  const [tab, setTab] = useState('sources')

  const message = useMemo(() => {
    const assistants = messages.filter(m => m.role === 'assistant')
    return assistants.find(m => m.id === sourcesMessageId) ?? assistants[assistants.length - 1] ?? null
  }, [messages, sourcesMessageId])

  const tabs = [{ id: 'sources', label: `Sources${message?.sources?.length ? ` (${message.sources.length})` : ''}` }, { id: 'context', label: 'Patient context' }]
  return (
    <>
      <div className="px-4 pt-3 pb-2 border-b border-void-600 flex items-center gap-2">
        <div role="tablist" aria-label="Side panel" className="flex gap-1 p-1 bg-void-800 rounded-lg flex-1">
          {tabs.map(t => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
              className={`flex-1 py-1.5 px-2 rounded-md text-[10px] font-semibold transition-all ${tab === t.id ? 'bg-void-600 text-ink shadow-sm' : 'text-ink-faint hover:text-ink-muted'}`}>
              {t.label}
            </button>
          ))}
        </div>
        {onClose && <button onClick={onClose} className="btn-icon" aria-label="Close panel">✕</button>}
      </div>
      {tab === 'sources' ? <SourcesTab message={message} isLoading={isLoading} /> : <ContextPanel encounter={activeEncounter} />}
      <div className="border-t border-void-600 px-4 py-2.5">
        <p className="text-[9px] text-ink-faint leading-relaxed">Reference information only — not a diagnosis or prescription. Always verify against the primary source.</p>
      </div>
    </>
  )
}

export default memo(function RagPanel() {
  const { ragPanelOpen, toggleRagPanel } = useUI()
  return (
    <>
      <aside className="w-80 shrink-0 hidden xl:flex flex-col bg-void-900 border-l border-void-600 overflow-hidden" aria-label="Sources and patient context">
        <PanelBody />
      </aside>
      {ragPanelOpen && (
        <div className="xl:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Sources and patient context">
          <div className="absolute inset-0 bg-void-950/80 backdrop-blur-sm" onClick={toggleRagPanel} />
          <div className="absolute bottom-0 left-0 right-0 max-h-[80dvh] bg-void-900 border-t border-void-600 rounded-t-2xl flex flex-col overflow-hidden animate-slide-up">
            <PanelBody onClose={toggleRagPanel} />
          </div>
        </div>
      )}
    </>
  )
})

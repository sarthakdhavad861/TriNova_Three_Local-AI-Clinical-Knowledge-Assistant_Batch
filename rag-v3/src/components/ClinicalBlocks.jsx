import React, { memo } from 'react'
import { STATUS_LABELS, WORKFLOW_LABELS } from '../utils/constants.js'
import { trustLine, RECORD_DISCLAIMER_FALLBACK } from '../utils/clinical.js'

/* Notices from the backend start with a marker character that decides how prominent they are. */
function noticeTone(text) {
  if (text.startsWith('🚨')) return 'urgent'
  if (text.startsWith('ℹ'))  return 'info'
  if (text.startsWith('⚠'))  return 'warn'
  return 'note'
}
const TONES = {
  urgent: 'border-rose/50 bg-rose/15 text-rose-light font-semibold',
  warn:   'border-amber/40 bg-amber/10 text-amber',
  info:   'border-cyan/30 bg-cyan/10 text-cyan-light',
  note:   'border-void-500 bg-void-800 text-ink-muted',
}

export const Notices = memo(function Notices({ notices }) {
  if (!notices?.length) return null
  // Urgent first, always.
  const sorted = [...notices].sort((a, b) => (noticeTone(a) === 'urgent' ? -1 : 0) - (noticeTone(b) === 'urgent' ? -1 : 0))
  return (
    <div className="space-y-2 mb-3" data-testid="notices">
      {sorted.map((n, i) => {
        const tone = noticeTone(n)
        return (
          <div key={i} role={tone === 'urgent' ? 'alert' : 'note'}
               className={`rounded-xl border px-3 py-2.5 text-xs leading-relaxed whitespace-pre-wrap break-words ${TONES[tone]}`}>
            {n}
          </div>
        )
      })}
    </div>
  )
})

/* A structured record card. Values are rendered exactly as stored (whitespace preserved, no reformatting). */
const RecordCard = memo(function RecordCard({ view }) {
  return (
    <article className="rounded-xl border border-void-400 bg-void-800 overflow-hidden" aria-label={`Record: ${view.name}`}>
      <header className="px-3 py-2 border-b border-void-500 flex items-baseline gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-ink">{view.name}</h3>
        <span className="text-[10px] uppercase tracking-wider text-ink-faint">{view.category} record</span>
      </header>
      <dl className="divide-y divide-void-600">
        {view.rows.map((r, i) => (
          <div key={i} className={`grid grid-cols-[9rem_1fr] gap-2 px-3 py-1.5 text-xs ${r.warning ? 'bg-amber/10' : ''}`}>
            <dt className={`font-medium ${r.warning ? 'text-amber' : 'text-ink-muted'}`}>{r.warning ? '⚠ ' : ''}{r.key}</dt>
            <dd className={`whitespace-pre-wrap break-words ${r.not_stated ? 'text-ink-faint italic' : 'text-ink'}`}>{r.value}</dd>
          </div>
        ))}
      </dl>
      <footer className="px-3 py-1.5 text-[10px] text-ink-faint border-t border-void-500 break-words">Source: {view.source}</footer>
    </article>
  )
})

export const RecordCards = memo(function RecordCards({ views, disclaimer }) {
  if (!views?.length) return null
  return (
    <section className="space-y-2 mb-3" aria-label="Structured reference records" data-testid="records">
      {views.map((v, i) => <RecordCard key={i} view={v} />)}
      <p className="text-[10px] text-ink-faint">{disclaimer || RECORD_DISCLAIMER_FALLBACK}</p>
    </section>
  )
})

export const TrustLine = memo(function TrustLine({ message, onShowSources }) {
  const line = trustLine(message)
  const meta = STATUS_LABELS[message.status]
  if (!line && !message.verification && !message.interrupted) return null
  const tone = { ok: 'text-emerald', bad: 'text-rose', warn: 'text-amber', info: 'text-cyan' }[meta?.tone] ?? 'text-ink-faint'
  return (
    <div className="mt-3 pt-2.5 border-t border-void-600 space-y-1.5" data-testid="trust">
      <div className="flex items-center gap-2 flex-wrap text-[10px]">
        {meta && <span className={`font-semibold ${tone}`}>{meta.label}</span>}
        {message.workflow && <span className="text-ink-faint">· {WORKFLOW_LABELS[message.workflow] ?? message.workflow}</span>}
        {message.sources?.length > 0 && (
          <button onClick={onShowSources} className="ml-auto text-violet-light hover:text-violet underline underline-offset-2">
            {message.sources.length} source{message.sources.length === 1 ? '' : 's'}
          </button>
        )}
      </div>
      {line && <p className="text-[10px] text-ink-faint leading-relaxed">{line}</p>}
      {message.verification?.issues?.length > 0 && (
        <ul className="text-[10px] text-ink-muted list-disc pl-4 space-y-0.5" aria-label="Evidence check findings">
          {message.verification.issues.map((x, i) => <li key={i} className="break-words">{x}</li>)}
        </ul>
      )}
      {message.interrupted && <p className="text-[10px] text-amber">Generation stopped — this partial answer was not saved to the encounter history.</p>}
    </div>
  )
})

import React, { memo, useMemo, useState, useCallback } from 'react'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import { formatScore, scoreColor, formatVideoTime } from '../utils/formatters.js'
import { MAX_RAG_SOURCES, SIMILARITY_THRESHOLD } from '../utils/constants.js'

/* ── Score bar ── */
const ScoreBar = memo(function ScoreBar({ score }) {
  const pct   = Math.round((score ?? 0) * 100)
  const color = scoreColor(score)
  return (
    <div className="flex items-center gap-2 mt-1.5">
      <div
        className="flex-1 h-1 bg-void-600 rounded-full overflow-hidden"
        role="meter"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Similarity score: ${pct}%`}
      >
        <div
          className="h-full rounded-full score-bar-fill"
          style={{ '--score-pct': `${pct}%`, background: color }}
        />
      </div>
      <span className="text-[10px] font-mono font-semibold shrink-0 tabular-nums w-8 text-right" style={{ color }}>
        {formatScore(score)}
      </span>
    </div>
  )
})

/* ── Type badge ── */
function TypeBadge({ type }) {
  const configs = {
    video:    { label: 'VIDEO', color: 'text-violet bg-violet/10 border-violet/25',  icon: <VideoIcon size={9} /> },
    pdf:      { label: 'PDF',   color: 'text-rose bg-rose/10 border-rose/25',        icon: <FileTextIcon size={9} /> },
    web:      { label: 'WEB',   color: 'text-cyan bg-cyan/10 border-cyan/25',        icon: <GlobeIcon size={9} /> },
    webpage:  { label: 'WEB',   color: 'text-cyan bg-cyan/10 border-cyan/25',        icon: <GlobeIcon size={9} /> },
    document: { label: 'DOC',   color: 'text-amber bg-amber/10 border-amber/25',     icon: <FileIcon size={9} /> },
  }
  const c = configs[type] ?? configs.document
  return (
    <span className={`inline-flex items-center gap-1 text-[8px] font-semibold px-1.5 py-0.5 rounded border ${c.color}`}>
      {c.icon}{c.label}
    </span>
  )
}

/* ── Source card ── */
const SourceCard = memo(function SourceCard({ source, index, isExpanded, onToggle }) {
  const hasTimestamp = source.type === 'video' && typeof source._start === 'number' && source._start > 0
  const hasUrl       = Boolean(source.sourceUrl)
  const hasPdfPage   = source.type === 'pdf' && source._page

  const handleClick = useCallback(() => {
    onToggle(source.id ?? `fallback-${index}`)
  }, [source.id, index, onToggle])

  const openSource = useCallback((e) => {
    e.stopPropagation()
    if (source.sourceUrl) window.open(source.sourceUrl, '_blank', 'noopener,noreferrer')
  }, [source.sourceUrl])

  return (
    <div className="card-hover rounded-xl overflow-hidden">
      <button
        onClick={handleClick}
        className="w-full text-left p-3 focus-visible:ring-2 focus-visible:ring-violet rounded-xl"
        aria-expanded={isExpanded}
        aria-controls={`source-excerpt-${source.id}`}
      >
        <div className="flex items-start gap-2">
          <div className="w-5 h-5 rounded-md bg-violet/20 border border-violet/30 flex items-center justify-center shrink-0 text-[9px] font-bold text-violet-light mt-0.5">
            {index + 1}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
              <TypeBadge type={source.type} />
              {hasTimestamp && (
                <span className="text-[9px] font-mono text-violet-light">
                  {formatVideoTime(source._start)}
                </span>
              )}
              {hasPdfPage && (
                <span className="text-[9px] font-mono text-rose-400">
                  p.{source._page}
                </span>
              )}
            </div>
            <p className="text-[11px] font-medium text-ink truncate leading-tight">
              {source.title}
            </p>
            <ScoreBar score={source.score} />
          </div>
          <div className={`shrink-0 text-ink-faint transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}>
            <ChevronIcon size={12} />
          </div>
        </div>
      </button>

      {isExpanded && (
        <div id={`source-excerpt-${source.id}`} className="px-3 pb-3 animate-fade-in">
          <div className="h-px bg-void-600 mb-2.5" />
          <p className="text-[11px] text-ink-muted leading-relaxed">
            {source.excerpt || 'No excerpt available.'}
          </p>
          {hasTimestamp && (
            <p className="text-[10px] text-violet-light font-mono mt-2">
              ⏱ {formatVideoTime(source._start)} → {formatVideoTime(source._end)}
            </p>
          )}
          {hasPdfPage && source._filename && (
            <p className="text-[10px] text-rose-400 font-mono mt-2">
              📄 {source._filename} — page {source._page}
            </p>
          )}
          {hasUrl && (
            <button
              onClick={openSource}
              className="mt-2 flex items-center gap-1 text-[10px] text-violet-light hover:text-violet transition-colors"
            >
              <ExternalLinkIcon size={10} /> Open source ↗
            </button>
          )}
        </div>
      )}
    </div>
  )
})

/* ── Skeleton ── */
function SourceSkeleton() {
  return (
    <div className="p-3 rounded-xl border border-void-600 space-y-2">
      <div className="flex gap-2">
        <div className="skeleton w-5 h-5 rounded-md shrink-0" />
        <div className="flex-1 space-y-1.5">
          <div className="skeleton h-2.5 w-14 rounded" />
          <div className="skeleton h-2.5 w-full rounded" />
          <div className="skeleton h-1 w-full rounded-full" />
        </div>
      </div>
    </div>
  )
}

/* ── Empty state ── */
function EmptyState({ tab }) {
  const labels = { video: 'video sources', pdf: 'PDF sources', web: 'web results' }
  return (
    <div className="flex flex-col items-center justify-center h-36 text-center px-4">
      <div className="w-10 h-10 rounded-xl bg-void-700 border border-void-600 flex items-center justify-center mb-3">
        <SearchIcon size={18} className="text-ink-faint" />
      </div>
      <p className="text-xs font-medium text-ink-muted mb-1">No {labels[tab] ?? 'sources'}</p>
      <p className="text-[10px] text-ink-faint leading-relaxed">
        {tab === 'web'
          ? 'Web search runs automatically for current-info queries'
          : 'Send a message to see retrieved chunks'}
      </p>
    </div>
  )
}

/* ── Tab bar ── */
function TabBar({ tab, setTab, counts }) {
  const tabs = [
    { id: 'video', label: 'Video', icon: <VideoIcon size={9} /> },
    { id: 'pdf',   label: 'PDF',   icon: <FileTextIcon size={9} /> },
    { id: 'web',   label: 'Web',   icon: <GlobeIcon size={9} /> },
  ]
  return (
    <div className="flex gap-1 p-1 bg-void-800 rounded-lg mx-3 mb-3">
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => setTab(t.id)}
          className={`
            flex-1 flex items-center justify-center gap-1 py-1.5 px-1 rounded-md text-[10px]
            font-semibold transition-all duration-150
            ${tab === t.id
              ? 'bg-void-600 text-ink shadow-sm'
              : 'text-ink-faint hover:text-ink-muted'}
          `}
        >
          {t.icon}
          {t.label}
          {counts[t.id] > 0 && (
            <span className="bg-violet/25 text-violet-light rounded-full px-1.5 text-[9px] font-bold tabular-nums">
              {counts[t.id]}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

/* ── Intent badge ── */
function IntentBadge({ intent }) {
  if (!intent || intent === 'video') return null
  const labels = {
    pdf:    { label: 'PDF query',    color: 'text-rose-400 bg-rose/10 border-rose/25' },
    web:    { label: 'Web search',   color: 'text-cyan-400 bg-cyan/10 border-cyan/25' },
    hybrid: { label: 'Multi-source', color: 'text-amber-400 bg-amber/10 border-amber/25' },
  }
  const cfg = labels[intent]
  if (!cfg) return null
  return (
    <span className={`inline-flex items-center text-[9px] font-semibold px-2 py-0.5 rounded border ${cfg.color}`}>
      {cfg.label}
    </span>
  )
}

/* ── Panel content ── */
function PanelContent({ videoSources, pdfSources, webSources, avgScore, hasVideo, isLoading, expanded, onToggle, intent }) {
  const [tab, setTab] = useState('video')

  const counts = {
    video: videoSources.length,
    pdf:   pdfSources.length,
    web:   webSources.length,
  }

  const displayed =
    tab === 'video' ? videoSources.slice(0, MAX_RAG_SOURCES) :
    tab === 'pdf'   ? pdfSources.slice(0, MAX_RAG_SOURCES)   :
                      webSources.slice(0, MAX_RAG_SOURCES)

  const totalSources = videoSources.length + pdfSources.length + webSources.length

  return (
    <>
      {/* Stats */}
      {totalSources > 0 && (
        <div className="grid grid-cols-3 gap-2 px-4 pb-3">
          {[
            { label: 'Sources', value: totalSources },
            { label: 'Avg',     value: `${avgScore}%` },
            { label: 'Intent',  value: intent ?? 'video', special: true },
          ].map(({ label, value, special }) => (
            <div key={label} className="bg-void-800 border border-void-600 rounded-xl p-2 text-center">
              <p className="text-sm font-bold tabular-nums text-ink">{special ? null : value}</p>
              {special && <IntentBadge intent={value} />}
              <p className="text-[8px] text-ink-faint uppercase tracking-wider mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tab bar */}
      <TabBar tab={tab} setTab={setTab} counts={counts} />

      {/* Sources list */}
      <div className="flex-1 overflow-y-auto px-3 py-1 space-y-2 scrollbar-none">
        {isLoading && totalSources === 0 && (
          <>{[0,1,2].map(i => <SourceSkeleton key={i} />)}</>
        )}
        {!isLoading && displayed.length === 0 && <EmptyState tab={tab} />}
        {displayed.map((s, i) => (
          <SourceCard
            key={s.id ?? i}
            source={s}
            index={i}
            isExpanded={expanded[s.id ?? `fallback-${i}`] ?? false}
            onToggle={onToggle}
          />
        ))}
      </div>

      {/* Footer */}
      <div className="border-t border-void-600 px-4 py-2.5">
        <p className="text-[9px] text-ink-faint">
          Cosine similarity · threshold {SIMILARITY_THRESHOLD} · v2 tri-modal
        </p>
      </div>
    </>
  )
}

/* ── Main RAG Panel ── */
export default memo(function RagPanel() {
  const { activeSession } = useSession()
  const { isLoading, ragPanelOpen, toggleRagPanel } = useUI()
  const [expanded, setExpanded] = useState({})

  const toggleExpand = useCallback((id) => {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }))
  }, [])

  const { videoSources, pdfSources, webSources, hasVideo, avgScore, intent } = useMemo(() => {
    const msgs   = activeSession?.messages ?? []
    const lastAI = [...msgs].reverse().find(m => m.role === 'assistant' && !m.isStreaming)
    const srcs   = lastAI?.ragSources  ?? []
    const web    = lastAI?.webSources  ?? []
    const int    = lastAI?.intent      ?? 'video'

    const videoSrcs = srcs.filter(s => s.type === 'video' || s.type === 'document')
    const pdfSrcs   = srcs.filter(s => s.type === 'pdf')
    const allSrcs   = [...srcs, ...web]
    const avg       = allSrcs.length
      ? Math.round(allSrcs.reduce((a, s) => a + (s.score ?? 0), 0) / allSrcs.length * 100)
      : 0

    return {
      videoSources: videoSrcs,
      pdfSources:   pdfSrcs,
      webSources:   web,
      hasVideo:     Boolean(lastAI?.video),
      avgScore:     avg,
      intent:       int,
    }
  }, [activeSession?.messages])

  const panelProps = { videoSources, pdfSources, webSources, avgScore, hasVideo, isLoading, expanded, onToggle: toggleExpand, intent }

  // Desktop panel
  const desktopPanel = (
    <aside
      className="w-72 shrink-0 hidden xl:flex flex-col bg-void-900 border-l border-void-600 overflow-hidden"
      aria-label="Knowledge sources panel"
    >
      <div className="px-4 pt-4 pb-3 border-b border-void-600">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-lg bg-violet/15 border border-violet/25 flex items-center justify-center">
            <DatabaseIcon size={12} className="text-violet" />
          </div>
          <h2 className="text-xs font-semibold text-ink">Knowledge Sources</h2>
          {(videoSources.length + pdfSources.length + webSources.length) > 0 && (
            <span className="ml-auto text-[10px] bg-violet/20 text-violet-light border border-violet/25 rounded-full px-2 py-0.5 font-medium tabular-nums">
              {videoSources.length + pdfSources.length + webSources.length}
            </span>
          )}
        </div>
      </div>
      <PanelContent {...panelProps} />
    </aside>
  )

  // Mobile drawer
  const mobileDrawer = ragPanelOpen ? (
    <div className="xl:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Knowledge sources">
      <div className="absolute inset-0 bg-void-950/80 backdrop-blur-sm" onClick={toggleRagPanel} aria-label="Close sources panel" />
      <div className="absolute bottom-0 left-0 right-0 max-h-[80dvh] bg-void-900 border-t border-void-600 rounded-t-2xl flex flex-col overflow-hidden animate-slide-up">
        <div className="flex justify-center pt-3 pb-1" aria-hidden="true">
          <div className="w-10 h-1 rounded-full bg-void-500" />
        </div>
        <div className="px-4 py-3 border-b border-void-600 flex items-center gap-2">
          <DatabaseIcon size={13} className="text-violet" />
          <h2 className="text-sm font-semibold text-ink">Knowledge Sources</h2>
          <button onClick={toggleRagPanel} className="ml-auto btn-icon" aria-label="Close sources panel">
            <XIcon size={16} />
          </button>
        </div>
        <PanelContent {...panelProps} />
      </div>
    </div>
  ) : null

  return (
    <>
      {desktopPanel}
      {mobileDrawer}
    </>
  )
})

/* ── Icons ── */
const DatabaseIcon    = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
const SearchIcon      = ({size=16,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
const ChevronIcon     = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><polyline points="6 9 12 15 18 9"/></svg>
const VideoIcon       = ({size=10,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
const FileTextIcon    = ({size=10,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
const GlobeIcon       = ({size=10,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
const FileIcon        = ({size=10,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
const ExternalLinkIcon= ({size=10,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
const XIcon           = ({size=14,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>

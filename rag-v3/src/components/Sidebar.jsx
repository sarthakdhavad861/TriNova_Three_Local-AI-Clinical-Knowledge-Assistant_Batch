import React, { memo, useCallback, useState, useRef, useEffect, useMemo } from 'react'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import { useToast } from './Toast.jsx'
import { MODELS } from '../utils/constants.js'
import { formatRelativeDate } from '../utils/formatters.js'

/* ── Session item with inline rename + confirm delete ── */
const SessionItem = memo(function SessionItem({ session, isActive, onSelect, onDelete, onRename }) {
  const [editing,    setEditing]   = useState(false)
  const [draft,      setDraft]     = useState(session.title)
  const [confirming, setConfirming]= useState(false)
  const inputRef   = useRef(null)
  const confirmRef = useRef(null)

  // Memoize the date string — only recomputes when updatedAt changes
  const dateStr = useMemo(() => formatRelativeDate(session.updatedAt), [session.updatedAt])

  useEffect(() => { if (editing) inputRef.current?.select() }, [editing])
  useEffect(() => { if (confirming) confirmRef.current?.focus() }, [confirming])

  // Reset draft when title changes externally
  useEffect(() => { if (!editing) setDraft(session.title) }, [session.title, editing])

  const commitRename = useCallback(() => {
    setEditing(false)
    const clean = draft.trim()
    if (clean && clean !== session.title) onRename(session.id, clean)
    else setDraft(session.title)
  }, [draft, session.id, session.title, onRename])

  const handleKey = useCallback((e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitRename() }
    if (e.key === 'Escape') { setEditing(false); setDraft(session.title) }
  }, [commitRename, session.title])

  const handleDeleteClick = useCallback((e) => {
    e.stopPropagation()
    setConfirming(true)
  }, [])

  const confirmDelete = useCallback((e) => {
    e.stopPropagation()
    setConfirming(false)
    onDelete(session.id)
  }, [session.id, onDelete])

  const cancelDelete = useCallback((e) => {
    e.stopPropagation()
    setConfirming(false)
  }, [])

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !editing && !confirming && onSelect(session.id)}
      onKeyDown={e => e.key === 'Enter' && !editing && !confirming && onSelect(session.id)}
      aria-current={isActive ? 'page' : undefined}
      aria-label={`Chat session: ${session.title}`}
      className={`
        group relative rounded-xl px-3 py-2.5 cursor-pointer transition-all duration-150 select-none
        focus-visible:ring-2 focus-visible:ring-violet outline-none
        ${isActive
          ? 'bg-violet/15 border border-violet/25 text-ink'
          : 'hover:bg-void-700 border border-transparent text-ink-muted hover:text-ink'}
      `}
    >
      {/* Rename input */}
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={handleKey}
          onClick={e => e.stopPropagation()}
          maxLength={80}
          aria-label="Rename session"
          className="w-full bg-void-600 border border-violet/40 rounded-lg px-2 py-0.5 text-xs text-ink outline-none focus:border-violet"
        />
      ) : confirming ? (
        /* Delete confirmation */
        <div onClick={e => e.stopPropagation()} className="space-y-1.5">
          <p className="text-[10px] text-rose font-medium">Delete this chat?</p>
          <div className="flex gap-1.5">
            <button
              ref={confirmRef}
              onClick={confirmDelete}
              className="flex-1 text-[10px] py-1 rounded-lg bg-rose/20 text-rose hover:bg-rose/30 transition-colors"
            >
              Delete
            </button>
            <button
              onClick={cancelDelete}
              className="flex-1 text-[10px] py-1 rounded-lg bg-void-600 text-ink-muted hover:text-ink transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        /* Normal display */
        <div className="flex items-start gap-2 min-w-0">
          <MsgIcon size={12} className={`mt-0.5 shrink-0 ${isActive ? 'text-violet' : 'text-ink-faint'}`} />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium truncate leading-snug">{session.title}</p>
            <p className="text-[10px] text-ink-faint mt-0.5 tabular-nums">
              {dateStr} · {session.messages.length}
            </p>
          </div>
        </div>
      )}

      {/* Action buttons (hover) */}
      {!editing && !confirming && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-0.5">
          <button
            onClick={e => { e.stopPropagation(); setEditing(true) }}
            aria-label="Rename session"
            className="p-1 rounded-md text-ink-faint hover:text-ink hover:bg-void-500 transition-all"
          ><PencilIcon size={11} /></button>
          <button
            onClick={handleDeleteClick}
            aria-label="Delete session"
            className="p-1 rounded-md text-ink-faint hover:text-rose hover:bg-rose/10 transition-all"
          ><TrashIcon size={11} /></button>
        </div>
      )}
    </div>
  )
})

/* ── Sidebar ── */
function SidebarContent({ onClose }) {
  const { sessions, activeSession, model, setModel, newSession, selectSession, deleteSession, renameSession } = useSession()
  const { toggleRagPanel, ragPanelOpen, toggleTheme } = useUI()
  const toast = useToast()

  const handleNewChat = useCallback(() => {
    newSession()
    onClose?.()
  }, [newSession, onClose])

  const handleSelect = useCallback((id) => {
    selectSession(id)
    onClose?.()
  }, [selectSession, onClose])

  const handleDelete = useCallback((id) => {
    deleteSession(id)
    toast('Chat deleted', 'info', 2500)
  }, [deleteSession, toast])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 pt-5 pb-3 border-b border-void-600">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet to-cyan flex items-center justify-center shadow-glow-sm shrink-0">
            <BrainIcon size={15} className="text-white" />
          </div>
          <div>
            <p className="text-xs font-semibold text-gradient leading-tight">RAG Assistant</p>
            <p className="text-[10px] text-ink-faint">AI-Powered</p>
          </div>
          {onClose && (
            <button onClick={onClose} className="ml-auto btn-icon" aria-label="Close sidebar">
              <XIcon size={16} />
            </button>
          )}
        </div>
        <button
          onClick={handleNewChat}
          className="btn-primary w-full justify-center text-xs py-2.5"
          aria-label="Start new chat"
        >
          <PlusIcon size={13} /> New Chat
        </button>
      </div>

      {/* Model selector */}
      <div className="px-3 pt-3 pb-2">
        <label htmlFor="model-select" className="text-[9px] uppercase tracking-widest text-ink-faint font-semibold block mb-1.5 px-1">
          Model
        </label>
        <select
          id="model-select"
          value={model}
          onChange={e => setModel(e.target.value)}
          className="w-full bg-void-800 border border-void-500 rounded-xl px-3 py-2 text-xs text-ink-muted focus:outline-none focus:border-violet/50 cursor-pointer"
          aria-label="Select AI model"
        >
          {MODELS.map(m => (
            <option key={m.id} value={m.id} className="bg-void-800">
              {m.label}  [{m.badge}]
            </option>
          ))}
        </select>
      </div>

      {/* Sessions */}
      <nav
        className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5 scrollbar-none"
        aria-label="Chat history"
      >
        <p className="text-[9px] uppercase tracking-widest text-ink-faint font-semibold px-2 mb-2">History</p>
        {sessions.length === 0 && (
          <p className="text-xs text-ink-faint text-center py-8">No conversations yet</p>
        )}
        {sessions.map(s => (
          <SessionItem
            key={s.id}
            session={s}
            isActive={s.id === activeSession?.id}
            onSelect={handleSelect}
            onDelete={handleDelete}
            onRename={renameSession}
          />
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-void-600 px-3 py-3 flex items-center gap-1">
        <button
          onClick={toggleRagPanel}
          aria-label={ragPanelOpen ? 'Hide sources panel' : 'Show sources panel'}
          aria-pressed={ragPanelOpen}
          className={`btn-ghost flex-1 text-xs justify-center py-1.5 ${ragPanelOpen ? 'text-violet' : ''}`}
        >
          <LayersIcon size={12} /> Sources
        </button>
        <div className="w-px h-4 bg-void-600" aria-hidden="true" />
        <button
          onClick={toggleTheme}
          aria-label="Toggle theme"
          className="btn-ghost flex-1 text-xs justify-center py-1.5"
        >
          <SunMoonIcon size={12} /> Theme
        </button>
      </div>
    </div>
  )
}

export default memo(function Sidebar() {
  const { sidebarOpen, toggleSidebar } = useUI()

  return (
    <>
      {/* Desktop sidebar */}
      <aside
        className={`
          hidden md:flex flex-col w-60 shrink-0 bg-void-900 border-r border-void-600 overflow-hidden
          transition-all duration-300 animate-slide-left
          ${sidebarOpen ? 'w-60' : 'w-0 border-0 overflow-hidden'}
        `}
        aria-label="Navigation sidebar"
        aria-hidden={!sidebarOpen}
      >
        {sidebarOpen && <SidebarContent />}
      </aside>

      {/* Mobile overlay sidebar */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Navigation sidebar">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-void-950/80 backdrop-blur-sm"
            onClick={toggleSidebar}
            aria-label="Close sidebar"
          />
          {/* Drawer */}
          <div className="absolute inset-y-0 left-0 w-72 bg-void-900 shadow-panel overflow-hidden animate-slide-left">
            <SidebarContent onClose={toggleSidebar} />
          </div>
        </div>
      )}
    </>
  )
})

/* ── Icons ── */
const BrainIcon   = ({size=15,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.46 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-1.14"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.46 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-1.14"/></svg>
const PlusIcon    = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><path d="M12 5v14M5 12h14"/></svg>
const TrashIcon   = ({size=11,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
const PencilIcon  = ({size=11,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
const LayersIcon  = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
const SunMoonIcon = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9"/></svg>
const MsgIcon     = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
const XIcon       = ({size=16,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>

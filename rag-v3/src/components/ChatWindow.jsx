import React, {
  memo, useCallback, useState, useEffect, useRef, lazy, Suspense
} from 'react'
import { Virtuoso } from 'react-virtuoso'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import MessageBubble from './MessageBubble.jsx'
import InputBox from './InputBox.jsx'
import { ErrorBoundary } from './ErrorBoundary.jsx'


/* ── Typing indicator ── */
const TypingIndicator = memo(function TypingIndicator() {
  return (
    <div className="flex items-start gap-3 px-4 py-2 animate-fade-in" aria-label="AI is thinking" role="status">
      <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-violet to-cyan flex items-center justify-center shrink-0 shadow-glow-sm" aria-hidden="true">
        <BotIcon size={13} className="text-white" />
      </div>
      <div className="glass rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-1.5">
        <span className="typing-dot" aria-hidden="true" />
        <span className="typing-dot" aria-hidden="true" />
        <span className="typing-dot" aria-hidden="true" />
      </div>
    </div>
  )
})

/* ── Empty state ── */
const EmptyState = memo(function EmptyState() {
  const { suggestions, health } = useSession()
  const { setDraft, setKnowledgeOpen } = useUI()
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 text-center py-12 animate-slide-up">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet/20 to-cyan/10 border border-violet/20 flex items-center justify-center mb-5 shadow-glow-sm text-violet text-xl font-bold" aria-hidden="true">Rx</div>
      <h2 className="text-xl font-semibold text-ink mb-2 text-balance">Clinical reference, from your own documents</h2>
      <p className="text-sm text-ink-muted max-w-md leading-relaxed mb-6">
        Ask about medicines, medical equipment or symptoms. Every answer cites the ingested source it came from, structured records are shown
        verbatim, and the assistant says so when the knowledge base has nothing reliable.
      </p>
      {health.ok && health.sources === 0 && (
        <button onClick={() => setKnowledgeOpen(true)} className="mb-6 text-xs px-4 py-2.5 rounded-xl border border-amber/40 bg-amber/10 text-amber hover:bg-amber/20 transition-all">
          The knowledge base is empty — add reference documents first
        </button>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg w-full" role="list" aria-label="Question templates">
        {(suggestions ?? []).slice(0, 4).map((s, i) => (
          <button key={i} role="listitem" onClick={() => { setDraft(s); document.getElementById('chat-input')?.focus() }}
            className="text-left text-xs px-3.5 py-3 rounded-xl border border-void-500 text-ink-muted hover:border-violet/30 hover:text-ink hover:bg-void-700 transition-all duration-150 focus-visible:ring-2 focus-visible:ring-violet">
            {s}
          </button>
        ))}
      </div>
      <p className="text-[10px] text-ink-faint mt-3">Templates fill the question box — replace the &lt;placeholder&gt; with a name from your documents.</p>
    </div>
  )
})

/* ── Offline banner ── */
const OfflineBanner = memo(function OfflineBanner() {
  return (
    <div
      className="mx-4 mb-2 px-4 py-2.5 rounded-xl border border-amber/25 bg-amber/10 text-amber text-xs flex items-center gap-2 animate-fade-in"
      role="alert"
      aria-live="assertive"
    >
      <WifiOffIcon size={13} className="shrink-0" />
      You are offline — responses may not be available
    </div>
  )
})

/* ── Error banner ── */
const ErrorBanner = memo(function ErrorBanner({ error, onDismiss }) {
  return (
    <div
      className="mx-4 mb-2 px-4 py-2.5 rounded-xl border border-rose/25 bg-rose/10 text-rose text-xs flex items-center gap-2 animate-fade-in"
      role="alert"
      aria-live="polite"
    >
      <AlertIcon size={13} className="shrink-0" />
      <span className="flex-1">{error}</span>
      <button
        onClick={onDismiss}
        aria-label="Dismiss error"
        className="shrink-0 hover:text-rose/60 transition-colors p-0.5"
      >
        <XIcon size={12} />
      </button>
    </div>
  )
})

/* ── Toolbar ── */
const Toolbar = memo(function Toolbar() {
  const { activeEncounter, messages, loadingEncounter } = useSession()
  const { toggleSidebar, toggleRagPanel, ragPanelOpen, isLoading } = useUI()
  const msgCount = messages.length
  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-void-600 bg-void-900/80 backdrop-blur-sm shrink-0">
      <button onClick={toggleSidebar} aria-label="Toggle sidebar" className="btn-icon text-ink-muted"><MenuIcon size={16} /></button>
      <div className="flex-1 min-w-0">
        <h1 className="text-sm font-semibold text-ink truncate leading-tight">{activeEncounter?.label || 'No encounter selected'}</h1>
        <p className="text-[10px] text-ink-faint tabular-nums">
          {msgCount} {msgCount === 1 ? 'message' : 'messages'}{loadingEncounter && ' · loading…'}{isLoading && ' · working…'}
        </p>
      </div>
      <button onClick={toggleRagPanel} aria-label={ragPanelOpen ? 'Hide side panel' : 'Show side panel'} aria-pressed={ragPanelOpen}
        className={`btn-ghost text-xs py-1.5 ${ragPanelOpen ? 'text-violet' : ''}`}><LayersIcon size={13} /> Sources &amp; context</button>
    </div>
  )
})

/* ── Scroll to bottom button with unread badge ── */
const ScrollToBottomBtn = memo(function ScrollToBottomBtn({ onClick, unreadCount }) {
  return (
    <button
      onClick={onClick}
      aria-label={`Scroll to latest messages${unreadCount > 0 ? ` (${unreadCount} new)` : ''}`}
      className="absolute bottom-4 right-4 flex items-center gap-1.5 px-3 py-1.5 rounded-full glass border border-void-500 text-xs text-ink-muted hover:text-ink hover:border-violet/40 hover:shadow-glow-sm transition-all duration-200 animate-fade-in"
    >
      <ChevronDownIcon size={13} />
      {unreadCount > 0
        ? <span className="font-semibold text-violet tabular-nums">{unreadCount} new</span>
        : 'Latest'}
    </button>
  )
})

/* ── Main ChatWindow ── */
export default function ChatWindow() {
  const { messages: msgs } = useSession()
  const { isLoading, isStreaming, error, clearError } = useUI()

  const [showScrollBtn, setShowScrollBtn]   = useState(false)
  const [unreadCount,   setUnreadCount]     = useState(0)
  const [isOnline,      setIsOnline]        = useState(navigator.onLine)

  const virtuosoRef   = useRef(null)
  const atBottomRef   = useRef(true)
  const prevLengthRef = useRef(0)

  const messages    = msgs
  const hasMessages = messages.length > 0

  /* Online/offline detection */
  useEffect(() => {
    const onOnline  = () => setIsOnline(true)
    const onOffline = () => setIsOnline(false)
    window.addEventListener('online',  onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online',  onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  /* Track unread messages when scrolled away */
  useEffect(() => {
    const newLen = messages.length
    const prev   = prevLengthRef.current
    if (newLen > prev && !atBottomRef.current) {
      setUnreadCount(c => c + (newLen - prev))
    }
    prevLengthRef.current = newLen
  }, [messages.length])

  /* Auto-scroll during streaming if at bottom */
  useEffect(() => {
    if ((isStreaming || isLoading) && atBottomRef.current) {
      virtuosoRef.current?.scrollToIndex({
        index:    messages.length - 1,
        behavior: 'smooth',
      })
    }
  }, [messages.length, isStreaming, isLoading])

  const scrollToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({
      index:    messages.length - 1,
      behavior: 'smooth',
    })
    setUnreadCount(0)
    setShowScrollBtn(false)
    atBottomRef.current = true
  }, [messages.length])

  const handleAtBottomChange = useCallback((atBottom) => {
    atBottomRef.current = atBottom
    setShowScrollBtn(!atBottom)
    if (atBottom) setUnreadCount(0)
  }, [])

  const dismissError = useCallback(() => clearError(), [clearError])

  /* Virtuoso item renderer */
  const itemContent = useCallback((index, message) => (
    <ErrorBoundary key={message.id}>
      <MessageBubble
        message={message}
        isLast={index === messages.length - 1}
      />
    </ErrorBoundary>
  ), [messages.length])

  /* Footer — typing indicator rendered as Virtuoso footer */
  const Footer = useCallback(() => (
    <>
      {isLoading && !isStreaming && <TypingIndicator />}
      <div className="h-2" aria-hidden="true" />
    </>
  ), [isLoading, isStreaming])

  return (
    <div className="flex flex-col h-full min-w-0 overflow-hidden">
      <Toolbar />

      {/* Banners */}
      {!isOnline && <OfflineBanner />}

      {/* Message area */}
      <div className="flex-1 relative min-h-0">
        {!hasMessages ? (
          <div className="h-full overflow-y-auto">
            <EmptyState />
          </div>
        ) : (
          <Virtuoso
            ref={virtuosoRef}
            data={messages}
            itemContent={itemContent}
            components={{ Footer }}
            followOutput="auto"
            atBottomStateChange={handleAtBottomChange}
            increaseViewportBy={{ top: 400, bottom: 400 }}
            overscan={8}
            className="h-full"
            role="log"
            aria-label="Chat messages"
            aria-live="polite"
            aria-atomic="false"
            style={{ height: '100%' }}
          />
        )}

        {/* Error banner — above scroll btn */}
        {error && (
          <div className="absolute bottom-4 left-4 right-16 z-10">
            <ErrorBanner error={error} onDismiss={dismissError} />
          </div>
        )}

        {/* Scroll to bottom */}
        {showScrollBtn && (
          <ScrollToBottomBtn onClick={scrollToBottom} unreadCount={unreadCount} />
        )}
      </div>

      <InputBox />
    </div>
  )
}

/* ── Icons ── */
const BotIcon        = ({size=14,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
const SparklesIcon   = ({size=24,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M12 3l1.9 5.4L19 10l-5.1 1.6L12 17l-1.9-5.4L5 10l5.1-1.6z"/><path d="M5 3l.9 2.4L8 6l-2.1.6L5 9l-.9-2.4L2 6l2.1-.6z"/><path d="M19 14l.9 2.4L22 17l-2.1.6L19 20l-.9-2.4L16 17l2.1-.6z"/></svg>
const MenuIcon       = ({size=16,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className={className}><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
const TrashIcon      = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
const LayersIcon     = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
const AlertIcon      = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
const WifiOffIcon    = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/><path d="M10.71 5.05A16 16 0 0 1 22.56 9"/><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
const XIcon          = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
const ChevronDownIcon= ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><polyline points="6 9 12 15 18 9"/></svg>

import React, { memo, useState, useCallback, lazy, Suspense } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import CodeBlock from './CodeBlock.jsx'
import { ErrorBoundary } from './ErrorBoundary.jsx'
import { useSession } from '../context/SessionContext.jsx'
import { useToast } from './Toast.jsx'
import { formatTimestamp } from '../utils/formatters.js'

const VideoPlayer = lazy(() => import('./VideoPlayer.jsx'))

/* ── Markdown component map — stable reference (outside component) ── */
const MD_COMPONENTS = {
  code({ node, inline, className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    if (!inline && match) return <CodeBlock language={match[1]}>{children}</CodeBlock>
    return (
      <code
        className="bg-void-600 text-cyan px-1.5 py-0.5 rounded text-[0.81em] font-mono border border-void-500"
        {...props}
      >
        {children}
      </code>
    )
  },
  table: ({ children }) => (
    <div className="overflow-x-auto my-3 rounded-lg border border-void-500">
      <table className="w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-void-500 px-3 py-2 bg-void-700 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border border-void-500 px-3 py-2">{children}</td>
  ),
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
  ),
}

/* ── Message skeleton ── */
function MessageSkeleton() {
  return (
    <div className="space-y-2 py-1">
      <div className="skeleton h-3 w-3/4 rounded" />
      <div className="skeleton h-3 w-full rounded" />
      <div className="skeleton h-3 w-5/6 rounded" />
      <div className="skeleton h-3 w-2/5 rounded" />
    </div>
  )
}

/* ── Message error ── */
function MessageError({ error }) {
  return (
    <div className="flex items-center gap-2 text-rose text-xs px-3 py-2.5 bg-rose/10 border border-rose/20 rounded-xl">
      <AlertIcon size={13} className="shrink-0" />
      <span>{error}</span>
    </div>
  )
}

/* ── Actions bar ── */
const MessageActions = memo(function MessageActions({ content, onFeedback, feedback, onRetry, showRetry }) {
  const toast = useToast()

  const copy = useCallback(async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(content)
      } else {
        const el = document.createElement('textarea')
        el.value = content
        el.style.cssText = 'position:fixed;top:-9999px'
        document.body.appendChild(el)
        el.select(); document.execCommand('copy')
        document.body.removeChild(el)
      }
      toast('Copied to clipboard', 'success', 2000)
    } catch {
      toast('Copy failed', 'error', 2000)
    }
  }, [content, toast])

  return (
    <div
      className="flex items-center gap-0.5 mt-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200"
      role="toolbar"
      aria-label="Message actions"
    >
      <button
        onClick={copy}
        aria-label="Copy message"
        className="flex items-center gap-1 text-[10px] text-ink-faint hover:text-ink px-2 py-1 rounded-lg hover:bg-void-600 transition-all"
      >
        <CopyIcon size={10} /> Copy
      </button>
      <button
        onClick={() => onFeedback('up')}
        aria-label="Mark helpful"
        aria-pressed={feedback === 'up'}
        className={`p-1.5 rounded-lg transition-all hover:bg-void-600 ${feedback === 'up' ? 'text-emerald' : 'text-ink-faint hover:text-ink'}`}
      >
        <ThumbUpIcon size={11} />
      </button>
      <button
        onClick={() => onFeedback('down')}
        aria-label="Mark not helpful"
        aria-pressed={feedback === 'down'}
        className={`p-1.5 rounded-lg transition-all hover:bg-void-600 ${feedback === 'down' ? 'text-rose' : 'text-ink-faint hover:text-ink'}`}
      >
        <ThumbDownIcon size={11} />
      </button>
      {showRetry && (
        <button
          onClick={onRetry}
          aria-label="Retry response"
          className="flex items-center gap-1 text-[10px] text-ink-faint hover:text-violet px-2 py-1 rounded-lg hover:bg-void-600 transition-all"
        >
          <RetryIcon size={10} /> Retry
        </button>
      )}
    </div>
  )
})

/* ── Main MessageBubble — custom memo equality check ── */
function MessageBubbleInner({ message, isLast }) {
  const { retryLast } = useSession()
  const [feedback, setFeedback] = useState(null)
  const isUser = message.role === 'user'
  const ts = formatTimestamp(message.timestamp)

  const handleFeedback = useCallback((v) => {
    setFeedback(p => p === v ? null : v)
  }, [])

  /* User bubble */
  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-1 animate-slide-up">
        <div className="max-w-[76%] min-w-0">
          <div
            className="bg-gradient-to-br from-violet to-violet-dark text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed shadow-glow-sm break-anywhere"
          >
            {message.content}
          </div>
          <p className="text-[10px] text-ink-faint text-right mt-1 pr-1" aria-label={`Sent at ${ts}`}>{ts}</p>
        </div>
      </div>
    )
  }

  /* AI bubble */
  return (
    <div className="group flex items-start gap-3 px-4 py-1 animate-slide-up">
      {/* Avatar */}
      <div
        className="w-7 h-7 rounded-xl bg-gradient-to-br from-violet to-cyan flex items-center justify-center shrink-0 mt-1 shadow-glow-sm"
        aria-hidden="true"
      >
        <BotIcon size={13} className="text-white" />
      </div>

      <div className="flex-1 min-w-0">
        {/* Bubble */}
        <div className="glass rounded-2xl rounded-tl-sm px-4 py-3">
          {message.error ? (
            <MessageError error={message.error} />
          ) : (message.isStreaming && !message.content) ? (
            <MessageSkeleton />
          ) : (
            <div className="prose-ai">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSanitize]}
                components={MD_COMPONENTS}
              >
                {message.content || ''}
              </ReactMarkdown>
              {/* Inline streaming cursor — span element, not ::after pseudo */}
              {message.isStreaming && <span className="stream-cursor" aria-hidden="true" />}
            </div>
          )}
        </div>

        <p className="text-[10px] text-ink-faint mt-1 pl-1">{ts}</p>

        {/* Actions — only when done */}
        {!message.isStreaming && !message.error && (
          <MessageActions
            content={message.content}
            onFeedback={handleFeedback}
            feedback={feedback}
            onRetry={retryLast}
            showRetry={isLast}
          />
        )}

        {/* Video player — lazy, wrapped in ErrorBoundary */}
        {message.video && !message.isStreaming && (
          <div className="mt-3">
            <ErrorBoundary fallback={() => (
              <div className="text-xs text-ink-faint px-3 py-2 rounded-xl border border-void-600 bg-void-800">
                Video preview could not be loaded.
              </div>
            )}>
              <Suspense fallback={<div className="skeleton h-48 w-full rounded-2xl" />}>
                <VideoPlayer video={message.video} />
              </Suspense>
            </ErrorBoundary>
          </div>
        )}
      </div>
    </div>
  )
}

/* Custom equality — only re-render when content/streaming/error/isLast changes */
const MessageBubble = memo(MessageBubbleInner, (prev, next) =>
  prev.message.content     === next.message.content &&
  prev.message.isStreaming === next.message.isStreaming &&
  prev.message.error       === next.message.error &&
  prev.message.video       === next.message.video &&
  prev.isLast              === next.isLast
)

export default MessageBubble

/* ── Icons ── */
const BotIcon       = ({size=14,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/></svg>
const CopyIcon      = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
const ThumbUpIcon   = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
const ThumbDownIcon = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
const RetryIcon     = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.91"/></svg>
const AlertIcon     = ({size=14,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>

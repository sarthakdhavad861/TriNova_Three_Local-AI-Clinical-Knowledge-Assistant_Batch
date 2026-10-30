import React, { memo, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import CodeBlock from './CodeBlock.jsx'
import { Notices, RecordCards, TrustLine } from './ClinicalBlocks.jsx'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import { useToast } from './Toast.jsx'
import { formatTimestamp } from '../utils/formatters.js'

/* Markdown component map — stable reference (outside component). The answer text is untrusted model output:
   rehype-sanitize strips raw HTML; links open in a new tab without referrer. */
const MD_COMPONENTS = {
  code({ node, inline, className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    if (!inline && match) return <CodeBlock language={match[1]}>{children}</CodeBlock>
    return <code className="bg-void-600 text-cyan px-1.5 py-0.5 rounded text-[0.81em] font-mono border border-void-500" {...props}>{children}</code>
  },
  table: ({ children }) => (
    <div className="overflow-x-auto my-3 rounded-lg border border-void-500"><table className="w-full text-xs border-collapse">{children}</table></div>
  ),
  th: ({ children }) => <th className="border border-void-500 px-3 py-2 bg-void-700 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border border-void-500 px-3 py-2">{children}</td>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
}

function MessageSkeleton() {
  return (
    <div className="space-y-2 py-1" role="status" aria-label="Searching the knowledge base">
      <div className="skeleton h-3 w-3/4 rounded" /><div className="skeleton h-3 w-full rounded" /><div className="skeleton h-3 w-2/5 rounded" />
    </div>
  )
}

function MessageError({ error }) {
  return (
    <div role="alert" className="flex items-start gap-2 text-rose text-xs px-3 py-2.5 bg-rose/10 border border-rose/20 rounded-xl">
      <span aria-hidden="true">⚠</span><span className="break-words">{error}</span>
    </div>
  )
}

const MessageActions = memo(function MessageActions({ text, onRetry, showRetry }) {
  const toast = useToast()
  const copy = useCallback(async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text)
      else {
        const el = document.createElement('textarea')
        el.value = text; el.style.cssText = 'position:fixed;top:-9999px'
        document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el)
      }
      toast('Copied to clipboard', 'success', 2000)
    } catch { toast('Copy failed', 'error', 2000) }
  }, [text, toast])
  return (
    <div className="flex items-center gap-1 mt-2" role="toolbar" aria-label="Message actions">
      <button onClick={copy} className="text-[10px] text-ink-faint hover:text-ink px-2 py-1 rounded-lg hover:bg-void-600 transition-all">Copy answer</button>
      {showRetry && <button onClick={onRetry} className="text-[10px] text-ink-faint hover:text-violet px-2 py-1 rounded-lg hover:bg-void-600 transition-all">Ask again</button>}
    </div>
  )
})

function MessageBubbleInner({ message, isLast }) {
  const { retryLast } = useSession()
  const { showSources } = useUI()
  const isUser = message.role === 'user'
  const ts = formatTimestamp(message.timestamp)
  const onShowSources = useCallback(() => showSources(message.id), [showSources, message.id])

  if (isUser) {
    return (
      <div className="flex justify-end px-4 py-1 animate-slide-up">
        <div className="max-w-[76%] min-w-0">
          <div className="bg-gradient-to-br from-violet to-violet-dark text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed shadow-glow-sm break-anywhere whitespace-pre-wrap">
            {message.content}
          </div>
          <p className="text-[10px] text-ink-faint text-right mt-1 pr-1">{ts}</p>
        </div>
      </div>
    )
  }

  const waiting = message.isStreaming && !message.content && !message.notices.length && !message.recordViews?.length
  const copyText = [message.content].filter(Boolean).join('\n')
  return (
    <div className="flex items-start gap-3 px-4 py-1 animate-slide-up" data-testid="assistant-message">
      <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-violet to-cyan flex items-center justify-center shrink-0 mt-1 text-white text-[11px] font-bold" aria-hidden="true">Rx</div>
      <div className="flex-1 min-w-0">
        <div className="glass rounded-2xl rounded-tl-sm px-4 py-3">
          {message.error ? <MessageError error={message.error} /> : waiting ? <MessageSkeleton /> : (
            <>
              <Notices notices={message.notices} />
              <RecordCards views={message.recordViews} disclaimer={message.disclaimer} />
              {(message.content || message.isStreaming) && (
                <div className="prose-ai">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={MD_COMPONENTS}>
                    {message.content || ''}
                  </ReactMarkdown>
                  {message.isStreaming && <span className="stream-cursor" aria-hidden="true" />}
                </div>
              )}
              {!message.isStreaming && <TrustLine message={message} onShowSources={onShowSources} />}
            </>
          )}
        </div>
        <p className="text-[10px] text-ink-faint mt-1 pl-1">{ts}</p>
        {!message.isStreaming && (message.content || message.error) && (
          <MessageActions text={copyText} onRetry={retryLast} showRetry={isLast} />
        )}
      </div>
    </div>
  )
}

/* Messages are replaced (never mutated) on every update, so identity comparison is exact. */
export default memo(MessageBubbleInner, (a, b) => a.message === b.message && a.isLast === b.isLast)

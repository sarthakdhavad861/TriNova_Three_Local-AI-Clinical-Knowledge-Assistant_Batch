import React, { memo, useState, useCallback, useEffect } from 'react'

/**
 * CodeBlock — lazy loads SyntaxHighlighter via useEffect (no Suspense needed).
 * Falls back to plain <pre> while loading.
 * Handles both HTTPS clipboard and HTTP fallback.
 */
const CodeContent = memo(function CodeContent({ language, code }) {
  const [SHL,   setSHL]   = useState(null)
  const [theme, setTheme] = useState(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      import('react-syntax-highlighter').then(m => m.Prism),
      import('react-syntax-highlighter/dist/esm/styles/prism').then(m => m.oneDark),
    ]).then(([Comp, style]) => {
      if (!cancelled) { setSHL(() => Comp); setTheme(style) }
    })
    return () => { cancelled = true }
  }, [])

  if (!SHL || !theme) {
    return (
      <pre className="px-4 py-3 m-0 overflow-x-auto text-cyan text-[0.78rem] font-mono leading-relaxed">
        <code>{code}</code>
      </pre>
    )
  }

  return (
    <SHL
      style={theme}
      language={language || 'text'}
      PreTag="div"
      wrapLongLines
      customStyle={{
        margin: 0, borderRadius: 0, background: '#060612',
        fontSize: '0.78rem', lineHeight: 1.65, padding: '0.75rem 1rem',
      }}
    >
      {code}
    </SHL>
  )
})

const CodeBlock = memo(function CodeBlock({ language, children }) {
  const [copied, setCopied] = useState(false)
  const code = String(children).replace(/\n$/, '')

  const copy = useCallback(async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(code)
      } else {
        const el = document.createElement('textarea')
        el.value = code
        el.style.cssText = 'position:fixed;top:-9999px;left:-9999px'
        document.body.appendChild(el)
        el.focus(); el.select()
        document.execCommand('copy')
        document.body.removeChild(el)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* silent */ }
  }, [code])

  return (
    <div className="relative group my-3 rounded-xl overflow-hidden border border-void-500">
      <div className="flex items-center justify-between px-4 py-2 bg-void-800 border-b border-void-600">
        <span className="text-[10px] font-mono text-ink-faint uppercase tracking-wider select-none">
          {language || 'code'}
        </span>
        <button
          onClick={copy}
          aria-label={copied ? 'Copied' : 'Copy code'}
          className="flex items-center gap-1 text-[10px] text-ink-faint hover:text-ink px-1.5 py-0.5 rounded hover:bg-void-600 transition-colors"
        >
          {copied
            ? <><CheckIcon size={10} className="text-emerald" /> Copied!</>
            : <><CopyIcon  size={10} /> Copy</>}
        </button>
      </div>
      <CodeContent language={language} code={code} />
    </div>
  )
})

export default CodeBlock

const CopyIcon  = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
const CheckIcon = ({size=11,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><polyline points="20 6 9 17 4 12"/></svg>

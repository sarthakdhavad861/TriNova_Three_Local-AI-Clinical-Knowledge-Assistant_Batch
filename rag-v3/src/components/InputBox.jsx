import React, { useState, useRef, useCallback, useEffect, memo } from 'react'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import { sanitizeInput } from '../utils/formatters.js'
import { validateQuestion } from '../utils/clinical.js'
import { MAX_INPUT_CHARS } from '../utils/constants.js'

export default memo(function InputBox() {
  const { sendMessage, stopGeneration, health, activeEncounter } = useSession()
  const { isLoading, draft, setDraft } = useUI()
  const [problem, setProblem] = useState(null)
  const textareaRef  = useRef(null)
  const composingRef = useRef(false)

  const value = draft
  const charCount = value.length
  const overLimit = charCount > MAX_INPUT_CHARS
  const canSend = value.trim().length > 0 && !isLoading && !overLimit
  const offline = health.ok === false

  useEffect(() => {                                   // auto-resize
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 180) + 'px'
    el.style.overflowY = el.scrollHeight > 180 ? 'auto' : 'hidden'
  }, [value])

  const handleSend = useCallback(() => {
    const p = validateQuestion(value)
    setProblem(p)
    if (p || isLoading) return
    sendMessage(value.trim())
    setDraft('')
    requestAnimationFrame(() => textareaRef.current?.focus())
  }, [value, isLoading, sendMessage, setDraft])

  const handleKeyDown = useCallback((e) => {
    if (e.isComposing || composingRef.current) return
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
    if (e.key === 'Escape' && isLoading) stopGeneration()
  }, [handleSend, isLoading, stopGeneration])

  return (
    <div className="px-4 pb-4 pt-2 safe-bottom">
      {problem && <p className="mb-1.5 text-xs text-rose" role="alert">{problem}</p>}
      {offline && <p className="mb-1.5 text-xs text-rose" role="alert">Backend not reachable — start it with <code>uvicorn Main:app --port 8000</code>.</p>}
      <div className={`glass rounded-2xl transition-all duration-200 ${canSend ? 'border-violet/35 shadow-glow-sm' : ''} ${overLimit ? 'border-rose/40' : ''}`}>
        <textarea
          ref={textareaRef} id="chat-input" value={value} rows={1} enterKeyHint="send"
          onChange={e => { setDraft(sanitizeInput(e.target.value).slice(0, MAX_INPUT_CHARS + 200)); setProblem(null) }}
          onKeyDown={handleKeyDown}
          onCompositionStart={() => { composingRef.current = true }} onCompositionEnd={() => { composingRef.current = false }}
          disabled={isLoading} aria-label="Question" aria-invalid={overLimit}
          aria-describedby={charCount > MAX_INPUT_CHARS * 0.7 ? 'char-counter' : undefined}
          placeholder={isLoading ? 'Searching the knowledge base and generating…' : 'Ask about a medicine, a piece of equipment or a symptom…'}
          className="w-full bg-transparent resize-none px-4 pt-3 pb-1 text-sm text-ink placeholder-ink-faint focus:outline-none leading-relaxed min-h-[44px] max-h-[180px] scrollbar-none disabled:cursor-not-allowed"
        />
        <div className="flex items-center gap-2 px-3 pb-2.5 pt-1">
          <span className="text-[10px] text-ink-faint truncate">{activeEncounter ? `Encounter: ${activeEncounter.label || 'untitled'}` : 'No encounter — one is created when you send'}</span>
          {charCount > MAX_INPUT_CHARS * 0.7 && (
            <span id="char-counter" aria-live="polite" className={`text-[10px] font-mono tabular-nums ${overLimit ? 'text-rose' : 'text-ink-faint'}`}>{charCount}/{MAX_INPUT_CHARS}</span>
          )}
          <div className="flex-1" />
          {isLoading ? (
            <button onClick={stopGeneration} aria-label="Stop generation" className="px-3 h-8 rounded-xl bg-rose/20 border border-rose/30 text-rose text-xs hover:bg-rose/30 transition-all shrink-0">Stop</button>
          ) : (
            <button onClick={handleSend} disabled={!canSend} aria-label="Send question"
              className={`px-3 h-8 rounded-xl text-xs font-semibold transition-all shrink-0 ${canSend ? 'bg-violet hover:bg-violet-light text-white shadow-glow-sm' : 'bg-void-700 text-ink-faint cursor-not-allowed'}`}>
              Ask
            </button>
          )}
        </div>
      </div>
      <p className="text-[10px] text-ink-faint text-center mt-1.5">
        Reference tool — not a diagnostic or prescribing system and not for emergencies. Answers come only from the ingested documents; verify against the source.
      </p>
    </div>
  )
})

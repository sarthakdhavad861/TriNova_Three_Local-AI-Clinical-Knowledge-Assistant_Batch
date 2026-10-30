import React, { memo, useState, useCallback } from 'react'
import { useSession } from '../context/SessionContext.jsx'
import { validateNote } from '../utils/clinical.js'
import { MAX_NOTE_CHARS } from '../utils/constants.js'

/* Private context for ONE encounter. It is sent to the local model only inside this encounter, is never a citable
   source, is never indexed with the knowledge base, and is erased with the encounter. */
export default memo(function ContextPanel({ encounter }) {
  const { notes, addNote, removeNote } = useSession()
  const [text, setText] = useState('')
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = useCallback(async (e) => {
    e.preventDefault()
    const p = validateNote(text)
    setProblem(p)
    if (p) return
    setBusy(true)
    const ok = await addNote(text)
    setBusy(false)
    if (ok) setText('')
  }, [text, addNote])

  if (!encounter) {
    return <div className="flex-1 px-4 py-10 text-center text-xs text-ink-faint">Start an encounter to add patient context.</div>
  }
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <p className="mx-3 mt-3 px-3 py-2 rounded-lg border border-amber/30 bg-amber/10 text-[10px] text-amber leading-relaxed">
        Use synthetic or non-identifying information only. Notes stay on this machine, are used only for this encounter,
        are never cited as evidence, and are erased with the encounter (or automatically after the server's expiry time).
      </p>
      <ul className="flex-1 overflow-y-auto px-3 py-2 space-y-2" aria-label="Context notes">
        {notes.length === 0 && <li className="text-center text-[11px] text-ink-faint py-6">No context notes yet.</li>}
        {notes.map(n => (
          <li key={n.note_id} className="rounded-xl border border-void-500 bg-void-800 p-2.5 text-[11px] text-ink whitespace-pre-wrap break-words flex gap-2">
            <span className="flex-1">{n.text}</span>
            <button onClick={() => removeNote(n.note_id)} aria-label="Delete note" className="text-ink-faint hover:text-rose self-start">✕</button>
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="px-3 pb-3 space-y-1.5" noValidate>
        <label htmlFor="ctx-note" className="sr-only">New context note</label>
        <textarea id="ctx-note" value={text} onChange={e => { setText(e.target.value.slice(0, MAX_NOTE_CHARS + 50)); setProblem(null) }} rows={3}
          placeholder="e.g. synthetic note: adult, impaired renal function" aria-invalid={Boolean(problem)}
          className="w-full bg-void-800 border border-void-500 rounded-xl px-3 py-2 text-xs text-ink placeholder-ink-faint focus:outline-none focus:border-violet/50 resize-none" />
        <div className="flex items-center gap-2">
          <span className={`text-[10px] tabular-nums ${text.length > MAX_NOTE_CHARS ? 'text-rose' : 'text-ink-faint'}`}>{text.length}/{MAX_NOTE_CHARS}</span>
          {problem && <span className="text-[10px] text-rose" role="alert">{problem}</span>}
          <button type="submit" disabled={busy} className="btn-primary ml-auto text-xs py-1.5 px-3">{busy ? 'Adding…' : 'Add note'}</button>
        </div>
      </form>
    </div>
  )
})

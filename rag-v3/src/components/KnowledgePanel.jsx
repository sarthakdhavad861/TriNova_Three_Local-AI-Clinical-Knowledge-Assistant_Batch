import React, { memo, useEffect, useState, useCallback, useRef } from 'react'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import { validateUpload } from '../utils/clinical.js'
import { ACCEPTED_DOC_TYPES, CATEGORIES } from '../utils/constants.js'

/* Knowledge-base dialog: what is ingested (with provenance) + adding reference documents. Licence and origin are
   mandatory here so every document in the demo has recorded provenance. */
export default memo(function KnowledgePanel() {
  const { knowledgeOpen, setKnowledgeOpen, uploadStatus, uploadMessage, resetUpload } = useUI()
  const { knowledge, refreshKnowledge, uploadDocument } = useSession()
  const [file, setFile] = useState(null)
  const [category, setCategory] = useState('')
  const [license, setLicense] = useState('')
  const [origin, setOrigin] = useState('')
  const [problem, setProblem] = useState(null)
  const closeRef = useRef(null)
  const busy = uploadStatus === 'uploading' || uploadStatus === 'processing'

  useEffect(() => { if (knowledgeOpen) { refreshKnowledge(); resetUpload(); closeRef.current?.focus() } }, [knowledgeOpen]) // eslint-disable-line
  useEffect(() => {
    if (!knowledgeOpen) return
    const onKey = (e) => { if (e.key === 'Escape' && !busy) setKnowledgeOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [knowledgeOpen, busy, setKnowledgeOpen])

  const submit = useCallback(async (e) => {
    e.preventDefault()
    const p = validateUpload({ file, category, license, origin })
    setProblem(p)
    if (p) return
    if (await uploadDocument({ file, category, license, origin })) { setFile(null); setLicense(''); setOrigin('') }
  }, [file, category, license, origin, uploadDocument])

  if (!knowledgeOpen) return null
  const field = 'w-full bg-void-800 border border-void-500 rounded-xl px-3 py-2 text-xs text-ink placeholder-ink-faint focus:outline-none focus:border-violet/50'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="kb-title">
      <div className="absolute inset-0 bg-void-950/80 backdrop-blur-sm" onClick={() => !busy && setKnowledgeOpen(false)} />
      <div className="relative w-full max-w-3xl max-h-[88dvh] overflow-y-auto bg-void-900 border border-void-500 rounded-2xl shadow-panel p-5 space-y-5">
        <header className="flex items-center gap-3">
          <h2 id="kb-title" className="text-sm font-semibold text-ink">Knowledge base</h2>
          {knowledge.totals && <span className="text-[10px] text-ink-faint">{knowledge.totals.sources} sources · {knowledge.totals.chunks} passages · {knowledge.totals.records} records</span>}
          <button ref={closeRef} onClick={() => setKnowledgeOpen(false)} disabled={busy} className="btn-icon ml-auto" aria-label="Close">✕</button>
        </header>

        <section aria-label="Ingested sources">
          {knowledge.loading && <div className="skeleton h-16 rounded-xl" role="status" aria-label="Loading sources" />}
          {knowledge.error && <p className="text-xs text-rose" role="alert">Could not load sources: {knowledge.error}</p>}
          {!knowledge.loading && !knowledge.error && knowledge.sources.length === 0 && (
            <p className="text-xs text-amber border border-amber/30 bg-amber/10 rounded-xl px-3 py-2.5">
              The knowledge base is empty — questions cannot be answered until you add reference documents below.
            </p>
          )}
          <ul className="space-y-1.5">
            {knowledge.sources.map(s => (
              <li key={s.source_id} className="rounded-xl border border-void-500 bg-void-800 px-3 py-2 text-[11px]">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium text-ink break-all">{s.display_name}</span>
                  <span className="text-ink-faint">{s.kind}{s.category ? ` · ${s.category}` : ''} · v{s.version ?? '?'}</span>
                  <span className="text-ink-faint ml-auto">{s.chunk_count ?? 0} passages · {s.record_count ?? 0} records</span>
                </div>
                <div className="text-[10px] text-ink-faint break-words">Licence: {s.license || 'not recorded'} · Origin: {s.origin || 'not recorded'}</div>
                {s.warnings?.length > 0 && <div className="text-[10px] text-amber">{s.warnings.length} ingestion warning(s): {s.warnings[0]}</div>}
              </li>
            ))}
          </ul>
        </section>

        <form onSubmit={submit} className="space-y-3 border-t border-void-600 pt-4" noValidate aria-label="Add a reference document">
          <h3 className="text-xs font-semibold text-ink">Add a reference document</h3>
          <p className="text-[10px] text-ink-faint">Only add material you are licensed to use. Accepted: {ACCEPTED_DOC_TYPES.join(', ')} (max 50 MB). CSV/JSON rows become structured records (name column required).</p>
          <div className="grid sm:grid-cols-2 gap-3">
            <label className="text-[10px] text-ink-muted space-y-1 block">File
              <input type="file" accept={ACCEPTED_DOC_TYPES.join(',')} disabled={busy} onChange={e => { setFile(e.target.files?.[0] ?? null); setProblem(null) }} className={field} />
            </label>
            <label className="text-[10px] text-ink-muted space-y-1 block">Category (use "Symptoms" for symptom records)
              <select value={category} disabled={busy} onChange={e => setCategory(e.target.value)} className={field}>
                {CATEGORIES.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
            <label className="text-[10px] text-ink-muted space-y-1 block">Licence <span className="text-rose">*</span>
              <input value={license} disabled={busy} onChange={e => { setLicense(e.target.value); setProblem(null) }} placeholder='e.g. "CC BY 4.0", "public domain", "own work"' className={field} aria-required="true" />
            </label>
            <label className="text-[10px] text-ink-muted space-y-1 block">Origin <span className="text-rose">*</span>
              <input value={origin} disabled={busy} onChange={e => { setOrigin(e.target.value); setProblem(null) }} placeholder="URL or where the document came from" className={field} aria-required="true" />
            </label>
          </div>
          {problem && <p className="text-xs text-rose" role="alert">{problem}</p>}
          {uploadStatus && (
            <p role="status" aria-live="polite" className={`text-xs rounded-xl border px-3 py-2 ${uploadStatus === 'error' ? 'border-rose/30 bg-rose/10 text-rose' : uploadStatus === 'success' ? 'border-emerald/30 bg-emerald/10 text-emerald' : 'border-violet/30 bg-violet/10 text-violet-light'}`}>
              {busy && '⏳ '}{uploadMessage}
            </p>
          )}
          <button type="submit" disabled={busy} className="btn-primary text-xs py-2 px-4">{busy ? 'Working…' : 'Add to knowledge base'}</button>
        </form>
      </div>
    </div>
  )
})

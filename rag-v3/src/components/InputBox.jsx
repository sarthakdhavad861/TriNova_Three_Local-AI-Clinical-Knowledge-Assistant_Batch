import React, { useState, useRef, useCallback, useEffect, memo } from 'react'
import { useSession } from '../context/SessionContext.jsx'
import { useUI } from '../context/UIContext.jsx'
import { useToast } from './Toast.jsx'
import { sanitizeInput, formatFileSize } from '../utils/formatters.js'
import { MAX_INPUT_CHARS, ACCEPTED_VIDEO_TYPES, ACCEPTED_PDF_TYPES } from '../utils/constants.js'

export default memo(function InputBox() {
  const { sendMessage, stopGeneration, uploadVideoFile, uploadPdfFile } = useSession()
  const { isLoading, isStreaming, uploadStatus, uploadProgress, uploadMessage, totalChunks } = useUI()
  const toast = useToast()

  const [value,     setValue]  = useState('')
  const [isDragOver, setDragOver] = useState(false)
  const textareaRef  = useRef(null)
  const fileInputRef = useRef(null)
  const composingRef = useRef(false)

  const isDisabled  = isLoading
  const isUploading = uploadStatus === 'uploading' || uploadStatus === 'processing'
  const charCount   = value.length
  const overLimit   = charCount > MAX_INPUT_CHARS
  const canSend     = value.trim().length > 0 && !isDisabled && !overLimit

  /* Auto-resize textarea */
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const next = Math.min(el.scrollHeight, 180) + 'px'
    el.style.height = next
    el.style.overflowY = el.scrollHeight > 180 ? 'auto' : 'hidden'
  }, [value])

  const handleSend = useCallback(() => {
    if (!canSend) return
    sendMessage(value.trim())
    setValue('')
    requestAnimationFrame(() => textareaRef.current?.focus())
  }, [canSend, value, sendMessage])

  const handleKeyDown = useCallback((e) => {
    if (e.isComposing || composingRef.current) return
    if (e.key === 'Enter' && !e.shiftKey)             { e.preventDefault(); handleSend() }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)){ e.preventDefault(); handleSend() }
    if (e.key === 'Escape' && isLoading)               { stopGeneration() }
  }, [handleSend, isLoading, stopGeneration])

  const handleCompositionStart = useCallback(() => { composingRef.current = true  }, [])
  const handleCompositionEnd   = useCallback(() => { composingRef.current = false }, [])

  const handleChange = useCallback((e) => {
    setValue(sanitizeInput(e.target.value).slice(0, MAX_INPUT_CHARS))
  }, [])

  const handlePaste = useCallback((e) => {
    e.preventDefault()
    const text = sanitizeInput(e.clipboardData.getData('text/plain'))
    const el   = e.target
    const start = el.selectionStart ?? value.length
    const end   = el.selectionEnd   ?? value.length
    setValue((value.slice(0, start) + text + value.slice(end)).slice(0, MAX_INPUT_CHARS))
  }, [value])

  /* ── Unified file handler — routes to video or PDF upload ── */
  const handleFile = useCallback(async (file) => {
    if (!file) return
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()

    if (ACCEPTED_PDF_TYPES.includes(ext) || file.type === 'application/pdf') {
      await uploadPdfFile(file)
      return
    }

    if (ACCEPTED_VIDEO_TYPES.includes(ext)) {
      await uploadVideoFile(file)
      return
    }

    toast(
      `Unsupported file type "${ext}". Accepted: ${[...ACCEPTED_VIDEO_TYPES, ...ACCEPTED_PDF_TYPES].join(', ')}`,
      'error',
    )
  }, [uploadVideoFile, uploadPdfFile, toast])

  const handleFileChange = useCallback((e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) handleFile(file)
  }, [handleFile])

  /* Drag and drop */
  const handleDragOver = useCallback((e) => {
    e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setDragOver(true)
  }, [])
  const handleDragLeave = useCallback((e) => {
    if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(false)
  }, [])
  const handleDrop = useCallback((e) => {
    e.preventDefault(); setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }, [handleFile])

  const uploadColor =
    uploadStatus === 'success' ? 'border-emerald/30 bg-emerald/10 text-emerald' :
    uploadStatus === 'error'   ? 'border-rose/30 bg-rose/10 text-rose' :
    'border-violet/30 bg-violet/10 text-violet-light'

  /* Accept both video + PDF in one input */
  const acceptAttr = [...ACCEPTED_VIDEO_TYPES, ...ACCEPTED_PDF_TYPES].join(',')

  return (
    <div
      className={`px-4 pb-4 pt-2 safe-bottom transition-all ${isDragOver ? 'bg-violet/5' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Upload status banner */}
      {uploadStatus && (
        <div className={`mb-2 flex items-center gap-2 px-3 py-2 rounded-xl text-xs border animate-fade-in ${uploadColor}`}>
          {(uploadStatus === 'uploading' || uploadStatus === 'processing') && (
            <SpinnerIcon size={12} className="animate-spin shrink-0" />
          )}
          {uploadStatus === 'success' && <CheckIcon  size={12} className="shrink-0" />}
          {uploadStatus === 'error'   && <AlertIcon  size={12} className="shrink-0" />}
          <span className="flex-1 truncate" aria-live="polite">{uploadMessage}</span>
          {uploadStatus === 'uploading' && (
            <>
              <div className="w-16 h-1 bg-void-600 rounded-full overflow-hidden shrink-0"
                   role="progressbar" aria-valuenow={uploadProgress} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full bg-violet rounded-full transition-all duration-300"
                     style={{ width: `${uploadProgress}%` }} />
              </div>
              <span className="font-mono text-[10px] shrink-0 tabular-nums w-8 text-right">{uploadProgress}%</span>
            </>
          )}
          {uploadStatus === 'processing' && (
            <div className="w-16 h-1 bg-void-600 rounded-full overflow-hidden shrink-0"
                 role="progressbar" aria-label="Processing">
              <div className="h-full bg-violet rounded-full animate-pulse-slow" style={{ width: '100%' }} />
            </div>
          )}
          {uploadStatus === 'success' && totalChunks > 0 && (
            <span className="text-[10px] shrink-0 tabular-nums">{totalChunks} chunks</span>
          )}
        </div>
      )}

      {/* Drag overlay hint */}
      {isDragOver && (
        <div className="mb-2 flex items-center justify-center gap-2 px-3 py-2 rounded-xl border border-violet/40 bg-violet/10 text-violet text-xs animate-fade-in">
          <UploadIcon size={13} /> Drop video or PDF to upload
        </div>
      )}

      {/* Main input */}
      <div className={`
        glass rounded-2xl transition-all duration-200
        ${canSend   ? 'border-violet/35 shadow-glow-sm' : ''}
        ${overLimit ? 'border-rose/40' : ''}
        ${isDisabled ? 'opacity-75' : ''}
      `}>
        <textarea
          ref={textareaRef}
          id="chat-input"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          disabled={isDisabled}
          rows={1}
          enterKeyHint="send"
          aria-label="Message input"
          aria-describedby={charCount > MAX_INPUT_CHARS * 0.7 ? 'char-counter' : undefined}
          placeholder={
            isUploading ? 'Processing file…' :
            isDisabled  ? 'AI is thinking…'  :
            'Ask about your videos or PDFs… (or ask about latest docs)'
          }
          className="
            w-full bg-transparent resize-none px-4 pt-3 pb-1
            text-sm text-ink placeholder-ink-faint focus:outline-none
            leading-relaxed min-h-[44px] max-h-[180px]
            scrollbar-none disabled:cursor-not-allowed
          "
        />

        <div className="flex items-center gap-2 px-3 pb-2.5 pt-1">
          {/* Hidden file input — accepts video + PDF */}
          <input
            ref={fileInputRef}
            type="file"
            accept={acceptAttr}
            className="hidden"
            onChange={handleFileChange}
            disabled={isDisabled || isUploading}
            aria-label="Upload video or PDF file"
          />

          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isDisabled || isUploading}
            title={`Upload video (${ACCEPTED_VIDEO_TYPES.join(', ')}) or PDF`}
            aria-label="Upload video or PDF file"
            className="btn-icon text-ink-faint hover:text-ink"
          >
            {isUploading
              ? <SpinnerIcon size={15} className="animate-spin text-violet" />
              : <PaperclipIcon size={15} />}
          </button>

          {/* Char counter */}
          {charCount > MAX_INPUT_CHARS * 0.7 && (
            <span
              id="char-counter"
              className={`text-[10px] font-mono tabular-nums ${overLimit ? 'text-rose' : 'text-ink-faint'}`}
              aria-label={`${charCount} of ${MAX_INPUT_CHARS} characters`}
              aria-live="polite"
            >
              {charCount}/{MAX_INPUT_CHARS}
            </span>
          )}

          <div className="flex-1" />

          {/* Stop / Send */}
          {isLoading ? (
            <button
              onClick={stopGeneration}
              aria-label="Stop generation"
              className="w-8 h-8 flex items-center justify-center rounded-xl bg-rose/20 border border-rose/30 text-rose hover:bg-rose/30 transition-all shrink-0 active:scale-90"
            >
              <StopIcon size={13} />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!canSend}
              aria-label="Send message"
              className={`
                w-8 h-8 flex items-center justify-center rounded-xl transition-all duration-150 shrink-0 active:scale-90
                ${canSend
                  ? 'bg-violet hover:bg-violet-light text-white shadow-glow-sm hover:shadow-glow-violet'
                  : 'bg-void-700 text-ink-faint cursor-not-allowed'}
              `}
            >
              <SendIcon size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Hints */}
      <p className="text-[10px] text-ink-faint text-center mt-1.5">
        <kbd className="bg-void-700 border border-void-500 rounded px-1 font-mono text-[9px]">Enter</kbd> send ·{' '}
        <kbd className="bg-void-700 border border-void-500 rounded px-1 font-mono text-[9px]">⇧ Enter</kbd> newline ·{' '}
        drag & drop video or PDF to upload
      </p>
    </div>
  )
})

/* ── Icons ── */
const SendIcon      = ({size=14}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
const StopIcon      = ({size=13}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="3"/></svg>
const PaperclipIcon = ({size=15}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
const SpinnerIcon   = ({size=14,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
const CheckIcon     = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><polyline points="20 6 9 17 4 12"/></svg>
const AlertIcon     = ({size=12,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
const UploadIcon    = ({size=13}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>

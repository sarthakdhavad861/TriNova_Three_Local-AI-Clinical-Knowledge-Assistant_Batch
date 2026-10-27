import React, { createContext, useContext, useCallback, useRef, useState, useEffect, memo } from 'react'
import { uid } from '../utils/formatters.js'

const ToastContext = createContext(null)

const ToastItem = memo(function ToastItem({ toast, onDismiss }) {
  const [visible, setVisible] = useState(false)
  useEffect(() => { const id = requestAnimationFrame(() => setVisible(true)); return () => cancelAnimationFrame(id) }, [])

  const colors = {
    success: 'border-emerald/30 bg-emerald/10 text-emerald',
    error:   'border-rose/30   bg-rose/10   text-rose',
    info:    'border-violet/30 bg-violet/10 text-violet-light',
    warning: 'border-amber/30  bg-amber/10  text-amber',
  }
  const icons = {
    success: <CheckCircleIcon size={14}/>,
    error:   <AlertIcon size={14}/>,
    info:    <InfoIcon size={14}/>,
    warning: <TriangleIcon size={14}/>,
  }
  return (
    <div
      className={`flex items-center gap-2.5 px-4 py-3 rounded-xl border text-xs font-medium shadow-glass max-w-xs w-full transition-all duration-300 ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'} ${colors[toast.type] ?? colors.info}`}
      role="alert"
      aria-live="polite"
    >
      <span className="shrink-0">{icons[toast.type] ?? icons.info}</span>
      <span className="flex-1 break-words">{toast.message}</span>
      <button onClick={() => onDismiss(toast.id)} className="shrink-0 opacity-60 hover:opacity-100 transition-opacity" aria-label="Dismiss">
        <XIcon size={12}/>
      </button>
    </div>
  )
})

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef({})

  const dismiss = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
    clearTimeout(timers.current[id])
    delete timers.current[id]
  }, [])

  const toast = useCallback((message, type = 'info', duration = 3500) => {
    const id = uid()
    setToasts(prev => [...prev.slice(-4), { id, message, type }])
    timers.current[id] = setTimeout(() => dismiss(id), duration)
    return id
  }, [dismiss])

  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-6 right-4 z-50 flex flex-col gap-2 items-end pointer-events-none" aria-label="Notifications">
        {toasts.map(t => (
          <div key={t.id} className="pointer-events-auto">
            <ToastItem toast={t} onDismiss={dismiss}/>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be inside ToastProvider')
  return ctx.toast
}

const CheckCircleIcon = ({size=14}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
const AlertIcon       = ({size=14}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
const InfoIcon        = ({size=14}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
const TriangleIcon    = ({size=14}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
const XIcon           = ({size=12}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>

import { useState, useEffect, useRef, useCallback } from 'react'
import { LS_SCHEMA_VERSION } from '../utils/constants.js'

const SCHEMA_KEY = '__rag_schema_v__'
let migrationDone = false

function ensureMigration() {
  if (migrationDone) return
  migrationDone = true
  try {
    const stored = localStorage.getItem(SCHEMA_KEY)
    const version = stored ? parseInt(stored, 10) : 0
    if (version < LS_SCHEMA_VERSION) {
      Object.keys(localStorage).filter(k => k.startsWith('rag_')).forEach(k => localStorage.removeItem(k))
      localStorage.setItem(SCHEMA_KEY, String(LS_SCHEMA_VERSION))
    }
  } catch {}
}

export function useLocalStorage(key, initialValue) {
  ensureMigration()
  const initialRef = useRef(initialValue)
  const isMounted  = useRef(true)

  const readValue = useCallback(() => {
    try {
      const item = localStorage.getItem(key)
      return item !== null ? JSON.parse(item) : initialRef.current
    } catch { return initialRef.current }
  }, [key])

  const [storedValue, setStoredValue] = useState(readValue)

  // Functional update — avoids stale closure
  const setValue = useCallback((valOrFn) => {
    setStoredValue(prev => {
      const next = typeof valOrFn === 'function' ? valOrFn(prev) : valOrFn
      try { localStorage.setItem(key, JSON.stringify(next)) }
      catch (e) { /* quota exceeded — fail silently in prod */ }
      return next
    })
  }, [key])

  const removeValue = useCallback(() => {
    try { localStorage.removeItem(key) } catch {}
    setStoredValue(initialRef.current)
  }, [key])

  // Cross-tab sync via storage event
  useEffect(() => {
    isMounted.current = true
    const handler = (e) => {
      if (e.key !== key || !isMounted.current) return
      try {
        const next = e.newValue !== null ? JSON.parse(e.newValue) : initialRef.current
        setStoredValue(next)
      } catch {}
    }
    window.addEventListener('storage', handler, { passive: true })
    return () => { isMounted.current = false; window.removeEventListener('storage', handler) }
  }, [key])

  return [storedValue, setValue, removeValue]
}

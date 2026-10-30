import React, { createContext, useContext, useReducer, useCallback, useMemo } from 'react'

const initialState = {
  isLoading: false, isStreaming: false, error: null,
  sidebarOpen: true, ragPanelOpen: true, theme: 'dark',
  uploadStatus: null, uploadProgress: 0, uploadMessage: null, totalChunks: 0,
  knowledgeOpen: false, sourcesMessageId: null, draft: '',
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_LOADING':      return { ...state, isLoading: action.v }
    case 'SET_STREAMING':    return { ...state, isStreaming: action.v }
    case 'SET_ERROR':        return { ...state, error: action.v }
    case 'CLEAR_ERROR':      return { ...state, error: null }
    case 'TOGGLE_SIDEBAR':   return { ...state, sidebarOpen: !state.sidebarOpen }
    case 'SET_SIDEBAR':      return { ...state, sidebarOpen: action.v }
    case 'TOGGLE_RAG_PANEL': return { ...state, ragPanelOpen: !state.ragPanelOpen }
    case 'TOGGLE_THEME': {
      const next = state.theme === 'dark' ? 'light' : 'dark'
      document.documentElement.classList.toggle('dark', next === 'dark')
      return { ...state, theme: next }
    }
    case 'SET_KNOWLEDGE':   return { ...state, knowledgeOpen: action.v }
    case 'SHOW_SOURCES':    return { ...state, sourcesMessageId: action.id, ragPanelOpen: true }
    case 'SET_DRAFT':       return { ...state, draft: action.v }
    case 'SET_UPLOAD':   return { ...state, ...action.patch }
    case 'RESET_UPLOAD': return { ...state, uploadStatus: null, uploadProgress: 0, uploadMessage: null }
    default: return state
  }
}

const UIContext = createContext(null)

export function UIProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  const setLoading    = useCallback((v)     => dispatch({ type: 'SET_LOADING',      v }), [])
  const setStreaming   = useCallback((v)     => dispatch({ type: 'SET_STREAMING',    v }), [])
  const setError      = useCallback((v)     => dispatch({ type: 'SET_ERROR',        v }), [])
  const clearError    = useCallback(()      => dispatch({ type: 'CLEAR_ERROR' }), [])
  const toggleSidebar   = useCallback(()    => dispatch({ type: 'TOGGLE_SIDEBAR' }), [])
  const setSidebar      = useCallback((v)   => dispatch({ type: 'SET_SIDEBAR',     v }), [])
  const toggleRagPanel  = useCallback(()    => dispatch({ type: 'TOGGLE_RAG_PANEL' }), [])
  const toggleTheme     = useCallback(()    => dispatch({ type: 'TOGGLE_THEME' }), [])
  const setUpload       = useCallback((patch)=> dispatch({ type: 'SET_UPLOAD',     patch }), [])
  const resetUpload     = useCallback(()    => dispatch({ type: 'RESET_UPLOAD' }), [])
  const setKnowledgeOpen = useCallback((v)  => dispatch({ type: 'SET_KNOWLEDGE', v }), [])
  const showSources      = useCallback((id)  => dispatch({ type: 'SHOW_SOURCES', id }), [])
  const setDraft          = useCallback((v)   => dispatch({ type: 'SET_DRAFT', v }), [])

  const value = useMemo(() => ({
    ...state,
    setLoading, setStreaming, setError, clearError,
    toggleSidebar, setSidebar, toggleRagPanel, toggleTheme,
    setUpload, resetUpload, setKnowledgeOpen, showSources, setDraft,
  }), [state, setLoading, setStreaming, setError, clearError,
    toggleSidebar, setSidebar, toggleRagPanel, toggleTheme, setUpload, resetUpload, setKnowledgeOpen, showSources, setDraft])

  return <UIContext.Provider value={value}>{children}</UIContext.Provider>
}

export function useUI() {
  const ctx = useContext(UIContext)
  if (!ctx) throw new Error('useUI must be inside UIProvider')
  return ctx
}

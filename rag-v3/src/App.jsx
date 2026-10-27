import React, { useEffect } from 'react'
import { UIProvider } from './context/UIContext.jsx'
import { SessionProvider } from './context/SessionContext.jsx'
import { ToastProvider } from './components/Toast.jsx'
import { ErrorBoundary } from './components/ErrorBoundary.jsx'
import ChatPage from './pages/ChatPage.jsx'

/* Remove the app loader once React has hydrated */
function AppLoader() {
  useEffect(() => {
    const loader = document.getElementById('app-loader')
    if (loader) {
      loader.style.opacity = '0'
      setTimeout(() => loader.remove(), 300)
    }
  }, [])
  return null
}

export default function App() {
  return (
    <ErrorBoundary>
      <UIProvider>
        <SessionProvider>
          <ToastProvider>
            <AppLoader />
            <ChatPage />
          </ToastProvider>
        </SessionProvider>
      </UIProvider>
    </ErrorBoundary>
  )
}

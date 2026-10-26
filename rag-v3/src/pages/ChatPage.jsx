import React, { lazy, Suspense } from 'react'
import { useUI } from '../context/UIContext.jsx'
import Sidebar from '../components/Sidebar.jsx'
import ChatWindow from '../components/ChatWindow.jsx'
import { ErrorBoundary } from '../components/ErrorBoundary.jsx'

const RagPanel = lazy(() => import('../components/RagPanel.jsx'))

function RagPanelSkeleton() {
  return (
    <aside
      className="w-72 shrink-0 hidden xl:flex flex-col bg-void-900 border-l border-void-600 p-4 gap-3"
      aria-label="Loading sources panel"
    >
      {[0, 1, 2].map(i => (
        <div key={i} className="skeleton h-20 rounded-xl" />
      ))}
    </aside>
  )
}

export default function ChatPage() {
  const { ragPanelOpen } = useUI()

  return (
    <div className="flex h-full w-full overflow-hidden bg-mesh">
      {/* Skip to main content — accessibility */}
      <a href="#main-content" className="skip-to-main">
        Skip to main content
      </a>

      <ErrorBoundary>
        <Sidebar />
      </ErrorBoundary>

      <main
        id="main-content"
        className="flex-1 flex flex-col overflow-hidden min-w-0"
        aria-label="Chat interface"
      >
        <ErrorBoundary>
          <ChatWindow />
        </ErrorBoundary>
      </main>

      {ragPanelOpen && (
        <ErrorBoundary fallback={() => null}>
          <Suspense fallback={<RagPanelSkeleton />}>
            <RagPanel />
          </Suspense>
        </ErrorBoundary>
      )}
    </div>
  )
}

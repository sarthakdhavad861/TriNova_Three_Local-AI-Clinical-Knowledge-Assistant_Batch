import React from 'react'

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info)
  }
  handleReset = () => this.setState({ hasError: false, error: null })

  render() {
    if (!this.state.hasError) return this.props.children
    const { fallback: Fallback } = this.props
    if (Fallback) return <Fallback error={this.state.error} onReset={this.handleReset} />
    return (
      <div className="flex flex-col items-center justify-center h-full px-6 text-center">
        <div className="w-14 h-14 rounded-2xl bg-rose/10 border border-rose/20 flex items-center justify-center mb-4">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fb7185" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-ink mb-1">Something went wrong</h2>
        <p className="text-sm text-ink-muted mb-4 max-w-xs">{this.state.error?.message ?? 'An unexpected error occurred.'}</p>
        <button onClick={this.handleReset} className="btn-primary">Try again</button>
      </div>
    )
  }
}

export function withErrorBoundary(Component, fallback) {
  return function WrappedWithBoundary(props) {
    return <ErrorBoundary fallback={fallback}><Component {...props} /></ErrorBoundary>
  }
}

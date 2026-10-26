export function formatTimestamp(ts) {
  if (!ts) return ''
  const d = new Date(ts), now = new Date()
  if (d.toDateString() === now.toDateString())
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString())
    return 'Yesterday ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
export function formatRelativeDate(ts) {
  if (!ts) return ''
  const d = new Date(ts), now = new Date()
  if (d.toDateString() === now.toDateString()) return 'Today'
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  const weekAgo = new Date(now); weekAgo.setDate(now.getDate() - 7)
  if (d > weekAgo) return d.toLocaleDateString('en-US', { weekday: 'long' })
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
export function formatVideoTime(secs) {
  if (typeof secs !== 'number' || isNaN(secs) || secs < 0) return '0:00'
  const m = Math.floor(secs / 60), s = Math.floor(secs % 60)
  return m + ':' + s.toString().padStart(2, '0')
}
export function formatScore(score)   { return Math.round((score ?? 0) * 100) + '%' }
export function scorePercent(score)  { return Math.round((score ?? 0) * 100) + '%' }
export function scoreColor(score) {
  const p = (score ?? 0) * 100
  if (p >= 90) return '#34d399'
  if (p >= 75) return '#22d3ee'
  if (p >= 55) return '#7c5cfc'
  return '#fbbf24'
}
export function truncate(str = '', max = 60) {
  if (str.length <= max) return str
  return str.slice(0, max).trimEnd() + '\u2026'
}
export function titleFromMessage(content = '') {
  return truncate(content.replace(/\s+/g, ' ').trim(), 44) || 'New Chat'
}
export function sanitizeInput(str = '') {
  return str.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
}
export function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 ** 3) return (bytes / 1024 ** 2).toFixed(1) + ' MB'
  return (bytes / 1024 ** 3).toFixed(2) + ' GB'
}
export function uid() {
  return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8)
}

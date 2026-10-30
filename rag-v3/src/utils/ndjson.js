// Incremental NDJSON parser: feed it arbitrary string chunks (lines may be split anywhere); it emits one object per line.
export function createNdjsonParser(onEvent) {
  let buf = ''
  const emit = (line) => {
    const s = line.trim()
    if (!s) return
    let ev
    try { ev = JSON.parse(s) } catch { ev = { type: 'error', message: 'Malformed server event', malformed: true } }
    onEvent(ev)
  }
  return {
    push(text) {
      buf += text
      let i
      while ((i = buf.indexOf('\n')) >= 0) {
        emit(buf.slice(0, i))
        buf = buf.slice(i + 1)
      }
    },
    end() { if (buf.trim()) emit(buf); buf = '' },
  }
}

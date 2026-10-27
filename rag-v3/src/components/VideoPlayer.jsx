import React, { useState, useRef, useCallback, useEffect, memo } from 'react'
import { formatVideoTime } from '../utils/formatters.js'

export default memo(function VideoPlayer({ video }) {
  const [loaded,     setLoaded]     = useState(false)
  const [activeTime, setActiveTime] = useState(null)
  const [videoError, setVideoError] = useState(false)
  const [videoLoading, setVideoLoading] = useState(false)
  const iframeRef = useRef(null)
  const videoRef  = useRef(null)
  const playerReadyRef = useRef(false)

  if (!video) return null

  const hasUrl    = Boolean(video.url)
  const isYouTube = hasUrl && (video.url.includes('youtube') || video.url.includes('youtu.be'))
  const isLocal   = hasUrl && !isYouTube
  const hasTimestamps = (video.timestamps?.length ?? 0) > 0

  /* YouTube Player API via postMessage */
  useEffect(() => {
    if (!isYouTube || !loaded) return
    const iframe = iframeRef.current
    if (!iframe) return

    const onMessage = (e) => {
      try {
        const data = typeof e.data === 'string' ? JSON.parse(e.data) : e.data
        if (data?.event === 'onReady') playerReadyRef.current = true
      } catch {}
    }

    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [isYouTube, loaded])

  const seekYouTube = useCallback((time) => {
    const iframe = iframeRef.current
    if (!iframe) return
    // YouTube iframe API postMessage seek
    iframe.contentWindow?.postMessage(
      JSON.stringify({ event: 'command', func: 'seekTo', args: [time, true] }),
      '*'
    )
    iframe.contentWindow?.postMessage(
      JSON.stringify({ event: 'command', func: 'playVideo', args: [] }),
      '*'
    )
  }, [])

  const seekToTime = useCallback((time) => {
    setActiveTime(time)
    if (!loaded) {
      setLoaded(true)
      // After iframe loads, seek via postMessage with delay for init
      if (isYouTube) {
        setTimeout(() => seekYouTube(time), 1200)
      }
      return
    }
    if (isYouTube) seekYouTube(time)
    if (isLocal && videoRef.current) {
      videoRef.current.currentTime = time
      videoRef.current.play().catch(() => {})
    }
  }, [loaded, isYouTube, isLocal, seekYouTube])

  /* Build YouTube embed URL with enablejsapi=1 */
  const youtubeEmbedUrl = useCallback(() => {
    if (!video.url) return ''
    const base = video.url.split('?')[0]
    const params = new URLSearchParams({ enablejsapi: '1', origin: window.location.origin })
    if (activeTime != null) params.set('start', String(Math.floor(activeTime)))
    return `${base}?${params}`
  }, [video.url, activeTime])

  return (
    <div className="rounded-2xl overflow-hidden border border-void-500 bg-void-900 mt-2">
      {/* Chrome bar */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-void-800 border-b border-void-600">
        <div className="flex gap-1.5" aria-hidden="true">
          <div className="w-2.5 h-2.5 rounded-full bg-rose/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-amber/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-emerald/70" />
        </div>
        <VideoIcon size={11} className="text-ink-faint ml-2 shrink-0" />
        <span className="text-[10px] text-ink-faint flex-1 truncate ml-1" title={video.title}>
          {video.title}
        </span>
      </div>

      {/* Video area */}
      {hasUrl ? (
        <div className="relative aspect-video bg-void-950">
          {/* Error state */}
          {videoError && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-void-900">
              <AlertIcon size={24} className="text-rose" />
              <p className="text-xs text-ink-muted">Failed to load video</p>
            </div>
          )}

          {/* Click-to-load poster */}
          {!loaded && !videoError && (
            <button
              onClick={() => setLoaded(true)}
              className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-void-900 hover:bg-void-800 transition-colors group"
              aria-label={`Load video: ${video.title}`}
            >
              <div className="w-14 h-14 rounded-full bg-violet/20 border border-violet/30 flex items-center justify-center group-hover:scale-110 transition-transform shadow-glow-sm">
                <PlayIcon size={22} className="text-violet ml-1" />
              </div>
              <p className="text-[10px] text-ink-faint">Click to load video</p>
            </button>
          )}

          {/* Loading overlay for local video */}
          {loaded && isLocal && videoLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-void-950/80 z-10">
              <SpinnerIcon size={28} className="text-violet animate-spin" />
            </div>
          )}

          {/* YouTube embed */}
          {loaded && isYouTube && (
            <iframe
              ref={iframeRef}
              src={youtubeEmbedUrl()}
              title={video.title}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
              className="absolute inset-0 w-full h-full"
              onError={() => setVideoError(true)}
            />
          )}

          {/* Local video */}
          {loaded && isLocal && (
            <video
              ref={videoRef}
              src={video.url}
              controls
              autoPlay
              className="absolute inset-0 w-full h-full bg-black object-contain"
              onLoadStart={() => setVideoLoading(true)}
              onCanPlay={() => setVideoLoading(false)}
              onError={() => { setVideoError(true); setVideoLoading(false) }}
            />
          )}
        </div>
      ) : (
        /* No URL — reference card */
        <div className="flex items-start gap-3 px-4 py-4 bg-void-900">
          <div className="w-9 h-9 rounded-xl bg-violet/15 border border-violet/25 flex items-center justify-center shrink-0">
            <BookOpenIcon size={15} className="text-violet" />
          </div>
          <div>
            <p className="text-xs font-semibold text-ink mb-1">Video reference</p>
            <p className="text-[11px] text-ink-muted leading-relaxed">
              This answer references{' '}
              <span className="text-violet-light font-medium">{video.title}</span>.
              Open it in your local player and seek to the timestamps below.
            </p>
          </div>
        </div>
      )}

      {/* Timestamps */}
      {hasTimestamps && (
        <div className="px-3 py-2.5">
          <p className="text-[9px] uppercase tracking-widest text-ink-faint font-semibold mb-2 flex items-center gap-1">
            <ClockIcon size={9} />
            {hasUrl ? 'Click to seek' : 'Watch at'}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {video.timestamps.map((ts, i) => (
              <button
                key={i}
                onClick={() => seekToTime(ts.time)}
                aria-label={`Seek to ${formatVideoTime(ts.time)}: ${ts.label}`}
                className={`
                  flex items-center gap-1.5 text-[10px] px-2.5 py-1.5 rounded-lg border transition-all duration-150
                  ${activeTime === ts.time
                    ? 'border-violet/50 bg-violet/15 text-violet-light'
                    : 'border-void-500 text-ink-muted hover:border-violet/30 hover:bg-void-700 hover:text-ink'}
                `}
              >
                <span className="font-mono font-semibold text-violet">{formatVideoTime(ts.time)}</span>
                <span className="max-w-[140px] truncate text-ink-faint">{ts.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
})

const PlayIcon     = ({size=16,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}><polygon points="5 3 19 12 5 21 5 3"/></svg>
const VideoIcon    = ({size=13,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
const ClockIcon    = ({size=11,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className={className}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
const BookOpenIcon = ({size=15,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
const AlertIcon    = ({size=14,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
const SpinnerIcon  = ({size=20,className=''}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className={className}><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>

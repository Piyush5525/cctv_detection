import { useState, useRef, useEffect, useCallback } from 'react'
import { Radio, Camera, RefreshCw } from 'lucide-react'
import { TYPE_SHORT } from '../utils/incidentMeta'
import { SEVERITY_HEX } from '../utils/types'
import { formatConfidence } from '../utils/format'

const FRAME_URL = '/api/v1/system/frame'
const POLL_MS = 150       // ~6-7 fps while a live pipeline is actually producing frames
const OFFLINE_POLL_MS = 5000  // no live pipeline is running in this deployment most of the
                               // time -- polling every 150ms against a 404 forever was
                               // flooding the backend (thousands of requests/min) and
                               // starving other real requests (incident thumbnails etc.)
                               // of response time. Back off hard once we know it's offline.

export function LiveVideo({ featureIncident }) {
  const [status, setStatus] = useState('connecting')
  const [frameUrl, setFrameUrl] = useState(null)
  const timerRef = useRef(null)
  const mountedRef = useRef(true)
  const failCountRef = useRef(0)

  const fetchFrame = useCallback(() => {
    // Don't even issue the request while the tab is hidden -- no one is
    // watching the feed, so there's no reason to keep polling it.
    if (document.hidden) {
      timerRef.current = setTimeout(fetchFrame, OFFLINE_POLL_MS)
      return
    }
    const img = new Image()
    const url = `${FRAME_URL}?t=${Date.now()}`
    img.onload = () => {
      if (!mountedRef.current) return
      failCountRef.current = 0
      setFrameUrl(url)
      setStatus('live')
      timerRef.current = setTimeout(fetchFrame, POLL_MS)
    }
    img.onerror = () => {
      if (!mountedRef.current) return
      failCountRef.current += 1
      // After 3 consecutive failures show offline and back off hard --
      // there's no live pipeline, so keep checking occasionally rather
      // than hammering the backend at video-framerate forever.
      if (failCountRef.current >= 3) setStatus('offline')
      const delay = failCountRef.current >= 3 ? OFFLINE_POLL_MS : 1000
      timerRef.current = setTimeout(fetchFrame, delay)
    }
    img.src = url
  }, [])

  useEffect(() => {
    mountedRef.current = true
    fetchFrame()
    const onVisibilityChange = () => {
      if (!document.hidden && mountedRef.current) {
        clearTimeout(timerRef.current)
        fetchFrame()
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      mountedRef.current = false
      clearTimeout(timerRef.current)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [fetchFrame])

  const retry = () => {
    failCountRef.current = 0
    setStatus('connecting')
    clearTimeout(timerRef.current)
    fetchFrame()
  }

  const sevColor = featureIncident ? SEVERITY_HEX[featureIncident.severity] : null
  const label = featureIncident
    ? `${TYPE_SHORT[featureIncident.incident_type] || featureIncident.incident_type?.toUpperCase()} ${formatConfidence(featureIncident.confidence)}`
    : null

  return (
    <div className="card overflow-hidden p-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-ground-line">
        <div className="flex items-center gap-2">
          <Camera className="w-4 h-4 text-ink-faint" />
          <span className="text-sm font-display font-semibold text-ink">
            {featureIncident ? `${featureIncident.location?.camera_id} · ${featureIncident.location?.address}` : 'Feature feed'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`live-indicator ${status !== 'live' ? 'opacity-60 border-ink-faint/30 bg-white/5 text-ink-faint' : ''}`}>
            <span className={status === 'live' ? 'live-dot' : 'w-1.5 h-1.5 rounded-full bg-ink-faint'} />
            {status === 'live' ? 'LIVE' : status === 'connecting' ? 'Connecting…' : 'Offline'}
          </div>
          {status === 'offline' && (
            <button onClick={retry} className="p-1 rounded text-ink-faint hover:text-ink">
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Frame */}
      <div className="relative bg-ground" style={{ aspectRatio: '16/9' }}>
        {frameUrl ? (
          <>
            <img
              src={frameUrl}
              alt="Live detection feed"
              className="w-full h-full object-contain"
            />
            {status === 'live' && (
              <div className="absolute top-2 left-2 flex items-center gap-1 text-[10px] font-mono font-semibold text-sev-critical bg-black/50 px-1.5 py-0.5 rounded">
                <span className="w-1.5 h-1.5 rounded-full bg-sev-critical animate-pulse-dot" /> REC
              </div>
            )}
            <div className="absolute top-2 right-2 text-[10px] font-mono text-ink-faint bg-black/50 px-1.5 py-0.5 rounded">
              1280x720 · 7 fps
            </div>
            {featureIncident && (
              <div
                className="detection-box"
                style={{
                  left: '28%', top: '20%', width: '38%', height: '55%',
                  borderColor: sevColor,
                }}
              >
                <span className="detection-label" style={{ left: 0, top: 0, background: sevColor }}>
                  {label}
                </span>
              </div>
            )}
          </>
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className="w-12 h-12 rounded-full bg-ground-panel border border-ground-line flex items-center justify-center mb-3">
              <Radio className={`w-5 h-5 ${status === 'connecting' ? 'text-signal animate-pulse' : 'text-ink-faint'}`} />
            </div>
            <p className="text-sm font-medium text-ink-muted">
              {status === 'connecting' ? 'Waiting for detection pipeline...' : 'Detection pipeline not running'}
            </p>
            <p className="text-xs text-ink-faint mt-1">
              Run: <span className="font-mono text-ink-muted">python run_dashboard.py --mode detection</span>
            </p>
            {status === 'offline' && (
              <button onClick={retry} className="mt-4 btn-ghost text-xs border border-ground-line">
                <RefreshCw className="w-3 h-3" /> Retry
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default LiveVideo

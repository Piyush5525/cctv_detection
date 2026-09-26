import { useState, useRef, useEffect, useCallback } from 'react'
import { Radio, Camera, RefreshCw } from 'lucide-react'

const FRAME_URL = '/api/v1/system/frame'
const POLL_MS = 150  // ~6-7 fps, light on the server

export function LiveVideo() {
  const [status, setStatus] = useState('connecting')
  const [frameUrl, setFrameUrl] = useState(null)
  const timerRef = useRef(null)
  const mountedRef = useRef(true)
  const failCountRef = useRef(0)

  const fetchFrame = useCallback(() => {
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
      // After 3 consecutive failures show offline, keep retrying slower
      if (failCountRef.current >= 3) setStatus('offline')
      timerRef.current = setTimeout(fetchFrame, 1000)
    }
    img.src = url
  }, [])

  useEffect(() => {
    mountedRef.current = true
    fetchFrame()
    return () => {
      mountedRef.current = false
      clearTimeout(timerRef.current)
    }
  }, [fetchFrame])

  const retry = () => {
    failCountRef.current = 0
    setStatus('connecting')
    clearTimeout(timerRef.current)
    fetchFrame()
  }

  return (
    <div className="card overflow-hidden p-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1a2540]">
        <div className="flex items-center gap-2">
          <Camera className="w-4 h-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-200">Live Detection Feed</span>
        </div>
        <div className="flex items-center gap-2">
          <div className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${
            status === 'live'
              ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
              : status === 'connecting'
              ? 'text-blue-400 bg-blue-500/10 border-blue-500/20'
              : 'text-red-400 bg-red-500/10 border-red-500/20'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${
              status === 'live' ? 'bg-emerald-400 animate-pulse'
              : status === 'connecting' ? 'bg-blue-400 animate-pulse'
              : 'bg-red-400'
            }`} />
            {status === 'live' ? 'Live' : status === 'connecting' ? 'Connecting...' : 'Offline'}
          </div>
          {status === 'offline' && (
            <button onClick={retry} className="p-1 rounded text-slate-600 hover:text-slate-400">
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Frame */}
      <div className="relative bg-[#080d18]" style={{ aspectRatio: '16/9' }}>
        {frameUrl ? (
          <img
            src={frameUrl}
            alt="Live detection feed"
            className="w-full h-full object-contain"
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className="w-12 h-12 rounded-full bg-[#0d1526] border border-[#1a2540] flex items-center justify-center mb-3">
              <Radio className={`w-5 h-5 ${status === 'connecting' ? 'text-blue-400 animate-pulse' : 'text-slate-700'}`} />
            </div>
            <p className="text-sm font-medium text-slate-500">
              {status === 'connecting' ? 'Waiting for detection pipeline...' : 'Detection pipeline not running'}
            </p>
            <p className="text-xs text-slate-700 mt-1">
              Run: <span className="font-mono text-slate-500">python run_dashboard.py --mode detection</span>
            </p>
            {status === 'offline' && (
              <button onClick={retry} className="mt-4 btn-ghost text-xs border border-[#1a2540]">
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

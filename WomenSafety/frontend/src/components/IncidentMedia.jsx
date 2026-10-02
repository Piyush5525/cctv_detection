// Evidence media for the detail panel: 16:9 containers (object-fit: contain), a loading skeleton, a clear error state with the
// failing reason and a Retry button, and an Original / Annotated toggle for the photo. The <img> and <video> elements keep
// their identity while the selected incident is unchanged (polling / WebSocket updates never reload them); the parent keys
// this component by incident_id.
import { useCallback, useEffect, useRef, useState } from 'react'
import { describeFailure, evidenceUrl, hasAnnotated, setVideoPlaying } from '../utils/media.mjs'

async function diagnose(url) {
  try {
    const r = await fetch(url, { headers: { Range: 'bytes=0-0' } })
    if (r.ok) return describeFailure(200)
    let detail
    try { detail = (await r.json())?.detail } catch { /* not JSON */ }
    return `${describeFailure(r.status)}${detail && r.status !== 404 ? `: ${detail}` : ''}`
  } catch {
    return describeFailure(null)
  }
}

function useMediaState() {
  const [state, setState] = useState('loading')   // loading | ok | error
  const [reason, setReason] = useState('')
  const [nonce, setNonce] = useState(0)
  const fail = useCallback(async (url) => { setState('error'); setReason(await diagnose(url)) }, [])
  const retry = useCallback(() => { setState('loading'); setReason(''); setNonce((n) => n + 1) }, [])
  const reset = useCallback(() => { setState('loading'); setReason('') }, [])
  return { state, reason, nonce, ok: () => setState('ok'), fail, retry, reset }
}

function Frame({ label, st, children, onRetry }) {
  return (
    <div className="media-frame" role="group" aria-label={label}>
      {children}
      {st.state === 'loading' && <div className="media-skeleton" aria-hidden="true" />}
      {st.state === 'error' && (
        <div className="media-error" role="alert">
          <strong>{label} unavailable</strong>
          <span>{st.reason || 'Loading failed'}</span>
          <button type="button" className="media-retry" onClick={onRetry}>Retry</button>
        </div>
      )}
    </div>
  )
}

export default function IncidentMedia({ incident }) {
  const [view, setView] = useState('best')            // 'best' (original frame) | 'annotated'
  const photo = useMediaState()
  const video = useMediaState()
  const videoRef = useRef(null)
  const photoUrl = evidenceUrl(incident, view, photo.nonce)
  const clipUrl = evidenceUrl(incident, 'clip', video.nonce)
  const poster = evidenceUrl(incident, 'thumbnail')
  const annotatedOk = hasAnnotated(incident)
  useEffect(() => () => setVideoPlaying(false), [])

  const switchView = (next) => { if (next !== view) { setView(next); photo.reset() } }

  return (
    <div className="detail-media">
      <div className="media-toggle" role="group" aria-label="Photo version">
        <button type="button" className={view === 'best' ? 'on' : ''} aria-pressed={view === 'best'} onClick={() => switchView('best')}>Original frame</button>
        <button type="button" className={view === 'annotated' ? 'on' : ''} aria-pressed={view === 'annotated'} disabled={!annotatedOk}
                title={annotatedOk ? 'Frame with the detector overlay' : 'No annotated frame for this incident'} onClick={() => switchView('annotated')}>Annotated frame</button>
      </div>
      <Frame label="Photo" st={photo} onRetry={photo.retry}>
        <img key={photoUrl} className="media-el" src={photoUrl} alt={view === 'annotated' ? 'Annotated evidence frame' : 'Best evidence frame'}
             onLoad={photo.ok} onError={() => photo.fail(photoUrl)} />
      </Frame>
      <Frame label="Clip" st={video} onRetry={video.retry}>
        <video key={clipUrl} ref={videoRef} className="media-el" controls preload="metadata" playsInline poster={poster} src={clipUrl}
               onLoadedMetadata={video.ok} onError={() => video.fail(clipUrl)}
               onPlay={() => setVideoPlaying(true)} onPause={() => setVideoPlaying(false)} onEnded={() => setVideoPlaying(false)} />
      </Frame>
    </div>
  )
}

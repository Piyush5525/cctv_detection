import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Map, { Layer, Marker, Source } from 'react-map-gl/mapbox'
import 'mapbox-gl/dist/mapbox-gl.css'
import toast from 'react-hot-toast'
import api from '../utils/api'
import { useWebSocket } from '../context/WebSocketContext'
import { DispatchCard, DispatchLayer, DispatchLegend, dispatchModel, fitToDispatch } from '../components/dispatch'
import IncidentMedia from '../components/IncidentMedia'
import { isVideoPlaying } from '../utils/media.mjs'

// Local style used when Mapbox's style/tiles cannot be loaded (offline): plain dark background,
// dispatch icons / lines / card keep working because they are drawn by our own layers.
const BLANK_STYLE = { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#0B1119' } }] }

// ─── Constants ───────────────────────────────────────────────────────
const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN
const POLL_MS = 2000
// "confirmed" only ever comes from the Acknowledge button (dashboard or Telegram).
const STATUS_LABELS = { confirmed: 'Acknowledged', acknowledged: 'Acknowledged', false_positive: 'False positive', false_alarm: 'False alarm' }
const statusLabel = (status) => STATUS_LABELS[status] || status

// Location source badge. The backend only sends location_source for phone cameras and only when
// LOCATION_MODE != fixed, so nothing is shown (and nothing changes) in the default mode.
function locationBadge(source, accuracy, fixAge) {
  if (source === 'device_gps') return `Device GPS ± ${Math.round(accuracy ?? 0)} m${fixAge != null ? ` · fix ${Math.round(fixAge)} s old` : ''}`
  if (source === 'camera_registry') return 'Fixed placement'
  return null
}

// Great-circle metres, and a polygon approximating an accuracy circle (display only).
function metres(a, b) {
  const R = 6371000, rad = (x) => (x * Math.PI) / 180
  const dLat = rad(b.latitude - a.latitude), dLng = rad(b.longitude - a.longitude)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.latitude)) * Math.cos(rad(b.latitude)) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}
function circlePolygon(lng, lat, radiusM) {
  const pts = []
  for (let i = 0; i <= 64; i++) {
    const t = (i / 64) * 2 * Math.PI
    pts.push([lng + (radiusM * Math.cos(t)) / (111320 * Math.cos((lat * Math.PI) / 180)), lat + (radiusM * Math.sin(t)) / 110540])
  }
  return { type: 'Feature', geometry: { type: 'Polygon', coordinates: [pts] }, properties: {} }
}
const CLOSE_CAMERA_M = 15
const SLIDE_MS = 3000
const PREFERSREDUCEDMOTION =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches

// Category → color, keeping the palette tight for projector contrast
const CATEGORY_COLORS = {
  fire: '#FF951F',
  road_accident: '#FF4B3E',
  assault: '#E74C6F',
  snatching: '#A97BFF',
  fall: '#FFB829',
  women_safety: '#5B9BFF',
  other: '#7FE3D0',
}

const categoryColor = (cat) => CATEGORY_COLORS[cat] || CATEGORY_COLORS.other

// Severity rank for sorting (higher = more severe)
const SEVERITY_RANK = {
  road_accident: 5,
  fire: 4,
  assault: 3,
  snatching: 2,
  women_safety: 2,
  fall: 1,
  other: 0,
}

// Experimental action detectors (fall / violence / snatch): shown with an "Experimental" badge everywhere.
const EXPERIMENTAL_CATEGORIES = new Set(['fall', 'assault', 'snatching'])
const isExperimental = (inc) => !!(inc?.experimental || inc?.detection?.experimental || EXPERIMENTAL_CATEGORIES.has(inc?.category))
const CATEGORY_NAMES = { assault: 'Violence', snatching: 'Snatch', fall: 'Fall' }
const CATEGORY_ICONS = { fire: '🔥', road_accident: '🚗', assault: '👊', snatching: '👜', fall: '🧍' }
const categoryIcon = (cat) => CATEGORY_ICONS[cat] || ''

const categoryLabel = (cat) =>
  CATEGORY_NAMES[cat] || (cat || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

// SCRIPTED demo incident: category set by the demo script, not a detector result (nothing scored)
const isScripted = (inc) => !!(inc?.scripted || inc?.detection?.scripted || inc?.detection?.detector_source === 'scripted_demo')

function ScriptedBadge() {
  return <span className="honesty-badge scripted-badge" title="Scripted demo incident: the category was set by the demo script, not by a detector. Nothing was scored.">SCRIPTED DEMO</span>
}

function ExperimentalBadge() {
  return <span className="honesty-badge exp-badge" title="Experimental detector: verify before acting. It never calls automatically.">EXPERIMENTAL</span>
}

// Filter chips (category -> incident categories it matches)
const FILTERS = [
  { key: 'all', label: 'All', cats: null },
  { key: 'fire', label: '🔥 Fire', cats: ['fire'] },
  { key: 'crash', label: '🚗 Crash', cats: ['road_accident'] },
  { key: 'violence', label: '👊 Violence', cats: ['assault'], exp: true },
  { key: 'fall', label: '🧍 Fall', cats: ['fall'], exp: true },
  { key: 'snatch', label: '👜 Snatch', cats: ['snatching'], exp: true },
]


const fmtTime = (iso) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

const fmtDateTime = (iso) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString([], {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return iso
  }
}

// Determine the "worst" category in a group's incidents
function mostSevereCategory(incidents) {
  if (!incidents?.length) return 'other'
  return incidents.reduce((worst, inc) => {
    const rank = SEVERITY_RANK[inc.category] ?? 0
    const worstRank = SEVERITY_RANK[worst] ?? 0
    return rank > worstRank ? inc.category : worst
  }, incidents[0].category)
}

// ─── Hover Popup ─────────────────────────────────────────────────────
function HoverPopup({ group, onPin }) {
  const [idx, setIdx] = useState(0)
  const rows = group.incidents || []

  useEffect(() => {
    if (rows.length <= 1 || PREFERSREDUCEDMOTION) return
    const id = setInterval(() => { if (!isVideoPlaying()) setIdx((x) => (x + 1) % rows.length) }, SLIDE_MS)
    return () => clearInterval(id)
  }, [rows.length])

  const item = rows[idx]

  return (
    <div className="hover-popup" onClick={(e) => { e.stopPropagation(); onPin() }}
         role="tooltip" aria-label={`${group.camera_name} preview`}>
      <div className="hover-head">
        <strong className="hover-name">{group.camera_name}</strong>
        {group.camera_type === 'phone' && (
          <span className="honesty-badge phone-badge">Demo phone camera</span>
        )}
        {group.location_basis === 'simulated_placement' && (
          <span className="honesty-badge sim-badge">Simulated placement</span>
        )}
      </div>
      <span className="hover-place">{group.place_text}</span>
      <span className="hover-count">
        {group.count} incident{group.count !== 1 ? 's' : ''}
      </span>
      {item && (
        <div className="hover-slide">
          <img
            key={item.incident_id}
            src={item.thumbnail_url}
            alt={`${categoryLabel(item.category)} evidence thumbnail`}
            loading="lazy"
          />
          <div className="hover-meta">
            <span className="hover-category" style={{ color: categoryColor(item.category) }}>
              {categoryIcon(item.category)} {categoryLabel(item.category)}
            </span>
            {isScripted(item) && <ScriptedBadge />}
            {isExperimental(item) && <ExperimentalBadge />}
            <span>{fmtTime(item.event_start)}</span>
            <span>{isScripted(item) ? 'Confidence: Not scored' : `Conf: ${(item.peak_confidence ?? 0).toFixed(2)}`}</span>
          </div>
          {/* Slide indicator dots */}
          {rows.length > 1 && (
            <div className="slide-dots">
              {rows.map((_, i) => (
                <span key={i} className={`slide-dot ${i === idx ? 'active' : ''}`} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Notification Timeline Item ──────────────────────────────────────
function TimelineItem({ record }) {
  const channelIcons = {
    telegram: '📨',
    call: '📞',
    button: '🔘',
    escalation: '⏫',
  }
  const statusColors = {
    sent: '#7FE3D0',
    delivered: '#7FE3D0',
    confirmed: '#34D399',
    false_alarm: '#FF7180',
    cancelled: '#9CABC0',
    suppressed: '#FFB829',
    acknowledged: '#34D399',
    failed: '#FF4B3E',
    pending: '#FFB829',
    escalated: '#E74C6F',
  }

  return (
    <div className="timeline-item">
      <div className="timeline-icon">{channelIcons[record.channel] || '📋'}</div>
      <div className="timeline-content">
        <div className="timeline-header">
          <strong style={{ color: statusColors[record.status] || '#CBD8E8' }}>
            {(record.channel || 'unknown').replace(/_/g, ' ')}
          </strong>
          <span className="timeline-status" style={{ color: statusColors[record.status] }}>
            {statusLabel(record.status)}
          </span>
        </div>
        <span className="timeline-time">{fmtDateTime(record.at || record.sent_at || record.timestamp)}</span>
        {record.detail && <span className="timeline-detail">{record.detail}</span>}
        {record.error && <span className="timeline-error">⚠ {record.error}</span>}
      </div>
    </div>
  )
}

// ─── Detail Panel ────────────────────────────────────────────────────
function DetailPanel({ incident, group, onClose, hot, onHot }) {
  if (!incident) {
    return (
      <aside className="detail-panel empty-detail" id="detail-panel">
        <div className="empty-state">
          <div className="empty-icon">🗺️</div>
          <h3>Select a camera</h3>
          <p>Click a numbered marker on the map to inspect verified evidence, dispatch routing, and notification records.</p>
        </div>
      </aside>
    )
  }

  const plan = incident.dispatch_plan || {}
  const det = incident.detection || {}
  const notifications = incident.notifications || []

  return (
    <aside className="detail-panel" id="detail-panel">
      <button className="detail-close" onClick={onClose} aria-label="Close detail panel">✕</button>

      {/* Honesty badges */}
      <div className="detail-badges">
        {isScripted(incident) && <ScriptedBadge />}
        {isExperimental(incident) && <ExperimentalBadge />}
        {incident.status && incident.status !== 'new' && (
          <span className="honesty-badge">{statusLabel(incident.status)}</span>
        )}
        {locationBadge(incident.location_source, incident.location_accuracy_m, incident.location_fix_age_s) && (
          <span className="honesty-badge loc-badge">{locationBadge(incident.location_source, incident.location_accuracy_m, incident.location_fix_age_s)}</span>
        )}
        {incident.source === 'test_replay' && (
          <span className="honesty-badge replay-badge">📹 Recorded footage replay</span>
        )}
        {incident.source === 'live' && (
          <span className="honesty-badge live-badge">🔴 Live detection</span>
        )}
        {group?.camera_type === 'phone' && (
          <span className="honesty-badge phone-badge">Demo phone camera</span>
        )}
        {group?.location_basis === 'simulated_placement' && (
          <span className="honesty-badge sim-badge">Simulated placement</span>
        )}
        {group?.location_basis === 'real_installation' && (
          <span className="honesty-badge">Real installation</span>
        )}
      </div>

      {/* Header */}
      <h2 className="detail-category" style={{ color: categoryColor(incident.category) }}>
        {categoryIcon(incident.category)} {categoryLabel(incident.category)}
      </h2>
      <div className="detail-location">
        <strong>{incident.camera_name}</strong>
        <span>{incident.place_text}</span>
        <span className="detail-time">{fmtDateTime(incident.detected_at)}</span>
      </div>

      {/* Evidence media: stable elements keyed by incident (polling never reloads the video) */}
      <IncidentMedia key={incident.incident_id} incident={incident} />

      {/* Detection metadata */}
      <div className="detail-meta-grid">
        <div className="meta-item">
          <span className="meta-label">{isScripted(incident) ? 'Confidence' : 'Peak / Mean'}</span>
          <span className="meta-value">
            {isScripted(incident) ? 'Not scored' : `${det.peak_confidence?.toFixed(2) ?? '—'} / ${det.mean_confidence?.toFixed(2) ?? '—'}`}
          </span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Threshold</span>
          <span className="meta-value">{isScripted(incident) ? 'Not scored' : (det.threshold_applied ?? '—')}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">{isScripted(incident) ? 'Source' : 'Model'}</span>
          <span className="meta-value mono">{isScripted(incident) ? 'scripted demo' : (det.model_name || '—')}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">{isScripted(incident) ? 'Verified' : 'Frames confirmed'}</span>
          <span className="meta-value">{isScripted(incident) ? 'No' : (det.frames_confirmed || '—')}</span>
        </div>
      </div>

      {isScripted(incident) && (
        <div className="signals-panel scripted-panel">
          <h3 className="detail-section-title">Scripted demo - not a detector result</h3>
          <p className="detail-muted">
            The category was set by the demo script. No detector ran on this clip, nothing was scored and no bounding box or keypoints were drawn
            by a detector. No automatic call is placed unless the “Scripted incidents: call after delay” demo option is on.
          </p>
          <table className="signals-table">
            <tbody>
              <tr><td>event window used</td><td>{incident.video_offset_start_s != null ? `${incident.video_offset_start_s.toFixed(1)}-${incident.video_offset_end_s?.toFixed(1)} s of the clip` : '—'}</td></tr>
              <tr><td>note</td><td>{det.note || 'Scripted demo incident'}</td></tr>
            </tbody>
          </table>
        </div>
      )}
      {isExperimental(incident) && !isScripted(incident) && (
        <div className="signals-panel">
          <h3 className="detail-section-title">Why it fired (experimental)</h3>
          <p className="detail-muted">
            Score {det.peak_confidence?.toFixed(2) ?? '—'} against threshold {det.threshold_applied ?? '—'}. No automatic call is placed for
            experimental detections: a call only happens if an operator presses “Escalate now” in Telegram.
          </p>
          <table className="signals-table">
            <tbody>
              {Object.entries(det.signals || {}).map(([k, v]) => (
                <tr key={k}><td>{k.replace(/_/g, ' ')}</td><td>{String(v)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Status buttons */}
      <div className="detail-actions">
        <StatusButton incident={incident} status="confirmed" label="✓ Acknowledge" color="#34D399" />
        <StatusButton incident={incident} status="false_positive" label="✗ False positive" color="#FF7180" />
      </div>

      <p className="detail-muted">
        {isExperimental(incident)
          ? 'Acknowledge records that you saw it. False positive dismisses the incident.'
          : 'Acknowledge stops the automatic escalation call. False positive dismisses the incident.'}
      </p>

      {/* Notification Timeline */}
      <h3 className="detail-section-title">Notification Timeline</h3>
      {notifications.length > 0 ? (
        <div className="timeline-list">
          {notifications.map((n, i) => <TimelineItem key={i} record={n} />)}
        </div>
      ) : (
        <p className="detail-muted">No notification attempts recorded yet.</p>
      )}

      {/* Dispatch Plan */}
      <h3 className="detail-section-title">Dispatch Plan</h3>
      <DispatchCard incident={incident} hot={hot} onHot={onHot} />
      {plan.contact_policy && (
        <p className="detail-contact-policy">
          ⓘ {plan.contact_policy.replace(/_/g, ' ')}
        </p>
      )}
    </aside>
  )
}

// ─── Status Button ───────────────────────────────────────────────────
function StatusButton({ incident, status, label, color }) {
  const [loading, setLoading] = useState(false)
  const isActive = incident.status === status

  const handleClick = async () => {
    if (isActive || loading) return
    setLoading(true)
    try {
      await api.patch(`/incidents/${incident.incident_id}/status`, { status, reviewed_by: 'dashboard_operator' })
      toast.success(`Incident ${statusLabel(status).toLowerCase()}`)
    } catch {
      toast.error('Failed to update status')
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      className={`status-btn ${isActive ? 'active' : ''}`}
      style={{ '--btn-color': color }}
      onClick={handleClick}
      disabled={loading}
      aria-label={label}
    >
      {loading ? '…' : (isActive && status === 'confirmed' ? '✓ Acknowledged' : label)}
    </button>
  )
}

// ─── Live Camera Tile ────────────────────────────────────────────────
function LiveCameraTile({ camera }) {
  const isOnline = camera.status === 'online'
  return (
    <article className="live-tile" aria-label={`Live feed: ${camera.camera_name}`}>
      {isOnline ? (
        <img
          src={`/api/v1/cameras/${camera.camera_id}/live`}
          alt={`Live annotated stream from ${camera.camera_name}`}
          className="live-feed-img"
        />
      ) : (
        <div className="live-feed-offline">
          <span>📵</span>
          <span>Camera offline</span>
          {camera.error && <span className="live-offline-reason" style={{ fontSize: 12, opacity: 0.8, padding: '0 12px', textAlign: 'center' }}>{camera.error}</span>}
        </div>
      )}
      <div className="live-tile-info">
        <strong>
          {camera.camera_name}
        </strong>
        <div className="live-tile-status">
          <span className={`status-indicator ${isOnline ? 'online' : 'offline'}`} />
          <span className={isOnline ? 'text-online' : 'text-offline'}>
            {camera.status}
          </span>
          {camera.effective_fps != null && (
            <span className="live-fps">{camera.effective_fps} FPS</span>
          )}
        </div>
        {locationBadge(camera.location_source, camera.location_accuracy_m, camera.location_fix_age_s) && (
          <span className="honesty-badge loc-badge">{locationBadge(camera.location_source, camera.location_accuracy_m, camera.location_fix_age_s)}</span>
        )}
        {camera.detectors?.length > 0 && (
          <div className="det-chips" aria-label="Active detectors">
            {camera.detectors.map((d) => (
              <span key={d} className={`det-chip ${['fall', 'violence', 'snatch'].includes(d) ? 'exp' : ''}`}>
                {d}{['fall', 'violence', 'snatch'].includes(d) ? ' EXP' : ''}
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  )
}

// ─── Demo Controls Panel ─────────────────────────────────────────────
function DemoControls({ groups, onRefresh, demoState, onDemoState }) {
  const [triggerLoading, setTriggerLoading] = useState(false)
  const [triggerCategory, setTriggerCategory] = useState('fire')

  const [cameras, setCameras] = useState([])
  const [cameraId, setCameraId] = useState('')
  useEffect(() => {
    api.get('/cameras').then(({ data }) => {
      setCameras(data.cameras || [])
      setCameraId((cur) => cur || data.cameras?.[0]?.camera_id || '')
    }).catch(() => {})
  }, [])

  const handleTrigger = async () => {
    const cam = cameras.find((c) => c.camera_id === cameraId)
    if (!cam) return toast.error('No cameras available')
    const chosen = (demoState?.categories || []).find((c) => c.category === triggerCategory)
    if (chosen && !chosen.enabled) return toast.error(`${chosen.label} unavailable: ${chosen.reason}`)
    setTriggerLoading(true)
    try {
      await api.post('/demo/trigger', { camera_id: cam.camera_id, category: triggerCategory })
      toast.success(`Test ${triggerCategory} incident triggered on ${cam.name}`)
      if (demoState && !demoState.alerts_enabled) toast('Alerts are OFF: no Telegram message and no call are sent. Turn Alerts on in the Demo panel.', { icon: '⚠️', duration: 7000 })
      onRefresh()
      onDemoState?.()
    } catch (err) {
      toast.error(`Trigger failed: ${err.response?.data?.detail || err.message}`)
    } finally {
      setTriggerLoading(false)
    }
  }

  const [busy, setBusy] = useState(false)
  const runDemoAction = async (path, okMessage) => {
    setBusy(true)
    try {
      const { data } = await api.post(path)
      toast.success(`${okMessage} (previous DB backed up: ${data.backup})`)
      onRefresh()
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="demo-controls-panel" role="region" aria-label="Demo controls">
      <div className="demo-controls-header">
        <span className="demo-controls-title">🎛️ Demo Controls</span>
        <span className="demo-controls-hint">Ctrl+Shift+D to toggle</span>
      </div>
      <div className="demo-controls-buttons">
        <button className="demo-btn" disabled={busy} onClick={() => runDemoAction('/demo/showcase', 'Showcase loaded')}
                title="Replace current incidents with demo/showcase.db (current DB is backed up first)">
          📦 Load showcase
        </button>
        <button className="demo-btn" disabled={busy} onClick={() => runDemoAction('/demo/reset', 'Demo reset to 0 incidents')}
                title="Clear all incidents (current DB is backed up first)">
          ♻️ Reset demo
        </button>
        <button className="demo-btn" onClick={onRefresh}>
          🔄 Reset view
        </button>
        <div className="demo-trigger-row">
          <select className="demo-select" value={cameraId} onChange={(e) => setCameraId(e.target.value)} aria-label="Trigger camera">
            {cameras.map((c) => <option key={c.camera_id} value={c.camera_id}>{c.name}</option>)}
          </select>
          <select
            className="demo-select"
            value={triggerCategory}
            onChange={(e) => setTriggerCategory(e.target.value)}
            aria-label="Trigger category"
          >
            {(demoState?.categories || [
              { category: 'fire', label: 'Fire', enabled: true }, { category: 'road_accident', label: 'Crash', enabled: true },
            ]).map((c) => (
              <option key={c.category} value={c.category} disabled={!c.enabled}
                      title={c.enabled ? (c.scripted ? 'SCRIPTED DEMO: the category is set by the demo script, no detector runs on the clip, nothing is scored' : '') : `Unavailable: ${c.reason}`}>
                {({ fire: '🔥', road_accident: '🚗', fall: '🧍', assault: '👊', snatching: '👜' })[c.category]} {c.label}{c.enabled ? '' : ' - unavailable'}
              </option>
            ))}
          </select>
          <button
            className="demo-btn trigger"
            onClick={handleTrigger}
            disabled={triggerLoading}
          >
            {triggerLoading ? '⏳ Triggering…' : '⚡ Trigger test incident'}
          </button>
        </div>
        {(() => {
          const chosen = (demoState?.categories || []).find((c) => c.category === triggerCategory)
          return chosen && !chosen.enabled ? <p className="demo-reason" role="status">{chosen.label} unavailable: {chosen.reason}</p> : null
        })()}
        <div className="demo-dry-row">
          <button className={`demo-btn ${demoState && !demoState.alerts_enabled ? 'dry-on' : ''}`} disabled={!demoState}
                  title="Master switch for every outbound Telegram message and call (ALERTS_ENABLED). Allowlist, DRY RUN, cooldowns and the call cap still apply."
                  onClick={async () => {
                    const turnOn = !demoState?.alerts_enabled
                    if (turnOn && !window.confirm('Turn ALERTS ON? Triggers will send REAL Telegram messages to the demo chat (and calls to the demo phone where the policy allows).')) return
                    try { await api.post('/demo/alerts', { enabled: turnOn }); onDemoState?.() }
                    catch (err) { toast.error(err.response?.data?.detail || err.message) }
                  }}>
            {demoState?.alerts_enabled ? '🔔 Alerts are ON (real Telegram / calls): turn off' : '🔕 Alerts are OFF: nothing is sent (turn on)'}
          </button>
        </div>
        <div className="demo-dry-row">
          <button className={`demo-btn ${demoState?.scripted_auto_call ? 'dry-on' : ''}`} disabled={!demoState}
                  title="Scripted incidents (Fall, Violence, Snatching) never call automatically by default. When ON and DEMO_MODE is true, an unacknowledged scripted incident calls the allowlisted demo phone after the escalation delay. All call safety rules still apply."
                  onClick={async () => {
                    try { await api.post('/demo/scripted-auto-call', { enabled: !demoState?.scripted_auto_call }); onDemoState?.() }
                    catch (err) { toast.error(err.response?.data?.detail || err.message) }
                  }}>
            {demoState?.scripted_auto_call
              ? `📞 Scripted incidents: call after ${demoState?.escalation_delay_s ?? '?'} s is ON${demoState?.scripted_auto_call_effective ? '' : ' (ignored: DEMO_MODE is off)'}: turn off`
              : '📞 Scripted incidents: call after delay is OFF (turn on)'}
          </button>
        </div>
        <div className="demo-dry-row">
          <button className={`demo-btn ${demoState?.dry_run ? 'dry-on' : ''}`} disabled={!demoState}
                  title="DRY RUN: Telegram stays real, calls are suppressed"
                  onClick={async () => {
                    try { await api.post('/demo/dry-run', { enabled: !demoState?.dry_run }); onDemoState?.() }
                    catch (err) { toast.error(err.response?.data?.detail || err.message) }
                  }}>
            {demoState?.dry_run ? '🧪 DRY RUN is ON (calls suppressed): turn off' : '🧪 Dry run: off (turn on to suppress calls)'}
          </button>
        </div>
        {(demoState?.cameras || []).length > 0 && (
          <div className="demo-toggles" role="group" aria-label="Per-camera detector toggles">
            <strong className="demo-toggles-title">Detectors per camera (applied live, no restart)</strong>
            {demoState.cameras.map((cam) => (
              <div key={cam.camera_id} className="demo-toggle-row">
                <span className="demo-toggle-cam">{cam.name}{cam.running ? '' : ' (offline)'}</span>
                {demoState.all_detectors.map((d) => {
                  const on = cam.detectors.includes(d)
                  const exp = ['fall', 'violence', 'snatch'].includes(d)
                  return (
                    <button key={d} className={`det-toggle ${on ? 'on' : ''} ${exp ? 'exp' : ''}`} aria-pressed={on} disabled={!cam.running}
                            title={cam.running ? `Default from cameras.json: ${cam.defaults.includes(d) ? 'on' : 'off'}${exp ? ' (experimental)' : ''}` : 'Camera worker not running'}
                            onClick={async () => {
                              try { await api.post('/demo/detectors', { camera_id: cam.camera_id, detector: d, enabled: !on }); onDemoState?.() }
                              catch (err) { toast.error(err.response?.data?.detail || err.message) }
                            }}>
                      {d}{exp ? ' EXP' : ''}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        )}
        {(demoState?.audit || []).length > 0 && (
          <ul className="demo-audit" aria-label="Session audit trail">
            {demoState.audit.slice(0, 5).map((a, i) => (
              <li key={i}><span>{new Date(a.at).toLocaleTimeString()}</span> {a.action}: {a.detail}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// ─── Loading Skeleton ────────────────────────────────────────────────
function MapSkeleton() {
  return (
    <div className="map-skeleton">
      <div className="skeleton-pulse" style={{ width: '60%', height: 20 }} />
      <div className="skeleton-pulse" style={{ width: '40%', height: 16, marginTop: 8 }} />
      <div className="skeleton-map-area">
        <div className="skeleton-pulse dot" style={{ left: '30%', top: '40%' }} />
        <div className="skeleton-pulse dot" style={{ left: '55%', top: '35%' }} />
        <div className="skeleton-pulse dot" style={{ left: '45%', top: '60%' }} />
      </div>
    </div>
  )
}

// ─── Error State ─────────────────────────────────────────────────────
function ErrorState({ message, onRetry }) {
  return (
    <div className="error-state">
      <span className="error-icon">⚠️</span>
      <h3>Connection Error</h3>
      <p>{message || 'Unable to reach the API. Check that the backend is running.'}</p>
      <button className="demo-btn" onClick={onRetry}>Retry</button>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════
//  MAIN MAP VIEW
// ═════════════════════════════════════════════════════════════════════
export default function MapView() {
  const [groups, setGroups] = useState([])
  const [cameraStatus, setCameraStatus] = useState([])
  const [selected, setSelected] = useState(null)
  const [hoveredId, setHoveredId] = useState(null)
  const [liveId, setLiveId] = useState(null)
  const [showControls, setShowControls] = useState(false)
  const [hotService, setHotService] = useState(null)
  const [styleFailed, setStyleFailed] = useState(false)
  const styleLoadedRef = useRef(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [newIncidentIds, setNewIncidentIds] = useState(new Set())
  const [filterKey, setFilterKey] = useState('all')
  const [demoState, setDemoState] = useState(null)
  const mapRef = useRef(null)
  const prevGroupsRef = useRef([])
  const wsRef = useRef(null)

  // ── Data fetching ──────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    try {
      const [mapRes, camRes] = await Promise.all([
        api.get('/map/groups'),
        api.get('/cameras/status'),
      ])
      const newGroups = mapRes.data.groups || []
      setCameraStatus(camRes.data.cameras || [])

      // Detect new incidents for pulse animation
      const prevIds = new Set()
      prevGroupsRef.current.forEach((g) =>
        (g.incidents || []).forEach((i) => prevIds.add(i.incident_id))
      )
      const freshIds = new Set()
      newGroups.forEach((g) =>
        (g.incidents || []).forEach((i) => {
          if (!prevIds.has(i.incident_id)) freshIds.add(i.incident_id)
        })
      )

      if (freshIds.size > 0 && prevGroupsRef.current.length > 0) {
        // Find the group with the newest incident for fly-to
        const newestGroup = newGroups.find((g) =>
          (g.incidents || []).some((i) => freshIds.has(i.incident_id))
        )
        if (newestGroup) {
          const newestInc = (newestGroup.incidents || []).find((i) => freshIds.has(i.incident_id))
          toast(
            `🚨 New ${categoryLabel(newestInc?.category || 'incident')} at ${newestGroup.camera_name}`,
            {
              icon: '🔴',
              duration: 5000,
              style: {
                background: '#1a1020',
                border: `1px solid ${categoryColor(newestInc?.category)}`,
                color: '#f4f7fb',
                fontSize: '14px',
                fontWeight: 600,
              },
            }
          )
          // Fly to the new incident
          if (mapRef.current && !PREFERSREDUCEDMOTION) {
            mapRef.current.flyTo({
              center: [newestGroup.longitude, newestGroup.latitude],
              zoom: 15,
              duration: 1200,
            })
          }
        }
        setNewIncidentIds(freshIds)
        // Clear pulse after 4s
        setTimeout(() => setNewIncidentIds(new Set()), 4000)
      }

      prevGroupsRef.current = newGroups
      setGroups(newGroups)
      setError(null)
    } catch (err) {
      if (groups.length === 0) setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [groups.length])

  // ── WebSocket push (shared connection from WebSocketProvider) ──────
  // The server pushes {type:"incident_created"}; any such message triggers an
  // immediate refresh. The 2 s polling below stays as the fallback.
  const { lastMessage } = useWebSocket()
  useEffect(() => {
    if (lastMessage?.type === 'incident_created') fetchData()
  }, [lastMessage, fetchData])

  // ── Demo state (dry run, category availability, per-camera detectors, audit tail) ──
  const refreshDemoState = useCallback(() => {
    api.get('/demo-state').then(({ data }) => setDemoState(data)).catch(() => {})
  }, [])
  useEffect(() => {
    refreshDemoState()
    const id = setInterval(refreshDemoState, 5000)
    return () => clearInterval(id)
  }, [refreshDemoState])

  // ── Polling fallback (2s) ──────────────────────────────────────────
  useEffect(() => {
    fetchData()
    const id = setInterval(fetchData, POLL_MS)
    return () => clearInterval(id)
  }, [fetchData])

  // ── Demo controls: header "Demo" button (Layout) and Ctrl+Shift+D ──
  useEffect(() => {
    const toggle = () => setShowControls((v) => !v)
    window.addEventListener('toggle-demo-controls', toggle)
    return () => window.removeEventListener('toggle-demo-controls', toggle)
  }, [])

  useEffect(() => {
    const handler = (e) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'd') {
        e.preventDefault()
        setShowControls((v) => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // ── Fit map to all cameras on load ─────────────────────────────────
  useEffect(() => {
    if (!TOKEN || !groups.length || !mapRef.current) return
    const lngs = groups.map((g) => g.longitude)
    const lats = groups.map((g) => g.latitude)
    mapRef.current.fitBounds(
      [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
      { padding: 100, maxZoom: 14, duration: PREFERSREDUCEDMOTION ? 0 : 600 }
    )
  }, [groups.length > 0 && loading === false]) // only on initial load

  // ── Fly back to overview ───────────────────────────────────────────
  const flyToOverview = useCallback(() => {
    if (!mapRef.current || !groups.length) return
    const lngs = groups.map((g) => g.longitude)
    const lats = groups.map((g) => g.latitude)
    mapRef.current.fitBounds(
      [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
      { padding: 100, maxZoom: 14, duration: PREFERSREDUCEDMOTION ? 0 : 800 }
    )
    setSelected(null)
    setLiveId(null)
  }, [groups])

  // ── Select a camera group (click marker → detail panel) ────────────
  const selectGroup = useCallback(
    async (group) => {
      try {
        const incId = group.incidents?.[0]?.incident_id
        if (!incId) return
        const { data } = await api.get(`/incidents/${incId}`)
        setSelected(data)
        setLiveId(group.camera_id)
      } catch (err) {
        toast.error('Failed to load incident details')
      }
    },
    []
  )

  // ── Selecting an incident: fit the map to it plus its services (eased) ──
  const planKey = selected ? `${selected.incident_id}|${selected.dispatch_plan?.created_at || ''}` : ''
  useEffect(() => {
    setHotService(null)
    if (!selected || !mapRef.current) return
    if (fitToDispatch(mapRef, selected)) return
    const g = groups.find((x) => x.camera_id === selected.camera_id)
    if (g && !PREFERSREDUCEDMOTION) mapRef.current.flyTo({ center: [g.longitude, g.latitude], zoom: 15, duration: 700 })
  }, [planKey])  // eslint-disable-line react-hooks/exhaustive-deps
  const dispatchTypes = useMemo(() => dispatchModel(selected).types, [planKey])  // eslint-disable-line react-hooks/exhaustive-deps

  // offline: if the Mapbox style never loads, swap to the local blank style once
  useEffect(() => {
    const t = setTimeout(() => { if (!styleLoadedRef.current) setStyleFailed(true) }, 8000)
    return () => clearTimeout(t)
  }, [])

  // ── Display-only offset for cameras within 15 m of each other (stored coordinates never change) ──
  const cameraOffsets = useMemo(() => {
    const offsets = {}
    const spread = [[-12, -8], [12, 8], [-12, 12], [12, -12]]
    groups.forEach((g, i) => {
      const near = groups.filter((o, j) => j !== i && metres(g, o) < CLOSE_CAMERA_M)
      if (near.length) {
        const cluster = [g, ...near].map((x) => x.camera_id).sort()
        offsets[g.camera_id] = spread[cluster.indexOf(g.camera_id) % spread.length]
      }
    })
    return offsets
  }, [groups.map((g) => `${g.camera_id}:${g.latitude}:${g.longitude}`).join('|')])  // eslint-disable-line react-hooks/exhaustive-deps

  // filter chips: hide cameras with no incident of the chosen category (stored data unchanged)
  const visibleGroups = useMemo(() => {
    const cats = FILTERS.find((f) => f.key === filterKey)?.cats
    if (!cats) return groups
    return groups
      .map((g) => ({ ...g, incidents: (g.incidents || []).filter((i) => cats.includes(i.category)) }))
      .filter((g) => g.incidents.length > 0)
      .map((g) => ({ ...g, count: g.incidents.length }))
  }, [groups, filterKey])

  // soft accuracy circle for the selected camera (device GPS only)
  const selectedGroup = groups.find((g) => g.camera_id === selected?.camera_id)
  const accuracyCircle = useMemo(
    () => (selectedGroup?.location_source === 'device_gps' && selectedGroup.location_accuracy_m
      ? circlePolygon(selectedGroup.longitude, selectedGroup.latitude, selectedGroup.location_accuracy_m) : null),
    [selectedGroup?.location_source, selectedGroup?.location_accuracy_m, selectedGroup?.latitude, selectedGroup?.longitude])  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Live cameras (show all, highlight phones) ──────────────────────
  const liveCameras = useMemo(
    () => cameraStatus.filter((c) => c.camera_type === 'phone'),
    [cameraStatus]
  )

  // ═══════════════════════════════════════════════════════════════════
  //  RENDER
  // ═══════════════════════════════════════════════════════════════════

  if (loading && groups.length === 0) return <section className="demo-page"><MapSkeleton /></section>
  if (error && groups.length === 0) return <section className="demo-page"><ErrorState message={error} onRetry={fetchData} /></section>

  return (
    <section className="demo-page" id="hackathon-dashboard">
      {/* ── Header ───────────────────────────────────────────────── */}
      <header className="demo-header">
        <div className="demo-header-left">
          <span className="demo-mode-badge" aria-label="Demo mode active">DEMO MODE</span>
          {demoState?.dry_run && <span className="demo-mode-badge dry-run-badge" aria-label="Dry run: calls are suppressed">DRY RUN</span>}
          {demoState && !demoState.alerts_enabled && <span className="demo-mode-badge dry-run-badge" aria-label="Alerts off: no Telegram or calls">ALERTS OFF</span>}
          <div>
            <h1 className="demo-title">Live Incident Command Map</h1>
            <p className="demo-subtitle">
              Camera-level locations · dispatcher-reviewed evidence · real-time detection
            </p>
          </div>
        </div>
        <button className="overview-btn" onClick={flyToOverview} aria-label="Back to overview">
          ← Back to overview
        </button>
      </header>

      {/* ── Demo Controls (hidden, Ctrl+Shift+D) ─────────────────── */}
      {showControls && <DemoControls groups={groups} onRefresh={fetchData} demoState={demoState} onDemoState={refreshDemoState} />}

      {/* ── Main Grid: Map + Detail ──────────────────────────────── */}
      <div className="demo-grid">
        {/* Map Container */}
        <div className="map-container">
          {TOKEN ? (
            <Map
              ref={mapRef}
              mapboxAccessToken={TOKEN}
              initialViewState={{ longitude: 75.79, latitude: 26.91, zoom: 12 }}
              mapStyle={styleFailed ? BLANK_STYLE : 'mapbox://styles/mapbox/dark-v11'}
              onLoad={() => { styleLoadedRef.current = true }}
              onError={(e) => { if (!styleLoadedRef.current || !e?.target?.isStyleLoaded?.()) setStyleFailed(true) }}
              style={{ width: '100%', height: '100%' }}
              attributionControl={false}
            >
              {visibleGroups.map((g, idx) => {
                const mainCategory = mostSevereCategory(g.incidents)
                const color = categoryColor(mainCategory)
                const isExp = g.incidents.some(isExperimental)
                const isNew = (g.incidents || []).some((i) => newIncidentIds.has(i.incident_id))
                const isLive = liveId === g.camera_id
                const isPhone = g.camera_type === 'phone'
                const isHovered = hoveredId === g.camera_id

                return (
                  <Marker key={g.camera_id} longitude={g.longitude} latitude={g.latitude} offset={cameraOffsets[g.camera_id] || [0, 0]}>
                    <button
                      className={[
                        'camera-marker',
                        isNew && !PREFERSREDUCEDMOTION ? 'pulse' : '',
                        isLive ? 'selected' : '',
                        isPhone ? 'phone' : '',
                        isExp ? 'experimental' : '',
                      ].filter(Boolean).join(' ')}
                      style={{ '--marker-color': color }}
                      onMouseEnter={() => setHoveredId(g.camera_id)}
                      onMouseLeave={() => setHoveredId(null)}
                      onClick={() => selectGroup(g)}
                      aria-label={`Camera ${idx + 1}: ${g.camera_name}, ${g.count} incidents`}
                      title={cameraOffsets[g.camera_id] ? `Offset on screen only: cameras within ${CLOSE_CAMERA_M} m (stored coordinates unchanged)` : undefined}
                    >
                      <span className="marker-number">{idx + 1}</span>
                      {isExp && <span className="marker-exp" aria-label={g.incidents.some(isScripted) ? 'scripted demo incident' : 'experimental detector'}>{g.incidents.some(isScripted) ? 'SCRIPTED' : 'EXP'}</span>}
                      {isNew && <span className="marker-pulse-ring" />}
                    </button>
                    {isHovered && (
                      <HoverPopup group={g} onPin={() => selectGroup(g)} />
                    )}
                  </Marker>
                )
              })}

              {accuracyCircle && (
                <Source id="gps-accuracy" type="geojson" data={accuracyCircle}>
                  <Layer id="gps-accuracy-fill" type="fill" paint={{ 'fill-color': '#7FE3D0', 'fill-opacity': 0.12 }} />
                  <Layer id="gps-accuracy-line" type="line" paint={{ 'line-color': '#7FE3D0', 'line-opacity': 0.55, 'line-width': 1.5 }} />
                </Source>
              )}
              {/* Service markers + routes for the selected incident only */}
              <DispatchLayer incident={selected} hot={hotService} onHot={setHotService} />
            </Map>
          ) : (
            /* ── Mapbox-free fallback ─────────────────────────────── */
            <div className="map-fallback">
              <div className="fallback-dots">
                {visibleGroups.map((g, idx) => {
                  const mainCategory = mostSevereCategory(g.incidents)
                  return (
                    <button
                      key={g.camera_id}
                      className={`camera-marker fallback ${g.camera_type === 'phone' ? 'phone' : ''} ${g.incidents.some(isExperimental) ? 'experimental' : ''}`}
                      style={{
                        '--marker-color': categoryColor(mainCategory),
                        left: `${12 + (idx * 23) % 76}%`,
                        top: `${15 + (idx * 31) % 65}%`,
                      }}
                      onClick={() => selectGroup(g)}
                      aria-label={`Camera ${idx + 1}: ${g.camera_name}`}
                    >
                      <span className="marker-number">{idx + 1}</span>
                    </button>
                  )
                })}
              </div>
              <p className="fallback-label">
                Map tiles unavailable — showing camera positions with straight-line routing fallback.
                <br />Set <code>VITE_MAPBOX_TOKEN</code> in <code>frontend/.env</code> for full map rendering.
              </p>
            </div>
          )}

          {/* Filter chips */}
          <div className="filter-chips" role="group" aria-label="Filter incidents by category">
            {FILTERS.map((f) => (
              <button key={f.key} className={`filter-chip ${filterKey === f.key ? 'active' : ''}`}
                      aria-pressed={filterKey === f.key} onClick={() => setFilterKey(f.key)}>
                {f.label}{f.exp && <span className="chip-exp">EXP</span>}
              </button>
            ))}
          </div>

          {/* Legend */}
          <div className="map-legend" role="img" aria-label="Map legend">
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#FF951F' }} />
              <span>Fire</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#FF4B3E' }} />
              <span>Crash</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot exp-dot" style={{ background: '#E74C6F' }} />
              <span>Violence <em className="legend-exp">exp.</em></span>
            </div>
            <div className="legend-item">
              <span className="legend-dot exp-dot" style={{ background: '#FFB829' }} />
              <span>Fall <em className="legend-exp">exp.</em></span>
            </div>
            <div className="legend-item">
              <span className="legend-dot exp-dot" style={{ background: '#A97BFF' }} />
              <span>Snatch <em className="legend-exp">exp.</em></span>
            </div>
            <div className="legend-item" title="Fall, Violence and Snatch demo incidents are created by the demo script: no detector ran">
              <span className="legend-scripted">SCRIPTED</span>
              <span>= demo script</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot phone-ring-legend" />
              <span>Demo phone</span>
            </div>
          </div>

          <DispatchLegend types={dispatchTypes} />

          {/* Empty state overlay */}
          {groups.length === 0 && !loading && (
            <div className="map-empty-overlay">
              <span>No incidents detected yet.</span>
              <span>Camera feeds are being monitored in real time.</span>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        <DetailPanel incident={selected} group={groups.find((g) => g.camera_id === selected?.camera_id)} onClose={() => { setSelected(null); setLiveId(null) }} hot={hotService} onHot={setHotService} />
      </div>

      {/* ── Live Cameras Panel ────────────────────────────────────── */}
      <section className="live-cameras-section" id="live-cameras-panel">
        <h2 className="section-title">
          Live Cameras
          <span className="section-count">{liveCameras.length}</span>
        </h2>
        {liveCameras.length > 0 ? (
          <div className="live-cameras-grid">
            {liveCameras.map((cam) => (
              <LiveCameraTile key={cam.camera_id} camera={cam} />
            ))}
          </div>
        ) : (
          <div className="live-cameras-empty">
            <p>
              No demo phone cameras registered. Use{' '}
              <code>python scripts/add_phone_camera.py</code> to add one.
            </p>
          </div>
        )}
      </section>
    </section>
  )
}

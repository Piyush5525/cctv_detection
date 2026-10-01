import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Map, { Marker, Source, Layer } from 'react-map-gl/mapbox'
import 'mapbox-gl/dist/mapbox-gl.css'
import toast from 'react-hot-toast'
import api from '../utils/api'
import { useWebSocket } from '../context/WebSocketContext'

// ─── Constants ───────────────────────────────────────────────────────
const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN
const POLL_MS = 2000
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

const categoryLabel = (cat) =>
  (cat || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

const evidenceUrl = (incident, name) =>
  `/api/v1/evidence/v2/${incident.camera_id}/${(incident.event_start || '').slice(0, 10)}/${incident.incident_id}/${name}`

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
    const id = setInterval(() => setIdx((x) => (x + 1) % rows.length), SLIDE_MS)
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
            src={item.thumbnail_url}
            alt={`${categoryLabel(item.category)} evidence thumbnail`}
            loading="lazy"
          />
          <div className="hover-meta">
            <span className="hover-category" style={{ color: categoryColor(item.category) }}>
              {categoryLabel(item.category)}
            </span>
            <span>{fmtTime(item.event_start)}</span>
            <span>Conf: {(item.peak_confidence ?? 0).toFixed(2)}</span>
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
            {record.status}
          </span>
        </div>
        <span className="timeline-time">{fmtDateTime(record.at || record.sent_at || record.timestamp)}</span>
        {record.detail && <span className="timeline-detail">{record.detail}</span>}
        {record.error && <span className="timeline-error">⚠ {record.error}</span>}
      </div>
    </div>
  )
}

// ─── Dispatch Assignment Card ────────────────────────────────────────
function DispatchCard({ assignment }) {
  const service = assignment.service
  const route = assignment.route
  const icons = { hospital: '🏥', police: '🚔', fire: '🚒' }

  return (
    <div className="dispatch-card">
      <div className="dispatch-header">
        <span className="dispatch-icon">{icons[assignment.service_category] || '🏢'}</span>
        <strong>{(assignment.service_category || '').replace(/_/g, ' ')}</strong>
      </div>
      {assignment.status === 'unavailable' ? (
        <span className="dispatch-unavailable">{assignment.reason || 'Lookup unavailable'}</span>
      ) : service ? (
        <>
          <span className="dispatch-name">{service.title || service.name || 'Unknown'}</span>
          <span className="dispatch-phone">{service.phone || 'No phone listed'}</span>
          {route && (
            <div className="dispatch-route-info">
              <span>{route.distance_km ?? '?'} km</span>
              <span className="dispatch-dot">·</span>
              <span>{route.eta_minutes ?? '?'} min ETA</span>
              {route.route_source === 'straight_line_fallback' && (
                <span className="dispatch-fallback-note">≈ straight line</span>
              )}
            </div>
          )}
        </>
      ) : (
        <span className="dispatch-unavailable">Pending lookup</span>
      )}
    </div>
  )
}

// ─── Detail Panel ────────────────────────────────────────────────────
function DetailPanel({ incident, group, onClose }) {
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
        {categoryLabel(incident.category)}
      </h2>
      <div className="detail-location">
        <strong>{incident.camera_name}</strong>
        <span>{incident.place_text}</span>
        <span className="detail-time">{fmtDateTime(incident.detected_at)}</span>
      </div>

      {/* Evidence media */}
      <div className="detail-media">
        <video
          controls
          src={evidenceUrl(incident, 'clip.mp4')}
          poster={evidenceUrl(incident, 'thumbnail.jpg')}
          className="detail-video"
          preload="metadata"
        />
        <img
          src={evidenceUrl(incident, 'best_frame.jpg')}
          alt="Best evidence frame"
          className="detail-best-frame"
          loading="lazy"
        />
      </div>

      {/* Detection metadata */}
      <div className="detail-meta-grid">
        <div className="meta-item">
          <span className="meta-label">Peak / Mean</span>
          <span className="meta-value">
            {det.peak_confidence?.toFixed(2) ?? '—'} / {det.mean_confidence?.toFixed(2) ?? '—'}
          </span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Threshold</span>
          <span className="meta-value">{det.threshold_applied ?? '—'}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Model</span>
          <span className="meta-value mono">{det.model_name || '—'}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Frames confirmed</span>
          <span className="meta-value">{det.frames_confirmed || '—'}</span>
        </div>
      </div>

      {/* Status buttons */}
      <div className="detail-actions">
        <StatusButton incident={incident} status="confirmed" label="✓ Acknowledge" color="#34D399" />
        <StatusButton incident={incident} status="false_positive" label="✗ False positive" color="#FF7180" />
      </div>

      <p className="detail-muted">Acknowledge stops the automatic escalation call. False positive dismisses the incident.</p>

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
      {plan.assignments?.length > 0 ? (
        <div className="dispatch-list">
          {plan.assignments.map((a, i) => <DispatchCard key={i} assignment={a} />)}
        </div>
      ) : (
        <p className="detail-muted">Dispatch lookup pending or unavailable.</p>
      )}
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
      toast.success(`Incident marked as ${status.replace(/_/g, ' ')}`)
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
      {loading ? '…' : label}
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
        </div>
      )}
      <div className="live-tile-info">
        <strong>
          {camera.camera_type === 'phone' ? 'Demo phone camera' : ''} {camera.camera_name}
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
      </div>
    </article>
  )
}

// ─── Demo Controls Panel ─────────────────────────────────────────────
function DemoControls({ groups, onRefresh }) {
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
    setTriggerLoading(true)
    try {
      await api.post('/demo/trigger', { camera_id: cam.camera_id, category: triggerCategory })
      toast.success(`Test ${triggerCategory} incident triggered on ${cam.name}`)
      onRefresh()
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
            <option value="fire">🔥 Fire</option>
            <option value="road_accident">🚗 Crash</option>
          </select>
          <button
            className="demo-btn trigger"
            onClick={handleTrigger}
            disabled={triggerLoading}
          >
            {triggerLoading ? '⏳ Triggering…' : '⚡ Trigger test incident'}
          </button>
        </div>
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [newIncidentIds, setNewIncidentIds] = useState(new Set())
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

  // ── Polling fallback (2s) ──────────────────────────────────────────
  useEffect(() => {
    fetchData()
    const id = setInterval(fetchData, POLL_MS)
    return () => clearInterval(id)
  }, [fetchData])

  // ── Keyboard shortcut for demo controls ────────────────────────────
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
        if (mapRef.current && !PREFERSREDUCEDMOTION) {
          mapRef.current.flyTo({
            center: [group.longitude, group.latitude],
            zoom: 15,
            duration: 700,
          })
        }
      } catch (err) {
        toast.error('Failed to load incident details')
      }
    },
    []
  )

  // ── Dispatch route overlay on map ──────────────────────────────────
  const routeGeoJSON = useMemo(() => {
    if (!selected?.dispatch_plan?.assignments) return null
    const coords = selected.dispatch_plan.assignments
      .filter((a) => a.route?.geometry?.coordinates)
      .flatMap((a) => a.route.geometry.coordinates)
    if (coords.length < 2) return null
    // Build individual line features for each assignment
    const features = selected.dispatch_plan.assignments
      .filter((a) => a.route?.geometry)
      .map((a) => ({
        type: 'Feature',
        geometry: a.route.geometry,
        properties: { category: a.service_category },
      }))
    return { type: 'FeatureCollection', features }
  }, [selected])

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
      {showControls && <DemoControls groups={groups} onRefresh={fetchData} />}

      {/* ── Main Grid: Map + Detail ──────────────────────────────── */}
      <div className="demo-grid">
        {/* Map Container */}
        <div className="map-container">
          {TOKEN ? (
            <Map
              ref={mapRef}
              mapboxAccessToken={TOKEN}
              initialViewState={{ longitude: 75.79, latitude: 26.91, zoom: 12 }}
              mapStyle="mapbox://styles/mapbox/dark-v11"
              style={{ width: '100%', height: '100%' }}
              attributionControl={false}
            >
              {groups.map((g, idx) => {
                const mainCategory = mostSevereCategory(g.incidents)
                const color = categoryColor(mainCategory)
                const isNew = (g.incidents || []).some((i) => newIncidentIds.has(i.incident_id))
                const isLive = liveId === g.camera_id
                const isPhone = g.camera_type === 'phone'
                const isHovered = hoveredId === g.camera_id

                return (
                  <Marker key={g.camera_id} longitude={g.longitude} latitude={g.latitude}>
                    <button
                      className={[
                        'camera-marker',
                        isNew && !PREFERSREDUCEDMOTION ? 'pulse' : '',
                        isLive ? 'selected' : '',
                        isPhone ? 'phone' : '',
                      ].filter(Boolean).join(' ')}
                      style={{ '--marker-color': color }}
                      onMouseEnter={() => setHoveredId(g.camera_id)}
                      onMouseLeave={() => setHoveredId(null)}
                      onClick={() => selectGroup(g)}
                      aria-label={`Camera ${idx + 1}: ${g.camera_name}, ${g.count} incidents`}
                    >
                      <span className="marker-number">{idx + 1}</span>
                      {isNew && <span className="marker-pulse-ring" />}
                    </button>
                    {isHovered && (
                      <HoverPopup group={g} onPin={() => selectGroup(g)} />
                    )}
                  </Marker>
                )
              })}

              {/* Dispatch route lines */}
              {routeGeoJSON && (
                <Source type="geojson" data={routeGeoJSON}>
                  <Layer
                    type="line"
                    paint={{
                      'line-color': '#7FE3D0',
                      'line-width': 3,
                      'line-dasharray': [2, 2],
                      'line-opacity': 0.8,
                    }}
                  />
                </Source>
              )}
            </Map>
          ) : (
            /* ── Mapbox-free fallback ─────────────────────────────── */
            <div className="map-fallback">
              <div className="fallback-dots">
                {groups.map((g, idx) => {
                  const mainCategory = mostSevereCategory(g.incidents)
                  return (
                    <button
                      key={g.camera_id}
                      className={`camera-marker fallback ${g.camera_type === 'phone' ? 'phone' : ''}`}
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
              <span className="legend-dot" style={{ background: '#E74C6F' }} />
              <span>Assault</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot" style={{ background: '#A97BFF' }} />
              <span>Snatch</span>
            </div>
            <div className="legend-item">
              <span className="legend-dot phone-ring-legend" />
              <span>Demo phone</span>
            </div>
          </div>

          {/* Empty state overlay */}
          {groups.length === 0 && !loading && (
            <div className="map-empty-overlay">
              <span>No incidents detected yet.</span>
              <span>Camera feeds are being monitored in real time.</span>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        <DetailPanel incident={selected} group={groups.find((g) => g.camera_id === selected?.camera_id)} onClose={() => { setSelected(null); setLiveId(null) }} />
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

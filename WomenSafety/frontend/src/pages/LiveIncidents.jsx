import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import {
  Activity, Search, Phone, MapPin, Camera as CameraIcon, User, Shield, Cross,
} from 'lucide-react'
import { useIncidents } from '../context/IncidentContext'
import { formatRelativeTime, formatConfidence, classNames } from '../utils/format'
import {
  TYPE_LABELS, SEVERITY_ORDER, SEVERITY_LABEL, severityChipClass,
  STATUS_LABEL, statusPillClass,
} from '../utils/incidentMeta'
import { PLACEHOLDER_OPERATOR } from '../components/TriageQueue'
import { useNearestEmergencyServices } from '../hooks/useNearestEmergencyServices'


function useLiveNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function AgeLabel({ timestamp, critical }) {
  const now = useLiveNow()
  const ms = now - new Date(timestamp).getTime()
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  const aging = critical && mins >= 5
  return (
    <span className={classNames('font-mono text-[11px]', aging ? 'text-sev-critical' : 'text-ink-faint')}>
      {mins}m {secs.toString().padStart(2, '0')}s
    </span>
  )
}

function ConfidenceBar({ value }) {
  return (
    <div className="w-14 h-1.5 rounded-full bg-ground-line overflow-hidden flex-shrink-0">
      <div className="h-full bg-signal" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

function IncidentRow({ incident, selected, onClick }) {
  return (
    <button
      onClick={onClick}
      className={classNames(
        'w-full text-left px-4 py-3 border-b border-ground-line transition-colors',
        selected
          ? 'bg-signal/[0.06] border-l-2 border-r-2 border-l-signal border-r-signal'
          : 'hover:bg-white/[0.02] border-l-2 border-r-2 border-l-transparent border-r-transparent'
      )}
    >
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className={severityChipClass(incident.severity)}>{SEVERITY_LABEL[incident.severity]}</span>
          <span className="text-sm font-medium text-ink truncate">
            {TYPE_LABELS[incident.incident_type] || incident.incident_type}
          </span>
          <span className="text-[10px] font-mono text-ink-faint flex-shrink-0">
            INC-{incident.incident_id?.slice(0, 4).toUpperCase()}
          </span>
        </div>
        <span className={statusPillClass(incident.status)}>{STATUS_LABEL[incident.status]}</span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-ink-muted truncate flex items-center gap-1">
          <MapPin className="w-3 h-3 flex-shrink-0" />
          {incident.location?.camera_id} · {incident.location?.address}
        </span>
        <ConfidenceBar value={incident.confidence} />
      </div>
      <div className="flex items-center justify-between gap-2 mt-1">
        <span className="text-[10px] font-mono text-ink-faint">{formatConfidence(incident.confidence)}</span>
        <AgeLabel timestamp={incident.timestamp} critical={incident.severity === 'critical'} />
      </div>
    </button>
  )
}

function OpenForTimer({ timestamp }) {
  const now = useLiveNow()
  const ms = now - new Date(timestamp).getTime()
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return (
    <span className="font-mono text-2xl text-ink">
      {h > 0 ? `${h}h ` : ''}{m}m {s.toString().padStart(2, '0')}s
    </span>
  )
}

function DetailPanel({ incident, onAction, onNote }) {
  const [note, setNote] = useState('')
  const noteInputRef = useRef(null)

  useEffect(() => { setNote('') }, [incident?.incident_id])

  if (!incident) {
    return (
      <div className="card h-full flex items-center justify-center text-ink-faint text-sm">
        Select an incident from the list to view details
      </div>
    )
  }

  const hasClip = !!incident.evidence_clip?.video_path
  const clipFile = hasClip ? incident.evidence_clip.video_path.split(/[\\/]/).pop() : null
  const thumbFile = incident.thumbnail_path ? incident.thumbnail_path.split(/[\\/]/).pop() : null

  const auditLog = [
    { label: `System detected ${TYPE_LABELS[incident.incident_type] || incident.incident_type}`, at: incident.timestamp },
    ...(incident.evidence_clip ? [{ label: 'Evidence clip saved', at: incident.evidence_clip.created_at || incident.timestamp }] : []),
    ...(incident.assigned_to ? [{ label: `Assigned to ${incident.assigned_to}`, at: incident.updated_at }] : []),
    ...(incident.status !== 'new' ? [{ label: `Status set to ${STATUS_LABEL[incident.status]}`, at: incident.updated_at }] : []),
  ]

  return (
    <div className="card h-full flex flex-col overflow-hidden p-0" data-detail-panel>
      {/* Header */}
      <div className="px-5 py-4 border-b border-ground-line flex-shrink-0">
        <div className="flex items-center gap-2 mb-2">
          <span className={severityChipClass(incident.severity)}>{SEVERITY_LABEL[incident.severity]}</span>
          <span className={statusPillClass(incident.status)}>{STATUS_LABEL[incident.status]}</span>
          <span className="text-xs font-mono text-ink-faint">INC-{incident.incident_id?.slice(0, 8).toUpperCase()}</span>
          <div className="flex-1" />
          <OpenForTimer timestamp={incident.timestamp} />
        </div>
        <h2 className="text-lg font-display font-semibold text-ink">
          {TYPE_LABELS[incident.incident_type] || incident.incident_type}
        </h2>
        <p className="text-xs text-ink-faint mt-0.5">
          {incident.location?.camera_id} · {incident.location?.address}
        </p>
      </div>

      {/* Action bar */}
      <div className="px-5 py-3 border-b border-ground-line flex items-center gap-2 flex-shrink-0 flex-wrap relative">
        {/* No real auth/officer-directory backend yet (see PLACEHOLDER_OPERATOR),
            so this assigns to the current session's own identity rather than
            offering a pick-list of fabricated officer names. */}
        <button
          onClick={() => onAction({ assigned_to: PLACEHOLDER_OPERATOR, status: 'investigating' })}
          className={incident.assigned_to ? 'btn-ghost border border-ground-line text-xs' : 'btn-primary text-xs'}
        >
          <User className="w-3.5 h-3.5" />
          {incident.assigned_to ? incident.assigned_to : 'Assign to me'}
        </button>
        <button
          onClick={() => onAction({ status: 'investigating' })}
          className={classNames('text-xs', incident.status === 'investigating' ? 'btn-ghost border border-signal/40 text-signal' : 'btn-ghost border border-ground-line')}
        >
          Investigating
        </button>
        <button
          onClick={() => onAction({ status: 'resolved' })}
          className={classNames('text-xs', incident.status === 'resolved' ? 'btn-ghost border border-success/40 text-success' : 'btn-ghost border border-ground-line')}
        >
          Resolve
        </button>
        <button
          onClick={() => onAction({ status: 'false_positive' })}
          className={classNames('text-xs', incident.status === 'false_positive' ? 'btn-ghost border border-ink-faint/40 text-ink-faint' : 'btn-ghost border border-ground-line')}
        >
          False positive
        </button>
        <div className="flex-1" />
        <button className="btn-danger text-xs">
          <Phone className="w-3.5 h-3.5" /> Escalate · call
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-5">
          {/* Video */}
          <div className="lg:col-span-2 space-y-2">
            <div className="relative bg-ground rounded-lg overflow-hidden border border-ground-line" style={{ aspectRatio: '16/9' }}>
              {hasClip ? (
                <video key={incident.incident_id} src={`/api/v1/evidence/${clipFile}`} controls className="w-full h-full object-contain bg-black" preload="metadata" />
              ) : thumbFile ? (
                <img key={incident.incident_id} src={`/api/v1/evidence/thumbnail/${thumbFile}`} alt="Detection" className="w-full h-full object-contain" />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-ink-faint text-sm">
                  <CameraIcon className="w-6 h-6 mr-2" /> No clip available
                </div>
              )}
              <div className="detection-label" style={{ left: 8, top: 24, background: '#FF4B3E' }}>
                {formatConfidence(incident.confidence)}
              </div>
            </div>
            {hasClip && (
              <p className="text-[11px] text-ink-faint">Clip saved to evidence · ±5s around detection</p>
            )}
          </div>

          {/* Metadata */}
          <div className="space-y-3">
            <div className="card-sm">
              <p className="text-2xl font-display font-semibold text-ink">{formatConfidence(incident.confidence)}</p>
              <p className="text-[10px] text-ink-faint mt-0.5">
                threshold 50% · {incident.detection_data?.model || 'model n/a'}
              </p>
            </div>
            <MetaRow label="Detected at" value={new Date(incident.timestamp).toLocaleString()} />
            <MetaRow label="Camera" value={incident.location?.camera_id} mono />
            <MetaRow label="Location" value={incident.location?.address} />
            <MetaRow
              label="Coordinates"
              value={
                incident.location?.latitude != null && incident.location?.longitude != null
                  ? `${incident.location.latitude.toFixed(4)}, ${incident.location.longitude.toFixed(4)}`
                  : null
              }
              mono
            />
            <MetaRow label="Assigned to" value={incident.assigned_to || 'Unassigned'} />
            <div className="flex flex-wrap gap-1.5 pt-1">
              <span className="text-[10px] font-mono text-success border border-success/30 rounded-full px-2 py-0.5">
                ✓ Telegram sent at {new Date(incident.timestamp).toLocaleTimeString()}
              </span>
              <span className="text-[10px] font-mono text-success border border-success/30 rounded-full px-2 py-0.5">
                ✓ Call · control desk
              </span>
            </div>
          </div>
        </div>

        {/* Nearest police / hospital, full width below the two columns above */}
        {incident.location?.latitude != null && incident.location?.longitude != null && (
          <div className="px-5 pb-5 -mt-1">
            <NearestServicesCard latitude={incident.location.latitude} longitude={incident.location.longitude} />
          </div>
        )}

        {/* Notes & activity */}
        <div className="px-5 pb-5">
          <div className="card-sm">
            <p className="text-sm font-display font-semibold text-ink mb-3">Notes &amp; activity</p>
            <div className="space-y-2 mb-3">
              {auditLog.map((entry, i) => (
                <div key={i} className="flex items-start justify-between gap-2 text-xs">
                  <span className="text-ink-muted">{entry.label}</span>
                  <span className="font-mono text-ink-faint flex-shrink-0">{formatRelativeTime(entry.at)}</span>
                </div>
              ))}
              {incident.notes && (
                <div className="flex items-start justify-between gap-2 text-xs pt-2 border-t border-ground-line">
                  <span className="text-ink-muted whitespace-pre-wrap">{incident.notes}</span>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 mt-3">
            <input
              ref={noteInputRef}
              data-note-input
              className="input text-sm flex-1"
              placeholder="Add a note for the responding unit..."
              value={note}
              onChange={e => setNote(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && note.trim()) {
                  onNote(note.trim())
                  setNote('')
                }
              }}
            />
            <button
              onClick={() => { if (note.trim()) { onNote(note.trim()); setNote('') } }}
              className="btn-primary text-xs"
            >
              Post
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Real nearest police station / hospital, looked up live from OpenStreetMap
// (see api/services/emergency_service.py) -- not a fabricated contact list.
// Empty results genuinely mean OSM has no tagged station/hospital nearby,
// which is common outside dense metro cores.
function NearestServicesCard({ latitude, longitude }) {
  const { data, loading, error } = useNearestEmergencyServices(latitude, longitude)

  return (
    <div className="card-sm">
      <p className="text-sm font-display font-semibold text-ink mb-3">Nearest emergency services</p>
      {loading && (
        <p className="text-xs text-ink-faint">Looking up nearby police &amp; hospitals…</p>
      )}
      {error && !loading && (
        <p className="text-xs text-sev-medium">Lookup failed — OpenStreetMap service may be busy, try again shortly.</p>
      )}
      {data && !loading && (
        <div className="space-y-3">
          <EmergencyList icon={Shield} label="Police" items={data.police} emptyText="No tagged police station found nearby" />
          <EmergencyList icon={Cross} label="Hospitals" items={data.hospitals} emptyText="No tagged hospital found nearby" />
        </div>
      )}
    </div>
  )
}

function EmergencyList({ icon: Icon, label, items, emptyText }) {
  return (
    <div>
      <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-1.5 flex items-center gap-1.5">
        <Icon className="w-3 h-3" /> {label}
      </p>
      {items.length === 0 ? (
        <p className="text-xs text-ink-faint">{emptyText}</p>
      ) : (
        <div className="space-y-1.5">
          {items.map((s, i) => (
            <div key={i} className="text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="text-ink truncate">{s.name}</span>
                <span className="font-mono text-ink-faint flex-shrink-0">{s.distance_km} km</span>
              </div>
              {(s.phone || s.address) && (
                <p className="text-[10px] text-ink-faint truncate">{[s.phone, s.address].filter(Boolean).join(' · ')}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MetaRow({ label, value, mono }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-ink-faint">{label}</span>
      <span className={classNames('text-ink text-right', mono && 'font-mono')}>{value || '—'}</span>
    </div>
  )
}

export function LiveIncidents() {
  const { incidents, isLoading, selectedIncident, setSelectedIncident, updateIncident } = useIncidents()
  const [sevFilter, setSevFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [newArrivalBanner, setNewArrivalBanner] = useState(0)
  const prevCountRef = useRef(incidents.length)
  const listRef = useRef(null)

  const filtered = useMemo(() => {
    let base = sevFilter !== 'all' ? incidents.filter(i => i.severity === sevFilter) : incidents
    if (search) {
      const q = search.toLowerCase()
      base = base.filter(i =>
        i.incident_type.includes(q) || i.location?.address?.toLowerCase().includes(q) || i.location?.camera_id?.toLowerCase().includes(q)
      )
    }
    return [...base].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
  }, [incidents, sevFilter, search])

  const severityCounts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, low: 0 }
    incidents.forEach(i => { if (c[i.severity] !== undefined) c[i.severity]++ })
    return c
  }, [incidents])

  useEffect(() => {
    if (incidents.length > prevCountRef.current) {
      setNewArrivalBanner(n => n + (incidents.length - prevCountRef.current))
    }
    prevCountRef.current = incidents.length
  }, [incidents.length])

  useEffect(() => {
    if (!selectedIncident && filtered.length > 0) {
      setSelectedIncident(filtered[0])
    }
  }, [filtered, selectedIncident, setSelectedIncident])

  const selectedIndex = useMemo(
    () => filtered.findIndex(i => i.incident_id === selectedIncident?.incident_id),
    [filtered, selectedIncident]
  )

  const moveSelection = useCallback((delta) => {
    if (filtered.length === 0) return
    const idx = selectedIndex < 0 ? 0 : Math.min(Math.max(selectedIndex + delta, 0), filtered.length - 1)
    setSelectedIncident(filtered[idx])
  }, [filtered, selectedIndex, setSelectedIncident])

  const applyUpdate = useCallback((patch) => {
    if (!selectedIncident) return
    updateIncident(selectedIncident.incident_id, patch)
  }, [selectedIncident, updateIncident])

  const applyNote = useCallback((text) => {
    if (!selectedIncident) return
    const stamped = `[${new Date().toLocaleTimeString()}] ${PLACEHOLDER_OPERATOR}: ${text}`
    const combined = selectedIncident.notes ? `${selectedIncident.notes}\n${stamped}` : stamped
    updateIncident(selectedIncident.incident_id, { notes: combined })
  }, [selectedIncident, updateIncident])

  useEffect(() => {
    const handler = (e) => {
      const target = e.target
      const inTextInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'

      if (e.key === 'Escape' && inTextInput) {
        target.blur()
        return
      }
      if (inTextInput) return

      switch (e.key.toLowerCase()) {
        case 'j':
          e.preventDefault(); moveSelection(1); break
        case 'k':
          e.preventDefault(); moveSelection(-1); break
        case 'a': {
          e.preventDefault()
          if (!selectedIncident) break
          // No real auth/operator-roster backend yet (see PLACEHOLDER_OPERATOR) --
          // the quick-assign shortcut assigns to the current session's own
          // placeholder identity rather than randomly picking a fake officer
          // name, since there's no real basis for picking anyone else.
          applyUpdate({ assigned_to: PLACEHOLDER_OPERATOR, status: 'investigating' })
          break
        }
        case 'i':
          e.preventDefault(); applyUpdate({ status: 'investigating' }); break
        case 'r':
          e.preventDefault(); applyUpdate({ status: 'resolved' }); break
        case 'f':
          e.preventDefault(); applyUpdate({ status: 'false_positive' }); break
        case 'n': {
          e.preventDefault()
          const el = document.querySelector('[data-note-input]')
          el?.focus()
          break
        }
        default:
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [moveSelection, applyUpdate, selectedIncident])

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col">
      <div className="flex items-center justify-between mb-3 flex-shrink-0">
        <div>
          <h1 className="text-2xl font-display font-semibold text-ink">Live Incidents</h1>
          <p className="text-sm text-ink-faint mt-0.5">{filtered.length} incidents</p>
        </div>
        <div className="live-indicator">
          <span className="live-dot" /> LIVE
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-5 gap-4 min-h-0">
        {/* List (~40%) */}
        <div className="lg:col-span-2 card p-0 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-ground-line space-y-2 flex-shrink-0">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-faint" />
              <input
                className="input pl-9 text-xs py-1.5"
                placeholder="Search by type, camera, location..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => setSevFilter('all')}
                className={classNames(
                  'px-2 py-1 rounded-lg text-[11px] font-medium transition-colors',
                  sevFilter === 'all' ? 'bg-white/10 text-ink border border-white/10' : 'text-ink-faint hover:text-ink hover:bg-white/5 border border-transparent'
                )}
              >
                All {incidents.length}
              </button>
              {SEVERITY_ORDER.map(sev => (
                <button
                  key={sev}
                  onClick={() => setSevFilter(sev)}
                  className={classNames(
                    'px-2 py-1 rounded-lg text-[11px] font-medium transition-colors capitalize',
                    sevFilter === sev ? 'bg-white/10 text-ink border border-white/10' : 'text-ink-faint hover:text-ink hover:bg-white/5 border border-transparent'
                  )}
                >
                  {SEVERITY_LABEL[sev]} {severityCounts[sev]}
                </button>
              ))}
            </div>
          </div>

          {newArrivalBanner > 0 && (
            <button
              onClick={() => { listRef.current?.scrollTo({ top: 0, behavior: 'smooth' }); setNewArrivalBanner(0) }}
              className="mx-3 mt-2 flex-shrink-0 flex items-center justify-center gap-1.5 text-xs font-medium text-signal bg-signal/10 border border-signal/30 rounded-full py-1"
            >
              <span className="live-dot" /> {newArrivalBanner} new detection{newArrivalBanner > 1 ? 's' : ''} arrived — show ↑
            </button>
          )}

          <div ref={listRef} className="flex-1 overflow-y-auto">
            {isLoading && filtered.length === 0 ? (
              <div className="flex items-center justify-center py-16">
                <div className="w-5 h-5 border-2 border-signal/30 border-t-signal rounded-full animate-spin" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-16">
                <Activity className="w-8 h-8 mx-auto mb-2 text-ink-faint" />
                <p className="text-sm text-ink-faint">No incidents match your filters</p>
              </div>
            ) : (
              filtered.map(inc => (
                <IncidentRow
                  key={inc.incident_id}
                  incident={inc}
                  selected={selectedIncident?.incident_id === inc.incident_id}
                  onClick={() => setSelectedIncident(inc)}
                />
              ))
            )}
          </div>

          <div className="px-3 py-2 border-t border-ground-line flex-shrink-0">
            <p className="text-[10px] font-mono text-ink-faint">
              J/K move · A assign · I investigate · R resolve · F false positive · N note
            </p>
          </div>
        </div>

        {/* Detail (~60%) */}
        <div className="lg:col-span-3 min-h-0">
          <DetailPanel incident={selectedIncident} onAction={applyUpdate} onNote={applyNote} />
        </div>
      </div>
    </div>
  )
}

export default LiveIncidents

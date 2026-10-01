import { useMemo, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { X, MapPin } from 'lucide-react'
import { useIncidents } from '../context/IncidentContext'
import { formatRelativeTime, formatConfidence, classNames } from '../utils/format'
import { TYPE_LABELS, SEVERITY_LABEL, severityChipClass, STATUS_LABEL, statusPillClass } from '../utils/incidentMeta'

// NOTE: there is no real auth/operator identity in the backend yet, so "Mine" is a
// static placeholder operator name that matches the same "Officer N" convention the
// backend's dummy-data generator uses (api/services/incident_service.py).
export const PLACEHOLDER_OPERATOR = 'Officer 1'

const TABS = [
  { key: 'all', label: 'All' },
  { key: 'unassigned', label: 'Unassigned' },
  { key: 'mine', label: 'Mine' },
]

function ageMs(timestamp) {
  return Date.now() - new Date(timestamp).getTime()
}

function OpenForTimer({ timestamp, critical }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const ms = ageMs(timestamp)
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  const aging = critical && mins >= 5
  return (
    <span className={classNames('font-mono text-[11px]', aging ? 'text-sev-critical' : 'text-ink-faint')}>
      {mins}m {secs.toString().padStart(2, '0')}s
    </span>
  )
}

function QueueCard({ incident, onOpen }) {
  const active = incident.status !== 'resolved' && incident.status !== 'false_positive'
  return (
    <button
      onClick={() => onOpen(incident)}
      className={classNames(
        'w-full text-left p-3 rounded-lg border transition-colors',
        incident.severity === 'critical'
          ? 'bg-sev-critical/[0.06] border-sev-critical/40 hover:border-sev-critical/70'
          : 'bg-ground-panel border-ground-line hover:border-ink-faint/40'
      )}
    >
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className={severityChipClass(incident.severity)}>{SEVERITY_LABEL[incident.severity]}</span>
        <span className={statusPillClass(incident.status)}>{STATUS_LABEL[incident.status]}</span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-ink truncate">
          {TYPE_LABELS[incident.incident_type] || incident.incident_type}
        </span>
        <span className="text-[10px] font-mono text-ink-faint flex-shrink-0">
          INC-{incident.incident_id?.slice(0, 4).toUpperCase()}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-1">
        <span className="text-xs text-ink-muted truncate flex items-center gap-1">
          <MapPin className="w-3 h-3 flex-shrink-0" />
          {incident.location?.camera_id} · {incident.location?.address}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-1.5">
        <span className="text-[10px] font-mono text-ink-faint">{formatConfidence(incident.confidence)} conf</span>
        {active ? (
          <OpenForTimer timestamp={incident.timestamp} critical={incident.severity === 'critical'} />
        ) : (
          <span className="text-[10px] font-mono text-ink-faint">{formatRelativeTime(incident.timestamp)}</span>
        )}
      </div>
    </button>
  )
}

export function TriageQueueBody({ onClose }) {
  const { allIncidents: incidents, setSelectedIncident } = useIncidents()
  const navigate = useNavigate()
  const [tab, setTab] = useState('all')

  const open = useMemo(
    () => incidents.filter(i => i.status !== 'resolved' && i.status !== 'false_positive'),
    [incidents]
  )
  const unassignedCount = useMemo(() => open.filter(i => !i.assigned_to).length, [open])
  const mineCount = useMemo(() => open.filter(i => i.assigned_to === PLACEHOLDER_OPERATOR).length, [open])

  const list = useMemo(() => {
    let base = open
    if (tab === 'unassigned') base = open.filter(i => !i.assigned_to)
    if (tab === 'mine') base = open.filter(i => i.assigned_to === PLACEHOLDER_OPERATOR)
    return [...base].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
  }, [open, tab])

  const handleOpen = (incident) => {
    setSelectedIncident(incident)
    navigate('/incidents')
    onClose?.()
  }

  const counts = { all: open.length, unassigned: unassignedCount, mine: mineCount }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-ground-line flex-shrink-0">
        <div>
          <h2 className="text-sm font-display font-semibold text-ink">Triage queue</h2>
          <p className="text-xs text-ink-faint mt-0.5">{open.length} open</p>
        </div>
        {onClose && (
          <button onClick={onClose} className="p-1.5 rounded-lg text-ink-faint hover:text-ink hover:bg-white/5">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="flex items-center gap-1 px-3 pt-3 flex-shrink-0">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={classNames(
              'px-2.5 py-1 rounded-lg text-xs font-medium transition-colors',
              tab === t.key
                ? 'bg-signal/15 text-signal border border-signal/30'
                : 'text-ink-faint hover:text-ink hover:bg-white/5 border border-transparent'
            )}
          >
            {t.label} <span className="font-mono">{counts[t.key]}</span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {list.length === 0 ? (
          <p className="text-center text-xs text-ink-faint py-10">No incidents in this view</p>
        ) : (
          list.map(inc => <QueueCard key={inc.incident_id} incident={inc} onOpen={handleOpen} />)
        )}
      </div>
    </div>
  )
}

// Persistent rail at >=1280px (typical laptop width and up) so it's visible
// on ordinary screens, not just large monitors -- drawer covers anything
// narrower.
export function TriageQueueRail() {
  return (
    <aside className="hidden min-[1280px]:flex flex-col w-[360px] flex-shrink-0 border-l border-ground-line bg-ground-rail">
      <TriageQueueBody />
    </aside>
  )
}

// Slide-over drawer below 1280px
export function TriageQueueDrawer({ open, onClose }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-[360px] max-w-[90vw] h-full bg-ground-rail border-l border-ground-line animate-fade-up">
        <TriageQueueBody onClose={onClose} />
      </div>
    </div>
  )
}

export default TriageQueueRail

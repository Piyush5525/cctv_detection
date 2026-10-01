import { useMemo, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle, X, ArrowRight,
} from 'lucide-react'
import {
  ResponsiveContainer, Line, LineChart,
} from 'recharts'
import { useIncidents } from '../context/IncidentContext'
import { useWebSocket } from '../context/WebSocketContext'
import { formatRelativeTime, formatConfidence, classNames } from '../utils/format'
import {
  TYPE_LABELS, SEVERITY_ORDER, SEVERITY_HEX,
} from '../utils/incidentMeta'
import { LiveVideo } from '../components/LiveVideo'

const MODEL_LANES = [
  { key: 'violence', label: 'Violence' },
  { key: 'fall', label: 'Fall' },
  { key: 'snatch', label: 'Snatch' },
  { key: 'fire', label: 'Fire' },
  { key: 'crash', label: 'Crash' },
]

function useClockIST() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

function KpiShell({ children, className }) {
  return <div className={classNames('card-sm relative overflow-hidden flex flex-col', className)}>{children}</div>
}

function SeverityMixBar({ counts, total }) {
  if (!total) return <div className="h-1.5 rounded-full bg-ground-line" />
  return (
    <div className="h-1.5 rounded-full overflow-hidden flex bg-ground-line">
      {SEVERITY_ORDER.map(sev => {
        const pct = (counts[sev] / total) * 100
        if (!pct) return null
        return <div key={sev} style={{ width: `${pct}%`, background: SEVERITY_HEX[sev] }} />
      })}
    </div>
  )
}

function Sparkline({ data, color }) {
  return (
    <div className="h-8 -mx-1">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Dashboard() {
  const { allIncidents: incidents, analytics, trends, systemHealth, refetch } = useIncidents()
  useWebSocket() // subscribed for live updates via WebSocketProvider side effects
  const navigate = useNavigate()
  const [dismissedToastId, setDismissedToastId] = useState(null)

  useEffect(() => { refetch() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const severityCounts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, low: 0 }
    incidents.forEach(i => { if (c[i.severity] !== undefined) c[i.severity]++ })
    return c
  }, [incidents])

  const openIncidents = useMemo(
    () => incidents.filter(i => i.status !== 'resolved' && i.status !== 'false_positive'),
    [incidents]
  )

  const falsePositiveRate = useMemo(() => {
    if (incidents.length === 0) return 0
    const fp = incidents.filter(i => i.status === 'false_positive').length
    return (fp / incidents.length) * 100
  }, [incidents])

  const detectionsSpark = useMemo(
    () => [...trends].reverse().map(t => ({ v: t.count })),
    [trends]
  )

  const newestCritical = useMemo(() => {
    return [...incidents]
      .filter(i => i.severity === 'critical' && i.status === 'new')
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0]
  }, [incidents])

  const featureIncident = useMemo(() => {
    return [...incidents].sort((a, b) => {
      const order = { critical: 0, high: 1, medium: 2, low: 3 }
      const sevDiff = (order[a.severity] ?? 9) - (order[b.severity] ?? 9)
      if (sevDiff !== 0) return sevDiff
      return new Date(b.timestamp) - new Date(a.timestamp)
    })[0]
  }, [incidents])

  // Detection stream swimlanes: bucket incidents by type over the last 60 minutes
  const swimlanes = useMemo(() => {
    const now = Date.now()
    const windowMs = 60 * 60 * 1000
    return MODEL_LANES.map(({ key, label }) => {
      const events = incidents.filter(i => i.incident_type === key && (now - new Date(i.timestamp).getTime()) <= windowMs)
      const ticks = events.map(e => ({
        id: e.incident_id,
        ageFrac: Math.min(1, (now - new Date(e.timestamp).getTime()) / windowMs),
        confidence: e.confidence,
        severity: e.severity,
      }))
      return { key, label, ticks, count: events.length }
    })
  }, [incidents])

  const citiesCovered = useMemo(() => {
    const cities = new Set()
    incidents.forEach(i => {
      const addr = i.location?.address || ''
      if (!addr.toLowerCase().includes('unspecified')) {
        cities.add(addr.split(',')[0].trim().toLowerCase())
      }
    })
    return cities.size
  }, [incidents])

  const openCount = analytics?.active_incidents ?? openIncidents.length

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-semibold text-ink">Overview</h1>
          <p className="text-sm text-ink-faint mt-0.5">Real-time incident monitoring</p>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <KpiShell>
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Open incidents</p>
          <p className="text-3xl font-display font-semibold text-ink">{openCount}</p>
          <div className="mt-3">
            <SeverityMixBar counts={severityCounts} total={incidents.length} />
          </div>
          <p className="text-[11px] font-mono text-sev-critical mt-1.5">{severityCounts.critical} CRITICAL</p>
        </KpiShell>

        <KpiShell>
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Avg response</p>
          <p className="text-3xl font-display font-semibold text-ink">
            {analytics ? `${Math.floor(analytics.avg_response_time_seconds / 60)}m ${Math.round(analytics.avg_response_time_seconds % 60)}s` : '—'}
          </p>
          <p className="text-[11px] text-ink-faint mt-1.5">vs 7-day avg</p>
          <Sparkline data={detectionsSpark.length ? detectionsSpark : [{ v: 0 }, { v: 0 }]} color="#7FE3D0" />
        </KpiShell>

        <KpiShell>
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Detections / hr</p>
          <p className="text-3xl font-display font-semibold text-ink">
            {trends.length ? trends[0].count : 0}
          </p>
          <p className="text-[11px] text-ink-faint mt-1.5">last hour bucket</p>
          <Sparkline data={detectionsSpark.length ? detectionsSpark : [{ v: 0 }, { v: 0 }]} color="#5B9BFF" />
        </KpiShell>

        <KpiShell className="group">
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">False-positive rate</p>
          <p className="text-3xl font-display font-semibold text-ink">{falsePositiveRate.toFixed(1)}%</p>
          <p className="text-[11px] text-ink-faint mt-1.5">of all detections</p>
          {newestCritical && (
            <button
              onClick={() => navigate('/incidents')}
              className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity text-[10px] font-mono text-signal border border-signal/30 rounded px-1.5 py-0.5"
            >
              Follow critical
            </button>
          )}
        </KpiShell>

        <KpiShell>
          <p className="text-[11px] font-mono uppercase tracking-wider text-ink-faint mb-2">Cities covered</p>
          <p className="text-3xl font-display font-semibold text-ink">{citiesCovered}</p>
          <p className="text-[11px] text-ink-faint mt-1.5">with a specific mapped location</p>
        </KpiShell>
      </div>

      {/* Camera wall */}
      <div className="space-y-3">
        <LiveVideo featureIncident={featureIncident} />
        {newestCritical && dismissedToastId !== newestCritical.incident_id && (
          <div className="incident-card-critical flex items-center justify-between gap-3 px-4 py-3">
            <div className="flex items-center gap-2 min-w-0">
              <AlertTriangle className="w-4 h-4 text-sev-critical flex-shrink-0" />
              <span className="text-sm text-ink truncate">
                New critical: {TYPE_LABELS[newestCritical.incident_type]} at {newestCritical.location?.camera_id}
              </span>
              <span className="text-xs font-mono text-ink-faint flex-shrink-0">
                {formatRelativeTime(newestCritical.timestamp)}
              </span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button onClick={() => navigate('/incidents')} className="btn-primary text-xs py-1 px-3">
                Open incident <ArrowRight className="w-3 h-3" />
              </button>
              <button onClick={() => setDismissedToastId(newestCritical.incident_id)} className="p-1 text-ink-faint hover:text-ink">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Detection stream + Model health */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 card">
          <p className="text-sm font-display font-semibold text-ink mb-4">Detection stream <span className="text-ink-faint font-sans font-normal text-xs">· last 60 min</span></p>
          <div className="space-y-3">
            {swimlanes.map(lane => (
              <div key={lane.key} className="flex items-center gap-3">
                <span className="w-16 text-xs text-ink-muted flex-shrink-0">{lane.label}</span>
                <div className="flex-1 h-7 relative bg-ground rounded border border-ground-line overflow-hidden">
                  {lane.ticks.map(t => (
                    <div
                      key={t.id}
                      title={`${formatConfidence(t.confidence)} confidence`}
                      className="absolute bottom-0 w-[2px] rounded-t-sm"
                      style={{
                        left: `${(1 - t.ageFrac) * 100}%`,
                        height: `${t.confidence == null ? 15 : Math.max(15, t.confidence * 100)}%`,
                        background: SEVERITY_HEX[t.severity] || '#5B9BFF',
                      }}
                    />
                  ))}
                </div>
                <span className="w-6 text-right text-xs font-mono text-ink-faint flex-shrink-0">{lane.count}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <p className="text-sm font-display font-semibold text-ink mb-4">Model health</p>
          <div className="space-y-2.5">
            {Object.entries(systemHealth?.detection_models_loaded || {}).map(([key, info]) => {
              const healthy = info.loaded
              return (
                <div key={key} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={classNames('w-1.5 h-1.5 rounded-full flex-shrink-0', healthy ? 'bg-success' : 'bg-sev-high')} />
                    <span className="text-ink truncate">{info.model || key}</span>
                  </div>
                  <span className="font-mono text-ink-faint flex-shrink-0">
                    {healthy ? 'loaded' : 'not loaded'}
                  </span>
                </div>
              )
            })}
            {!systemHealth && <p className="text-xs text-ink-faint">Loading system health…</p>}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard

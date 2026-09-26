import { useMemo } from 'react'
import {
  AlertTriangle, CheckCircle, Target, TrendingUp,
  Activity, Flame, Car, Shield, MapPin, Video,
  RefreshCw, Clock
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from 'recharts'
import { useIncidents } from '../context/IncidentContext'
import { formatRelativeTime, formatConfidence } from '../utils/format'
import { LiveVideo } from '../components/LiveVideo'
import { MiniMap } from '../components/MiniMap'

const TYPE_META = {
  violence:     { label: 'Violence',       color: '#f87171', Icon: Activity },
  fall:         { label: 'Fall',           color: '#fbbf24', Icon: AlertTriangle },
  women_safety: { label: "Women's Safety", color: '#60a5fa', Icon: Shield },
  snatch:       { label: 'Snatch',         color: '#a78bfa', Icon: Target },
  fire:         { label: 'Fire',           color: '#fb923c', Icon: Flame },
  crash:        { label: 'Crash',          color: '#f97316', Icon: Car },
}

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low']
const SEVERITY_COLORS = { critical: '#f87171', high: '#fb923c', medium: '#60a5fa', low: '#94a3b8' }

export function Dashboard() {
  const { incidents, analytics, trends, heatmap, isLoading, refetch } = useIncidents()

  const recent = useMemo(() => incidents.slice(0, 6), [incidents])

  const chartData = useMemo(() =>
    [...trends].reverse().map(t => ({
      time: t.period,
      total: t.count,
      violence: t.by_type?.violence || 0,
      fire: t.by_type?.fire || 0,
      crash: t.by_type?.crash || 0,
    })),
  [trends])

  const severityCounts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, low: 0 }
    incidents.forEach(i => { if (c[i.severity] !== undefined) c[i.severity]++ })
    return c
  }, [incidents])

  const typeCounts = useMemo(() => {
    const c = {}
    incidents.forEach(i => { c[i.incident_type] = (c[i.incident_type] || 0) + 1 })
    return c
  }, [incidents])

  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Command Dashboard</h1>
          <p className="text-sm text-slate-500 mt-0.5">Real-time incident monitoring</p>
        </div>
        <button
          onClick={refetch}
          disabled={isLoading}
          className="btn-ghost border border-[#1a2540] text-xs"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* ── KPI Row ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          label="Active Incidents"
          value={analytics?.active_incidents ?? 0}
          icon={AlertTriangle}
          color="#f87171"
          sub="Currently open"
        />
        <KpiCard
          label="Critical"
          value={analytics?.critical_incidents ?? 0}
          icon={Target}
          color="#fb923c"
          sub="Needs immediate action"
        />
        <KpiCard
          label="Resolved Today"
          value={analytics?.resolved_today ?? 0}
          icon={CheckCircle}
          color="#34d399"
          sub="Closed incidents"
        />
        <KpiCard
          label="Accuracy"
          value={`${analytics?.detection_accuracy ?? 0}%`}
          icon={TrendingUp}
          color="#60a5fa"
          sub="Detection confidence"
        />
      </div>

      {/* ── Main Grid ── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* Left: Live Feed + Incidents */}
        <div className="xl:col-span-2 space-y-5">
          <LiveVideo />

          {/* Recent Incidents */}
          <div className="card p-0">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#1a2540]">
              <span className="text-sm font-semibold text-slate-200">Recent Incidents</span>
              <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Live
              </span>
            </div>
            <div className="divide-y divide-[#1a2540] max-h-80 overflow-y-auto">
              {recent.length === 0 ? (
                <div className="py-12 text-center">
                  <Activity className="w-8 h-8 mx-auto mb-2 text-slate-700" />
                  <p className="text-sm text-slate-600">No incidents detected</p>
                </div>
              ) : (
                recent.map(inc => <IncidentRow key={inc.incident_id} incident={inc} />)
              )}
            </div>
          </div>

          {/* Type breakdown + Map */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="card">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-4">By Type (24h)</p>
              <div className="space-y-3">
                {Object.entries(TYPE_META).map(([type, { label, color, Icon }]) => {
                  const count = typeCounts[type] || 0
                  const pct = incidents.length > 0 ? (count / incidents.length) * 100 : 0
                  return (
                    <div key={type} className="flex items-center gap-3">
                      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                        style={{ background: `${color}15` }}>
                        <Icon className="w-3.5 h-3.5" style={{ color }} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-slate-400">{label}</span>
                          <span className="text-slate-500 font-mono">{count}</span>
                        </div>
                        <div className="h-1 bg-[#1a2540] rounded-full overflow-hidden">
                          <div className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${pct}%`, background: color }} />
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
            <MiniMap heatmap={heatmap} incidents={incidents.slice(0, 20)} />
          </div>
        </div>

        {/* Right: Charts + Severity */}
        <div className="space-y-5">

          {/* Trend Chart */}
          <div className="card">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-4">Incident Trend (24h)</p>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gTotal" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#34d399" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gViolence" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#f87171" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1a2540" vertical={false} />
                  <XAxis dataKey="time" stroke="#334155" fontSize={10} tickLine={false} axisLine={false} />
                  <YAxis stroke="#334155" fontSize={10} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{ background: '#0d1526', border: '1px solid #1a2540', borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: '#94a3b8' }}
                    itemStyle={{ color: '#e2e8f4' }}
                  />
                  <Area type="monotone" dataKey="total"    stroke="#34d399" strokeWidth={2} fill="url(#gTotal)" />
                  <Area type="monotone" dataKey="violence" stroke="#f87171" strokeWidth={1.5} fill="url(#gViolence)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Severity */}
          <div className="card">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-4">Severity Breakdown</p>
            <div className="space-y-3">
              {SEVERITY_ORDER.map(sev => {
                const count = severityCounts[sev] || 0
                const pct = incidents.length > 0 ? (count / incidents.length) * 100 : 0
                const color = SEVERITY_COLORS[sev]
                return (
                  <div key={sev} className="flex items-center gap-3">
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: `${color}15` }}>
                      <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                    </div>
                    <div className="flex-1">
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-400 capitalize">{sev}</span>
                        <span className="text-slate-500 font-mono">{count}</span>
                      </div>
                      <div className="h-1 bg-[#1a2540] rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${pct}%`, background: color }} />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* System Health */}
          <div className="card">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-4">System Health</p>
            <div className="space-y-2.5">
              {[
                { label: 'Detection Pipeline', value: 'Active',      ok: true },
                { label: 'API Server',          value: 'Running',    ok: true },
                { label: 'Alert Delivery',      value: 'Operational',ok: true },
                { label: 'Evidence Storage',    value: 'Ready',      ok: true },
              ].map(({ label, value, ok }) => (
                <div key={label} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400'}`} />
                    <span className="text-xs text-slate-400">{label}</span>
                  </div>
                  <span className={`text-xs font-medium ${ok ? 'text-emerald-400' : 'text-red-400'}`}>{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function KpiCard({ label, value, icon: Icon, color, sub }) {
  return (
    <div className="card-sm relative overflow-hidden">
      <div className="absolute top-0 right-0 w-16 h-16 rounded-full opacity-5 -translate-y-4 translate-x-4"
        style={{ background: color }} />
      <div className="flex items-start justify-between mb-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: `${color}15` }}>
          <Icon className="w-4 h-4" style={{ color }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-slate-100">{value}</p>
      <p className="text-xs font-medium text-slate-400 mt-0.5">{label}</p>
      <p className="text-[10px] text-slate-600 mt-0.5">{sub}</p>
    </div>
  )
}

const TYPE_COLORS_MAP = {
  violence: '#f87171', fall: '#fbbf24', women_safety: '#60a5fa',
  snatch: '#a78bfa', fire: '#fb923c', crash: '#f97316', other: '#94a3b8',
}
const SEV_COLORS = { critical: '#f87171', high: '#fb923c', medium: '#60a5fa', low: '#94a3b8' }

function IncidentRow({ incident }) {
  const color = TYPE_COLORS_MAP[incident.incident_type] || '#94a3b8'
  const sevColor = SEV_COLORS[incident.severity] || '#94a3b8'
  return (
    <div className="flex items-center gap-3 px-5 py-3 hover:bg-white/[0.02] transition-colors">
      <div className="w-1.5 h-8 rounded-full flex-shrink-0" style={{ background: sevColor }} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-200 capitalize">
            {incident.incident_type.replace('_', ' ')}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded font-medium capitalize"
            style={{ color: sevColor, background: `${sevColor}15` }}>
            {incident.severity}
          </span>
        </div>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-slate-600 flex items-center gap-1">
            <MapPin className="w-3 h-3" />{incident.location?.address || 'Unknown'}
          </span>
          <span className="text-xs text-slate-600 flex items-center gap-1">
            <Clock className="w-3 h-3" />{formatRelativeTime(incident.timestamp)}
          </span>
        </div>
      </div>
      <span className="text-xs font-mono text-slate-600">{formatConfidence(incident.confidence)}</span>
    </div>
  )
}

export default Dashboard

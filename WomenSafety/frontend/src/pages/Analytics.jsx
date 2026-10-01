import { useMemo } from 'react'
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import { useIncidents } from '../context/IncidentContext'
import { classNames } from '../utils/format'
import { formatNumber } from '../utils/format'
import { IncidentTypeLabels, StatusLabels, TYPE_COLORS } from '../utils/types'
import { SEVERITY_HEX, STATUS_LABEL } from '../utils/incidentMeta'

const STATUS_HEX = {
  new: '#ECE9E1', investigating: '#7FE3D0', resolved: '#58C98B', false_positive: '#858B80',
}
import { KPICard } from '../components/KPICard'
import { 
  AlertTriangle, 
  CheckCircle, 
  Target, 
  TrendingUp, 
  Activity,
  MapPin,
  Video,
  Shield,
  Flame,
  Car,
  Clock,
  Users,
  Download,
} from 'lucide-react'

const COLORS = ['#00d4aa', '#ff4757', '#ffa502', '#3742fa', '#00d4aa', '#ff6b35', '#8b99b3']

export function Analytics() {
  const { allIncidents: incidents, analytics, trends, allIncidentsLoading: isLoading } = useIncidents()

  const typeDistribution = useMemo(() => {
    const counts = {}
    incidents.forEach(i => {
      counts[i.incident_type] = (counts[i.incident_type] || 0) + 1
    })
    return Object.entries(counts).map(([type, value]) => ({
      type,
      label: IncidentTypeLabels[type] || type,
      value,
      color: TYPE_COLORS[type] || '#8b99b3',
    }))
  }, [incidents])

  const severityDistribution = useMemo(() => {
    const counts = { critical: 0, high: 0, medium: 0, low: 0 }
    incidents.forEach(i => {
      if (counts.hasOwnProperty(i.severity)) counts[i.severity]++
    })
    return Object.entries(counts).map(([name, value]) => ({
      name: name.charAt(0).toUpperCase() + name.slice(1),
      value,
      color: SEVERITY_HEX[name] || '#8b99b3',
    })).filter(d => d.value > 0)
  }, [incidents])

  const statusDistribution = useMemo(() => {
    const counts = { new: 0, investigating: 0, resolved: 0, false_positive: 0 }
    incidents.forEach(i => {
      if (counts.hasOwnProperty(i.status)) counts[i.status]++
    })
    return Object.entries(counts).map(([status, value]) => ({
      status,
      label: StatusLabels[status] || status,
      value,
      color: STATUS_HEX[status] || '#8b99b3',
    })).filter(d => d.value > 0)
  }, [incidents])

  const hourlyTrends = useMemo(() => trends.map(t => ({
    hour: t.period,
    total: t.count,
    ...t.by_type,
  })).reverse(), [trends])

  const dailyTrends = useMemo(() => {
    const daily = {}
    incidents.forEach(i => {
      const day = new Date(i.timestamp).toISOString().split('T')[0]
      daily[day] = (daily[day] || 0) + 1
    })
    return Object.entries(daily)
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-14)
      .map(([date, count]) => ({ date, count }))
  }, [incidents])

  const cameraStats = useMemo(() => {
    const stats = {}
    incidents.forEach(i => {
      const cam = i.location.camera_id
      if (!stats[cam]) stats[cam] = { total: 0, byType: {}, bySeverity: {} }
      stats[cam].total++
      stats[cam].byType[i.incident_type] = (stats[cam].byType[i.incident_type] || 0) + 1
      stats[cam].bySeverity[i.severity] = (stats[cam].bySeverity[i.severity] || 0) + 1
    })
    return Object.entries(stats)
      .map(([camera, data]) => ({ camera, ...data }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 10)
  }, [incidents])

  const responseTimes = useMemo(() => {
    const resolved = incidents.filter(i => i.resolved_at)
    return resolved.map(i => {
      const detected = new Date(i.timestamp).getTime()
      const resolved = new Date(i.resolved_at).getTime()
      return (resolved - detected) / 1000 / 60 // minutes
    })
  }, [incidents])

  const avgResponseTime = responseTimes.length > 0 
    ? responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length 
    : 0

  if (isLoading && incidents.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-command-accent" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-command-text">Analytics</h1>
          <p className="text-command-text-dim mt-1">Incident trends, distribution & performance metrics</p>
        </div>
        <button className="btn-secondary">
          <Download className="w-4 h-4" />
          Export Report
        </button>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <KPICard
          value={analytics?.total_incidents ?? 0}
          label="Total Incidents"
          icon={Activity}
          iconColor="text-command-info"
          format={formatNumber}
        />
        <KPICard
          value={analytics?.active_incidents ?? 0}
          label="Active"
          icon={AlertTriangle}
          iconColor="text-command-danger"
          format={formatNumber}
        />
        <KPICard
          value={analytics?.critical_incidents ?? 0}
          label="Critical"
          icon={Target}
          iconColor="text-command-warning"
          format={formatNumber}
        />
        <KPICard
          value={analytics?.resolved_today ?? 0}
          label="Resolved Today"
          icon={CheckCircle}
          iconColor="text-command-accent"
          format={formatNumber}
        />
        <KPICard
          value={Math.round(avgResponseTime)}
          label="Avg Response (min)"
          icon={Clock}
          iconColor="text-command-info"
        />
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Incidents by Type - Pie */}
        <div className="card">
          <h3 className="text-sm font-medium text-command-text mb-4">Incidents by Type</h3>
          <div className="h-64 flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={typeDistribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  fill="#8884d8"
                  paddingAngle={2}
                  dataKey="value"
                  nameKey="type"
                  label={({ type, percent }) => `${IncidentTypeLabels[type]} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {typeDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#111827',
                    border: '1px solid #1f2a44',
                    borderRadius: '8px',
                  }}
                  formatter={(value, name) => [value, IncidentTypeLabels[name]]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap gap-2 mt-4 justify-center">
            {typeDistribution.map((entry) => (
              <div key={entry.type} className="flex items-center gap-1.5 text-xs text-command-text-dim">
                <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
                <span>{entry.label} ({entry.value})</span>
              </div>
            ))}
          </div>
        </div>

        {/* Incidents by Severity - Bar */}
        <div className="card">
          <h3 className="text-sm font-medium text-command-text mb-4">Incidents by Severity</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={severityDistribution} layout="vertical" margin={{ top: 10, right: 10, left: 40, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2a44" vertical={false} />
                <XAxis type="number" stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis type="category" dataKey="name" stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} width={60} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#111827',
                    border: '1px solid #1f2a44',
                    borderRadius: '8px',
                  }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {severityDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Hourly Trends - Area */}
        <div className="card lg:col-span-2">
          <h3 className="text-sm font-medium text-command-text mb-4">Hourly Incident Trends (24h)</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={hourlyTrends} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00d4aa" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#00d4aa" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2a44" vertical={false} />
                <XAxis dataKey="hour" stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#111827',
                    border: '1px solid #1f2a44',
                    borderRadius: '8px',
                  }}
                  labelFormatter={(v) => `${v}:00`}
                />
                <Area type="monotone" dataKey="total" stroke="#00d4aa" strokeWidth={2} fillOpacity={1} fill="url(#colorTotal)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Status Distribution - Donut */}
        <div className="card">
          <h3 className="text-sm font-medium text-command-text mb-4">Incident Status</h3>
          <div className="h-64 flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={statusDistribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={2}
                  dataKey="value"
                  nameKey="status"
                  label={({ status, percent }) => `${StatusLabels[status]} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {statusDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#111827',
                    border: '1px solid #1f2a44',
                    borderRadius: '8px',
                  }}
                  formatter={(value, name) => [value, StatusLabels[name]]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Daily Trends - Line */}
        <div className="card">
          <h3 className="text-sm font-medium text-command-text mb-4">Daily Incidents (14 days)</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dailyTrends} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2a44" vertical={false} />
                <XAxis dataKey="date" stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => v.split('-').slice(1).join('/')} />
                <YAxis stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#111827',
                    border: '1px solid #1f2a44',
                    borderRadius: '8px',
                  }}
                />
                <Line type="monotone" dataKey="count" stroke="#00d4aa" strokeWidth={2} dot={false} activeDot={{ r: 6, fill: '#00d4aa' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Camera Performance */}
        <div className="card lg:col-span-2">
          <h3 className="text-sm font-medium text-command-text mb-4">Camera Performance (Top 10)</h3>
          <div className="overflow-x-auto">
            <table className="w-full" role="table">
              <thead>
                <tr className="border-b border-command-border bg-command-panel-hover">
                  <th className="px-4 py-3 text-left text-xs font-medium text-command-text-dim uppercase tracking-wider">Camera</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-command-text-dim uppercase tracking-wider">Total</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-command-text-dim uppercase tracking-wider">Critical</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-command-text-dim uppercase tracking-wider">High</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-command-text-dim uppercase tracking-wider">Medium</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-command-text-dim uppercase tracking-wider">Low</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-command-text-dim uppercase tracking-wider">Types</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-command-border">
                {cameraStats.map((cam, index) => (
                  <tr key={cam.camera} className="hover:bg-command-panel-hover/50">
                    <td className="px-4 py-3 font-mono text-command-text">{cam.camera}</td>
                    <td className="px-4 py-3 text-right font-medium text-command-text">{cam.total}</td>
                    <td className="px-4 py-3 text-right text-command-danger font-mono">{cam.bySeverity.critical || 0}</td>
                    <td className="px-4 py-3 text-right text-command-warning font-mono">{cam.bySeverity.high || 0}</td>
                    <td className="px-4 py-3 text-right text-command-info font-mono">{cam.bySeverity.medium || 0}</td>
                    <td className="px-4 py-3 text-right text-command-text-dim font-mono">{cam.bySeverity.low || 0}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {Object.entries(cam.byType).map(([type, count]) => (
                          <span key={type} className="text-xs px-2 py-0.5 rounded bg-command-panel-hover" style={{ color: TYPE_COLORS[type] }}>
                            {count}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Response Time Distribution */}
        <div className="card">
          <h3 className="text-sm font-medium text-command-text mb-4">Response Time Distribution</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={getResponseTimeBins(responseTimes)} margin={{ top: 10, right: 10, left: 40, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2a44" vertical={false} />
                <XAxis dataKey="range" stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#5a6a8a" fontSize={11} tickLine={false} axisLine={false} width={50} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#111827',
                    border: '1px solid #1f2a44',
                    borderRadius: '8px',
                  }}
                />
                <Bar dataKey="count" fill="#00d4aa" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-command-text-dim mt-2 text-center">
            Average: {avgResponseTime.toFixed(1)} min • Samples: {responseTimes.length}
          </p>
        </div>

        {/* Type vs Severity Heatmap */}
        <div className="card">
          <h3 className="text-sm font-medium text-command-text mb-4">Type × Severity Matrix</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" role="table">
              <thead>
                <tr className="border-b border-command-border">
                  <th className="px-3 py-2 text-left text-xs font-medium text-command-text-dim uppercase tracking-wider">Type</th>
                  {['critical', 'high', 'medium', 'low'].map(sev => (
                    <th key={sev} className="px-3 py-2 text-center text-xs font-medium text-command-text-dim uppercase tracking-wider">
                      {sev.charAt(0).toUpperCase() + sev.slice(1)}
                    </th>
                  ))}
                  <th className="px-3 py-2 text-right text-xs font-medium text-command-text-dim uppercase tracking-wider">Total</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(IncidentTypeLabels).map(([type, label]) => {
                  const typeIncidents = incidents.filter(i => i.incident_type === type)
                  const severityCounts = { critical: 0, high: 0, medium: 0, low: 0 }
                  typeIncidents.forEach(i => {
                    if (severityCounts.hasOwnProperty(i.severity)) severityCounts[i.severity]++
                  })
                  const total = typeIncidents.length
                  return (
                    <tr key={type} className="border-b border-command-border/50 hover:bg-command-panel-hover/50">
                      <td className="px-3 py-2 font-medium text-command-text">{label}</td>
                      {['critical', 'high', 'medium', 'low'].map(sev => (
                        <td key={sev} className="px-3 py-2 text-center font-mono" style={{ color: SEVERITY_HEX[sev] }}>
                          {severityCounts[sev] || '—'}
                        </td>
                      ))}
                      <td className="px-3 py-2 text-right font-medium text-command-text">{total}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

function getResponseTimeBins(times) {
  const bins = [
    { range: '< 5 min', min: 0, max: 5 },
    { range: '5-15 min', min: 5, max: 15 },
    { range: '15-30 min', min: 15, max: 30 },
    { range: '30-60 min', min: 30, max: 60 },
    { range: '1-2 hr', min: 60, max: 120 },
    { range: '> 2 hr', min: 120, max: Infinity },
  ]
  return bins.map(bin => ({
    range: bin.range,
    count: times.filter(t => t >= bin.min && t < bin.max).length,
  }))
}

export default Analytics
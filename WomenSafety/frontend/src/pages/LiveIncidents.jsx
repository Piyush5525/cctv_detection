import { useState, useMemo } from 'react'
import { Activity, Filter, Search } from 'lucide-react'
import { useIncidents } from '../context/IncidentContext'
import { IncidentCard } from '../components/IncidentCard'

const TYPES = ['all', 'violence', 'fall', 'women_safety', 'snatch', 'fire', 'crash']
const SEVERITIES = ['all', 'critical', 'high', 'medium', 'low']

export function LiveIncidents() {
  const { incidents, isLoading } = useIncidents()
  const [typeFilter, setTypeFilter] = useState('all')
  const [sevFilter, setSevFilter] = useState('all')
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => incidents.filter(i => {
    if (typeFilter !== 'all' && i.incident_type !== typeFilter) return false
    if (sevFilter !== 'all' && i.severity !== sevFilter) return false
    if (search && !i.incident_type.includes(search.toLowerCase()) &&
        !i.location?.address?.toLowerCase().includes(search.toLowerCase())) return false
    return true
  }), [incidents, typeFilter, sevFilter, search])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Live Incidents</h1>
          <p className="text-sm text-slate-500 mt-0.5">{filtered.length} incidents</p>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs font-medium text-emerald-400">Live</span>
        </div>
      </div>

      {/* Filters */}
      <div className="card-sm space-y-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600" />
          <input
            className="input pl-9"
            placeholder="Search by type or location..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="flex items-center gap-1 flex-wrap">
            <Filter className="w-3.5 h-3.5 text-slate-600" />
            {TYPES.map(t => (
              <button key={t} onClick={() => setTypeFilter(t)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors capitalize
                  ${typeFilter === t
                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent'
                  }`}>
                {t === 'all' ? 'All Types' : t.replace('_', ' ')}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1 flex-wrap ml-auto">
            {SEVERITIES.map(s => (
              <button key={s} onClick={() => setSevFilter(s)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors capitalize
                  ${sevFilter === s
                    ? 'bg-white/10 text-slate-200 border border-white/10'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent'
                  }`}>
                {s === 'all' ? 'All Severity' : s}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* List */}
      {isLoading && filtered.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-6 h-6 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="card text-center py-16">
          <Activity className="w-10 h-10 mx-auto mb-3 text-slate-700" />
          <p className="text-sm text-slate-500">No incidents match your filters</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((inc, i) => (
            <IncidentCard key={inc.incident_id} incident={inc} compact={i > 0} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}

export default LiveIncidents

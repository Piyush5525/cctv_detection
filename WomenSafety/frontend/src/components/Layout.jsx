import { Outlet, NavLink } from 'react-router-dom'
import { useState, useEffect } from 'react'
import {
  LayoutDashboard, Activity, MapPin, Video,
  BarChart3, Settings, Shield, Search,
} from 'lucide-react'
import { useWebSocket } from '../context/WebSocketContext'
import { PLACEHOLDER_OPERATOR } from './TriageQueue'

// Fix pass item 12: only the working map view is exposed. The other pages
// (Dashboard, Incidents, Analytics, Evidence, Settings) call v1 endpoints that
// no longer exist and are hidden until they are rebuilt on the v2 API.
const NAV = [
  { to: '/map', label: 'Incident Map', icon: MapPin },
]

function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

function TopBar({ isConnected }) {
  const now = useClock()
  const istTime = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })

  return (
    <header className="flex-shrink-0 flex items-center gap-4 h-14 px-5 border-b border-ground-line bg-ground-rail">
      {/* Search */}
      <div className="relative flex-1 max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-faint" />
        <input
          className="input pl-9 py-1.5 text-xs"
          placeholder="Search incidents, cameras..."
        />
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] font-mono text-ink-faint border border-ground-line rounded px-1 py-0.5">
          ⌘K
        </span>
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-3">
        <span className="text-[10px] font-mono font-bold tracking-wider rounded bg-signal text-ground px-2 py-1">DEMO MODE</span>
        {/* Live WS status */}
        <div className={`live-indicator ${!isConnected ? 'opacity-50 border-ink-faint/30 bg-white/5 text-ink-faint' : ''}`}>
          <span className={isConnected ? 'live-dot' : 'w-1.5 h-1.5 rounded-full bg-ink-faint'} />
          {isConnected ? 'LIVE' : 'WS OFFLINE'}
        </div>

        {/* Clock */}
        <div className="text-xs font-mono text-ink-muted hidden md:block">
          {istTime} IST
        </div>

        {/* Operator badge — no real auth/operator identity backend yet, so this
            uses the same PLACEHOLDER_OPERATOR string as TriageQueue/LiveIncidents
            rather than a separate hardcoded name, so there's one source of truth
            until real auth exists. */}
        <div className="flex items-center gap-2 pl-3 border-l border-ground-line">
          <div className="w-7 h-7 rounded-full bg-signal/15 border border-signal/30 flex items-center justify-center">
            <span className="text-[10px] font-display font-semibold text-signal">
              {PLACEHOLDER_OPERATOR.split(' ').map(w => w[0]).join('')}
            </span>
          </div>
          <div className="hidden sm:block leading-tight">
            <p className="text-xs font-medium text-ink">{PLACEHOLDER_OPERATOR}</p>
          </div>
        </div>
      </div>
    </header>
  )
}

export function DashboardLayout() {
  const { isConnected } = useWebSocket()
  const activeCount = 0

  return (
    <div className="flex h-screen overflow-hidden bg-ground">

      {/* ── Icon nav rail (fixed ~64px) ── */}
      <aside className="flex-shrink-0 w-16 flex flex-col items-center border-r border-ground-line bg-ground-rail py-3">
        <div className="w-9 h-9 rounded-lg bg-signal/15 border border-signal/30 flex items-center justify-center mb-4">
          <Shield className="w-5 h-5 text-signal" />
        </div>

        <nav className="flex-1 flex flex-col items-center gap-1.5">
          {NAV.map(({ to, label, icon: Icon, badge }) => (
            <NavLink key={to} to={to} title={label} className="relative">
              {({ isActive }) => (
                <div className={isActive ? 'nav-item-active w-11 h-11' : 'nav-item w-11 h-11'}>
                  <Icon className="w-5 h-5" />
                  {badge && activeCount > 0 && (
                    <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 flex items-center justify-center rounded-full bg-sev-critical text-[9px] font-mono font-bold text-ground">
                      {activeCount > 99 ? '99+' : activeCount}
                    </span>
                  )}
                </div>
              )}
            </NavLink>
          ))}
        </nav>

        <div
          className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-signal animate-pulse-dot' : 'bg-sev-critical'}`}
          title={isConnected ? 'System online' : 'Offline'}
        />
      </aside>

      {/* ── Main column ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopBar isConnected={isConnected} />
        <main className="flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default DashboardLayout

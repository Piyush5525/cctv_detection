import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { useState } from 'react'
import {
  LayoutDashboard, Activity, MapPin, Video,
  BarChart3, Settings, Bell, Menu, X,
  Shield, AlertTriangle, ChevronRight
} from 'lucide-react'
import { useWebSocket } from '../context/WebSocketContext'
import { useIncidents } from '../context/IncidentContext'
import { formatRelativeTime } from '../utils/format'

const NAV = [
  { to: '/dashboard', label: 'Dashboard',       icon: LayoutDashboard },
  { to: '/incidents', label: 'Live Incidents',   icon: Activity,  badge: true },
  { to: '/map',       label: 'Incident Map',     icon: MapPin },
  { to: '/evidence',  label: 'Evidence',         icon: Video },
  { to: '/analytics', label: 'Analytics',        icon: BarChart3 },
  { to: '/settings',  label: 'Settings',         icon: Settings },
]

export function DashboardLayout() {
  const [open, setOpen] = useState(true)
  const [notifOpen, setNotifOpen] = useState(false)
  const { isConnected, lastMessage } = useWebSocket()
  const { analytics } = useIncidents()
  const activeCount = analytics?.active_incidents || 0

  return (
    <div className="flex h-screen overflow-hidden bg-[#080d18]">

      {/* ── Sidebar ── */}
      <aside
        className={`
          flex-shrink-0 flex flex-col border-r border-[#1a2540] bg-[#0a1020]
          transition-all duration-200
          ${open ? 'w-56' : 'w-16'}
        `}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 h-14 px-4 border-b border-[#1a2540]">
          <div className="w-7 h-7 rounded-lg bg-emerald-500/20 flex items-center justify-center flex-shrink-0">
            <Shield className="w-4 h-4 text-emerald-400" />
          </div>
          {open && (
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-100 truncate">SafeWatch</p>
              <p className="text-[10px] text-slate-600 truncate">Command Center</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, label, icon: Icon, badge }) => (
            <NavLink key={to} to={to}>
              {({ isActive }) => (
                <div className={`
                  flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm font-medium
                  transition-all duration-150 cursor-pointer
                  ${isActive
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'text-slate-500 hover:text-slate-200 hover:bg-white/5 border border-transparent'
                  }
                `}>
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  {open && (
                    <>
                      <span className="flex-1 truncate">{label}</span>
                      {badge && activeCount > 0 && (
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400">
                          {activeCount}
                        </span>
                      )}
                    </>
                  )}
                </div>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Status */}
        <div className="p-3 border-t border-[#1a2540]">
          <div className={`flex items-center gap-2.5 px-2 py-2 rounded-lg ${isConnected ? 'bg-emerald-500/5' : 'bg-red-500/5'}`}>
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            {open && (
              <span className={`text-xs font-medium ${isConnected ? 'text-emerald-400' : 'text-red-400'}`}>
                {isConnected ? 'System Online' : 'Offline'}
              </span>
            )}
          </div>
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* Topbar */}
        <header className="flex-shrink-0 flex items-center justify-between h-14 px-5 border-b border-[#1a2540] bg-[#0a1020]">
          <button
            onClick={() => setOpen(v => !v)}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors"
          >
            {open ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
          </button>

          <div className="flex items-center gap-3">
            {/* Live indicator */}
            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border
              ${isConnected
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : 'bg-red-500/10 text-red-400 border-red-500/20'
              }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
              {isConnected ? 'Live' : 'Offline'}
            </div>

            {/* Notifications */}
            <div className="relative">
              <button
                onClick={() => setNotifOpen(v => !v)}
                className="relative p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors"
              >
                <Bell className="w-4 h-4" />
                {lastMessage && (
                  <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-red-500 rounded-full" />
                )}
              </button>

              {notifOpen && (
                <div className="absolute right-0 top-full mt-2 w-72 bg-[#0d1526] border border-[#1a2540] rounded-xl shadow-2xl z-50 animate-fade-up">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-[#1a2540]">
                    <span className="text-sm font-semibold text-slate-200">Notifications</span>
                    <button onClick={() => setNotifOpen(false)} className="text-slate-600 hover:text-slate-400">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="p-2 max-h-64 overflow-y-auto">
                    {lastMessage ? (
                      <div className="px-3 py-2.5 rounded-lg hover:bg-white/5">
                        <div className="flex items-center gap-2 mb-1">
                          <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                          <span className="text-sm font-medium text-slate-200 capitalize">
                            {lastMessage.data?.incident_type} Detected
                          </span>
                        </div>
                        <p className="text-xs text-slate-500">{formatRelativeTime(lastMessage.data?.timestamp)}</p>
                      </div>
                    ) : (
                      <p className="text-center text-xs text-slate-600 py-6">No new notifications</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Page */}
        <main className="flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

import { useState } from 'react'
import {
  ChevronDown, ChevronRight, MapPin, Clock,
  Play, Download, MoreVertical, CheckCircle,
  Video, X
} from 'lucide-react'
import { formatRelativeTime, formatConfidence } from '../utils/format'
import { useIncidents } from '../context/IncidentContext'
import { TYPE_LABELS, SEVERITY_LABEL, SEVERITY_HEX, severityChipClass, STATUS_LABEL, statusPillClass } from '../utils/incidentMeta'

export function IncidentCard({ incident, compact = false }) {
  const { updateIncident } = useIncidents()
  const [expanded, setExpanded] = useState(!compact)
  const [menuOpen, setMenuOpen] = useState(false)
  const [videoOpen, setVideoOpen] = useState(false)

  const color = SEVERITY_HEX[incident.severity] || '#5B9BFF'
  const hasClip = !!incident.evidence_clip?.video_path
  const clipFile = hasClip ? incident.evidence_clip.video_path.split(/[\\/]/).pop() : null

  const setStatus = (s) => { updateIncident(incident.incident_id, { status: s }); setMenuOpen(false) }

  return (
    <div className="bg-[#0d1526] border border-[#1a2540] rounded-xl overflow-hidden animate-fade-up">
      {/* Severity bar */}
      <div className="h-0.5 w-full" style={{ background: color }} />

      <div className="p-4">
        {/* Header row */}
        <div className="flex items-start gap-3">
          {/* Type dot */}
          <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
            style={{ background: `${color}15` }}>
            <span className="text-sm font-bold" style={{ color }}>
              {TYPE_LABELS[incident.incident_type]?.[0] || '?'}
            </span>
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-ink">
                {TYPE_LABELS[incident.incident_type] || incident.incident_type}
              </span>
              <span className={severityChipClass(incident.severity)}>
                {SEVERITY_LABEL[incident.severity]}
              </span>
              <span className={statusPillClass(incident.status)}>
                {STATUS_LABEL[incident.status]}
              </span>
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs text-slate-600">
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />{formatRelativeTime(incident.timestamp)}
              </span>
              <span className="flex items-center gap-1">
                <MapPin className="w-3 h-3" />{incident.location?.address || 'Unknown'}
              </span>
              <span className="font-mono">{formatConfidence(incident.confidence)}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1 flex-shrink-0">
            {hasClip && (
              <button
                onClick={() => setVideoOpen(true)}
                className="p-1.5 rounded-lg text-emerald-400 hover:bg-emerald-500/10 transition-colors"
                title="Play evidence clip"
              >
                <Play className="w-3.5 h-3.5" />
              </button>
            )}
            <div className="relative">
              <button
                onClick={() => setMenuOpen(v => !v)}
                className="p-1.5 rounded-lg text-slate-600 hover:text-slate-400 hover:bg-white/5 transition-colors"
              >
                <MoreVertical className="w-3.5 h-3.5" />
              </button>
              {menuOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                  <div className="absolute right-0 top-full mt-1 w-44 bg-[#0d1526] border border-[#1a2540] rounded-xl shadow-2xl z-20 py-1 animate-fade-up">
                    {['investigating', 'resolved', 'false_positive'].map(s => (
                      <button key={s} onClick={() => setStatus(s)}
                        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-400 hover:text-slate-200 hover:bg-white/5 capitalize">
                        <CheckCircle className="w-3.5 h-3.5" />
                        Mark {s.replace('_', ' ')}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
            <button
              onClick={() => setExpanded(v => !v)}
              className="p-1.5 rounded-lg text-slate-600 hover:text-slate-400 hover:bg-white/5 transition-colors"
            >
              {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* Expanded */}
        {expanded && (
          <div className="mt-4 pt-4 border-t border-[#1a2540] space-y-3 animate-fade-up">
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: 'Incident ID', value: incident.incident_id?.slice(0, 12), mono: true },
                { label: 'Camera',      value: incident.location?.camera_id },
                { label: 'Coordinates',
                  value: `${incident.location?.latitude?.toFixed(4)}, ${incident.location?.longitude?.toFixed(4)}`,
                  mono: true },
                { label: 'Confidence',  value: formatConfidence(incident.confidence), mono: true },
              ].map(({ label, value, mono }) => (
                <div key={label} className="bg-[#080d18] rounded-lg p-2.5 border border-[#1a2540]">
                  <p className="text-[10px] text-slate-600 mb-0.5">{label}</p>
                  <p className={`text-xs text-slate-300 ${mono ? 'font-mono' : 'font-medium'}`}>{value || '—'}</p>
                </div>
              ))}
            </div>

            {/* Thumbnail */}
            {incident.thumbnail_path && (
              <div className="rounded-lg overflow-hidden border border-[#1a2540]">
                <img
                  src={`/api/v1/evidence/thumbnail/${incident.thumbnail_path.split(/[\\/]/).pop()}`}
                  alt="Incident thumbnail"
                  className="w-full object-cover max-h-40"
                />
              </div>
            )}

            {/* Evidence clip inline */}
            {hasClip && (
              <div className="bg-[#080d18] rounded-lg border border-[#1a2540] overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-[#1a2540]">
                  <div className="flex items-center gap-2">
                    <Video className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-xs font-medium text-slate-300">Evidence Clip</span>
                    <span className="text-[10px] text-slate-600">
                      ±5s around incident
                    </span>
                  </div>
                  <a
                    href={`/api/v1/evidence/${clipFile}`}
                    download
                    className="p-1 rounded text-slate-600 hover:text-slateald-400"
                  >
                    <Download className="w-3.5 h-3.5" />
                  </a>
                </div>
                <video
                  src={`/api/v1/evidence/${clipFile}`}
                  controls
                  className="w-full bg-black"
                  style={{ maxHeight: 200 }}
                  preload="metadata"
                />
              </div>
            )}

            {!hasClip && (
              <p className="text-xs text-slate-600 text-center py-2">
                No evidence clip available for this incident
              </p>
            )}
          </div>
        )}
      </div>

      {/* Fullscreen video modal */}
      {videoOpen && hasClip && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setVideoOpen(false)}>
          <div className="relative w-full max-w-3xl mx-4" onClick={e => e.stopPropagation()}>
            <div className="bg-[#0d1526] border border-[#1a2540] rounded-2xl overflow-hidden shadow-2xl">
              <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#1a2540]">
                <div>
                  <p className="text-sm font-semibold text-slate-200">
                    Evidence — {TYPE_LABELS[incident.incident_type]}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {new Date(incident.timestamp).toLocaleString()} · ±5s clip
                  </p>
                </div>
                <button onClick={() => setVideoOpen(false)}
                  className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <video
                src={`/api/v1/evidence/${clipFile}`}
                controls
                autoPlay
                className="w-full bg-black"
                style={{ maxHeight: '60vh' }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default IncidentCard

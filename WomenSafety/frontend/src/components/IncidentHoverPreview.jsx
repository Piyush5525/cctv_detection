import { Camera } from 'lucide-react'
import { TYPE_LABELS, SEVERITY_LABEL, STATUS_LABEL, severityChipClass, statusPillClass } from '../utils/incidentMeta'
import { formatConfidence } from '../utils/format'

// Small popover shown on marker hover: photo, or a playing video if the
// incident has an evidence clip, plus the key facts an operator needs
// without opening the full incident.
export function IncidentHoverPreview({ incident }) {
  const hasClip = !!incident.evidence_clip?.video_path
  const clipFile = hasClip ? incident.evidence_clip.video_path.split(/[\\/]/).pop() : null
  const hasThumb = !!incident.thumbnail_path
  const thumbFile = hasThumb ? incident.thumbnail_path.split(/[\\/]/).pop() : null

  return (
    <div className="w-64 font-sans pointer-events-none select-none">
      <div className="w-full h-32 rounded-t-lg bg-ground-line overflow-hidden flex items-center justify-center">
        {hasClip ? (
          <video
            src={`/api/v1/evidence/${clipFile}`}
            className="w-full h-full object-cover"
            autoPlay
            muted
            loop
            playsInline
          />
        ) : hasThumb ? (
          <img
            src={`/api/v1/evidence/thumbnail/${thumbFile}`}
            alt="Incident evidence"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="flex flex-col items-center gap-1 text-ink-faint">
            <Camera className="w-6 h-6" />
            <span className="text-[10px]">No evidence media yet</span>
          </div>
        )}
      </div>
      <div className="bg-ground-panel border border-t-0 border-ground-line rounded-b-lg p-2.5">
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className={severityChipClass(incident.severity)}>{SEVERITY_LABEL[incident.severity]}</span>
          <span className={statusPillClass(incident.status)}>{STATUS_LABEL[incident.status]}</span>
        </div>
        <p className="text-sm font-semibold text-ink leading-tight">{TYPE_LABELS[incident.incident_type]}</p>
        <p className="text-xs text-ink-faint mt-0.5">{incident.location?.camera_id} · {incident.location?.address}</p>
        <p className="text-[11px] font-mono text-ink-faint mt-1">
          {formatConfidence(incident.confidence)} · {new Date(incident.timestamp).toLocaleTimeString()}
        </p>
      </div>
    </div>
  )
}

export default IncidentHoverPreview

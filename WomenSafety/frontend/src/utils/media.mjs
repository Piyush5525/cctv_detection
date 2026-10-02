// One place that turns an incident into evidence URLs (photo, annotated frame, thumbnail, clip).
// URLs are always API_BASE + the incident's own relative evidence path (camera/date/incident/file), so showcase
// incidents (re-assigned cameras), stored-sample triggers and live incidents all resolve the same way.
export const API_BASE = '/api/v1'

export const EVIDENCE_FILES = {
  thumbnail: { file: 'thumbnail.jpg', field: 'thumbnail_path' },
  best: { file: 'best_frame.jpg', field: 'best_frame_path' },
  annotated: { file: 'annotated_frame.jpg', field: 'annotated_frame_path' },
  clip: { file: 'clip.mp4', field: 'clip_path' },
}

const REL_PATH = /^(?:evidence\/)?([^/\\]+)\/(\d{4}-\d{2}-\d{2})\/([^/\\]+)\/[^/\\]+$/

/** "camera/date/incident" folder for an incident: the stored relative path when it agrees with the incident, else built from its fields. */
export function evidenceDir(incident) {
  const ev = incident?.evidence || {}
  for (const { field } of Object.values(EVIDENCE_FILES)) {
    const m = typeof ev[field] === 'string' ? ev[field].replace(/\\/g, '/').match(REL_PATH) : null
    if (m && m[3] === incident.incident_id) return `${m[1]}/${m[2]}/${m[3]}`
  }
  const date = String(incident?.event_start || '').slice(0, 10)
  return `${incident?.camera_id}/${date}/${incident?.incident_id}`
}

/** kind: 'thumbnail' | 'best' | 'annotated' | 'clip'. nonce is only set by the Retry button (cache-busting). */
export function evidenceUrl(incident, kind, nonce) {
  const spec = EVIDENCE_FILES[kind]
  if (!spec) throw new Error(`unknown evidence kind: ${kind}`)
  return `${API_BASE}/evidence/v2/${evidenceDir(incident)}/${spec.file}${nonce ? `?r=${nonce}` : ''}`
}

export const hasAnnotated = (incident) => Boolean(incident?.evidence?.annotated_frame_path)

/** Human reason for a failed media request (from the HTTP status, or null status = network error). */
export function describeFailure(status, detail) {
  if (status == null) return 'Could not reach the API (network error)'
  if (status === 404) return 'Evidence file not found on the server (404)'
  if (status === 403) return 'Evidence request refused (403)'
  if (status === 416) return 'Evidence range not satisfiable (416)'
  if (status >= 500) return `Server error while reading the file (${status})`
  if (status >= 200 && status < 300) return detail || 'The file was found but the browser could not decode it'
  return `Unexpected response (${status})`
}

// The hover slideshow pauses while the detail video plays (shared flag; no framework state needed).
let videoPlaying = false
export const setVideoPlaying = (value) => { videoPlaying = Boolean(value) }
export const isVideoPlaying = () => videoPlaying

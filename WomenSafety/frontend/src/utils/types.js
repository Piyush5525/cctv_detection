export const IncidentType = {
  VIOLENCE: 'violence',
  FALL: 'fall',
  WOMEN_SAFETY: 'women_safety',
  SNATCH: 'snatch',
  FIRE: 'fire',
  CRASH: 'crash',
  OTHER: 'other',
}

export const SeverityLevel = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  CRITICAL: 'critical',
}

export const IncidentStatus = {
  NEW: 'new',
  INVESTIGATING: 'investigating',
  RESOLVED: 'resolved',
  FALSE_POSITIVE: 'false_positive',
}

export const IncidentTypeLabels = {
  [IncidentType.VIOLENCE]: 'Violence',
  [IncidentType.FALL]: 'Fall',
  [IncidentType.WOMEN_SAFETY]: "Women's Safety",
  [IncidentType.SNATCH]: 'Snatch',
  [IncidentType.FIRE]: 'Fire',
  [IncidentType.CRASH]: 'Crash',
  [IncidentType.OTHER]: 'Other',
}

export const IncidentTypeIcons = {
  [IncidentType.VIOLENCE]: 'activity',
  [IncidentType.FALL]: 'alert-triangle',
  [IncidentType.WOMEN_SAFETY]: 'shield-alert',
  [IncidentType.SNATCH]: 'hand',
  [IncidentType.FIRE]: 'flame',
  [IncidentType.CRASH]: 'car',
  [IncidentType.OTHER]: 'alert-circle',
}

// Point at the new Reticle chip/pill classes (see src/index.css + src/utils/incidentMeta.js)
export const SeverityColors = {
  [SeverityLevel.LOW]: 'chip-sev-low',
  [SeverityLevel.MEDIUM]: 'chip-sev-medium',
  [SeverityLevel.HIGH]: 'chip-sev-high',
  [SeverityLevel.CRITICAL]: 'chip-sev-critical',
}

export const StatusColors = {
  [IncidentStatus.NEW]: 'pill-status-new',
  [IncidentStatus.INVESTIGATING]: 'pill-status-investigating',
  [IncidentStatus.RESOLVED]: 'pill-status-resolved',
  [IncidentStatus.FALSE_POSITIVE]: 'pill-status-false_positive',
}

// Severity-driven hex (red/orange/yellow/blue reserved for severity only per design system)
export const SEVERITY_HEX = {
  [SeverityLevel.CRITICAL]: '#FF4B3E',
  [SeverityLevel.HIGH]: '#FF8A1F',
  [SeverityLevel.MEDIUM]: '#F5C542',
  [SeverityLevel.LOW]: '#5B9BFF',
}

export const StatusLabels = {
  [IncidentStatus.NEW]: 'New',
  [IncidentStatus.INVESTIGATING]: 'Investigating',
  [IncidentStatus.RESOLVED]: 'Resolved',
  [IncidentStatus.FALSE_POSITIVE]: 'False Positive',
}

export const TYPE_COLORS = {
  violence: '#ff4757',
  fall: '#ffa502',
  women_safety: '#3742fa',
  snatch: '#00d4aa',
  fire: '#ff4757',
  crash: '#ff6b35',
  other: '#8b99b3',
}
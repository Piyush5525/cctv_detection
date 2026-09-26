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

export const SeverityColors = {
  [SeverityLevel.LOW]: 'text-command-text-dim bg-command-text-dim/20',
  [SeverityLevel.MEDIUM]: 'text-command-info bg-command-info/20',
  [SeverityLevel.HIGH]: 'text-command-warning bg-command-warning/20',
  [SeverityLevel.CRITICAL]: 'text-command-danger bg-command-danger/20',
}

export const StatusColors = {
  [IncidentStatus.NEW]: 'text-command-info bg-command-info/20',
  [IncidentStatus.INVESTIGATING]: 'text-command-warning bg-command-warning/20',
  [IncidentStatus.RESOLVED]: 'text-command-accent bg-command-accent/20',
  [IncidentStatus.FALSE_POSITIVE]: 'text-command-text-dim bg-command-text-dim/20',
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
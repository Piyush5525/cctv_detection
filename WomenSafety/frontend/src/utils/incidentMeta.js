// Shared incident metadata helpers for the "Reticle" design system.
// Severity colors are reserved for incidents ONLY — always paired with a text label.

export const TYPE_LABELS = {
  violence: 'Violence',
  fall: 'Fall',
  women_safety: "Women's Safety",
  snatch: 'Snatch',
  fire: 'Fire',
  crash: 'Crash',
  other: 'Other',
}

export const TYPE_SHORT = {
  violence: 'VIOLENCE',
  fall: 'FALL',
  women_safety: 'WOMEN SAFETY',
  snatch: 'SNATCH',
  fire: 'FIRE',
  crash: 'CRASH',
  other: 'OTHER',
}

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low']

export const SEVERITY_LABEL = {
  critical: 'CRITICAL',
  high: 'HIGH',
  medium: 'MEDIUM',
  low: 'LOW',
}

export const SEVERITY_HEX = {
  critical: '#FF4B3E',
  high: '#FF8A1F',
  medium: '#F5C542',
  low: '#5B9BFF',
}

export function severityChipClass(severity) {
  return `chip-sev-${severity || 'low'}`
}

export const STATUS_LABEL = {
  new: 'NEW',
  investigating: 'INVESTIGATING',
  resolved: 'RESOLVED',
  false_positive: 'FALSE POSITIVE',
}

export function statusPillClass(status) {
  return `pill-status-${status || 'new'}`
}

export function typeTextClass(type) {
  return `type-${type || 'other'}`
}

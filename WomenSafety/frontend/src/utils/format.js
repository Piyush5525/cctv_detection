import { format, formatDistanceToNow, isToday, isYesterday } from 'date-fns'

export function formatTimestamp(dateString) {
  const date = new Date(dateString)
  if (isToday(date)) {
    return `Today at ${format(date, 'HH:mm:ss')}`
  }
  if (isYesterday(date)) {
    return `Yesterday at ${format(date, 'HH:mm:ss')}`
  }
  return format(date, 'MMM d, yyyy HH:mm:ss')
}

export function formatRelativeTime(dateString) {
  const date = new Date(dateString)
  return formatDistanceToNow(date, { addSuffix: true })
}

export function formatConfidence(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'Not scored'
  return `${Math.round(value * 100)}%`
}

export function formatDuration(seconds) {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ${Math.round(seconds % 60)}s`
  return `${Math.round(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`
}

export function formatNumber(num) {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return num.toString()
}

export function formatPercentage(value, decimals = 1) {
  return `${(value * 100).toFixed(decimals)}%`
}

export function getInitials(name) {
  return name
    .split(' ')
    .map(n => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

export function truncate(str, length = 50) {
  if (str.length <= length) return str
  return str.slice(0, length) + '...'
}

export function generateId() {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

export function debounce(fn, delay) {
  let timeoutId
  return (...args) => {
    clearTimeout(timeoutId)
    timeoutId = setTimeout(() => fn(...args), delay)
  }
}

export function classNames(...classes) {
  return classes.filter(Boolean).join(' ')
}
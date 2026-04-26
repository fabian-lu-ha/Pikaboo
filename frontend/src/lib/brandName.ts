// Brand-name and time formatting helpers used across the dashboard.

export function primaryName(s: string): string {
  return s.split(' · ')[0].split(' — ')[0].split(' | ')[0].trim()
}

export function firstWord(s: string): string {
  return primaryName(s).split(/\s+/)[0] || s
}

// Compact relative time formatter — "just now" / "Nm ago" / "Nh ago" / "Nd ago".
// `ts` is a Unix milliseconds timestamp.
export function relativeTime(ts: number, now: number = Date.now()): string {
  const delta = Math.max(0, now - ts)
  const seconds = Math.floor(delta / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

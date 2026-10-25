const UNITS: [number, string][] = [
  [86400, "d"],
  [3600, "h"],
  [60, "min"],
]

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never"
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return iso
  const seconds = Math.round((now - then) / 1000)
  for (const [size, unit] of UNITS)
    if (seconds >= size) return `${Math.floor(seconds / size)} ${unit} ago`
  return "just now"
}

export function until(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return ""
  const seconds = Math.round((Date.parse(iso) - now) / 1000)
  if (Number.isNaN(seconds)) return ""
  if (seconds <= 0) return "now"
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `in ${days} d ${hours} h`
  if (hours) return `in ${hours} h ${minutes} min`
  return `in ${Math.max(minutes, 1)} min`
}

/** A clock time, with the weekday when it is not today. */
export function clock(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return ""
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return ""
  const time = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  return when.toDateString() === now.toDateString()
    ? time
    : `${when.toLocaleDateString([], { weekday: "short" })} ${time}`
}

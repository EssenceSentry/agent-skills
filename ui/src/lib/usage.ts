import { until } from "@/lib/time"

const DAY = 86_400_000

function percent(value: number): string {
  return value >= 10 ? `${Math.round(value)}%` : `${Number(value.toFixed(1))}%`
}

/**
 * What a usage window leaves you: per day until a weekly window resets, or what is left
 * when it resets within a day. A session window lasts hours, so it shows its reset.
 */
export function usageFoot(
  row: { window: string; used: number | null; resets_at: string | null },
  now = Date.now()
): string {
  if (row.used === null || !row.resets_at) return ""
  const resets = `resets ${until(row.resets_at, now)}`
  const left = Math.max(0, 100 - row.used)
  if (left === 0) return `none left, ${resets}`
  if (row.window === "session") return resets
  const days = (Date.parse(row.resets_at) - now) / DAY
  if (days < 1) return `${percent(left)} left, ${resets}`
  const span = Number(days.toFixed(1))
  return `${percent(left / days)} a day for ${span} ${span === 1 ? "day" : "days"}`
}

/** An even pace spends a seventh of a weekly window a day. */
export const EVEN_PER_DAY = 100 / 7
/** More than this many even days' worth a day is allowance that may reset unused. */
export const SPARE_FACTOR = 1.5

/**
 * How what is left per day compares with an even pace: "tight" below it, "spare" well
 * above it (use it before it resets), "even" between. Session windows have no pace.
 */
export function usagePace(
  row: { window: string; used: number | null; resets_at: string | null },
  now = Date.now()
): "tight" | "even" | "spare" | null {
  if (row.used === null || !row.resets_at || row.window === "session") return null
  const days = (Date.parse(row.resets_at) - now) / DAY
  if (!(days > 0)) return null
  const perDay = Math.max(0, 100 - row.used) / days
  if (perDay < EVEN_PER_DAY) return "tight"
  return perDay > EVEN_PER_DAY * SPARE_FACTOR ? "spare" : "even"
}

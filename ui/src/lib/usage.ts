// Relative, so the VS Code extension can bundle this file as it is.
import { until } from "./time"

const DAY = 86_400_000

/** What a window shows when its reading can't be trusted, by its status. */
export const UNREAD: Record<string, string> = {
  unavailable: "not reported",
  stale: "stale reading",
  ambiguous: "unclear reading",
  reset_passed: "reset since last read",
}

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

/** Only these windows turn yellow for allowance left unused; the others only when tight. */
const SPARE_WARNS = new Set(["weekly"])

/** The colour a window's bar takes: red nearly spent, yellow off pace or near the limit. */
export function usageTone(
  row: { window: string; used: number | null; resets_at: string | null },
  now = Date.now()
): "primary" | "warning" | "critical" {
  const used = row.used ?? 0
  if (used >= 95) return "critical"
  const pace = usagePace(row, now)
  if (pace === "tight" || (pace === "spare" && SPARE_WARNS.has(row.window))) return "warning"
  return pace === null && used >= 80 ? "warning" : "primary"
}

const TOOL: Record<string, string> = { claude: "Claude", codex: "Codex" }
const WINDOW: Record<string, string> = {
  session: "session",
  weekly: "weekly",
  weekly_fable: "Fable weekly",
}
const URGENCY = { primary: 0, warning: 1, critical: 2 } as const

/** A window's name for people: "Claude session", "Codex weekly". */
export function windowName(row: { provider: string; window: string }): string {
  return `${TOOL[row.provider] ?? row.provider} ${WINDOW[row.window] ?? row.window}`
}

/** A tool's name for people. */
export const toolName = (provider: string): string => TOOL[provider] ?? provider

/**
 * The bar's whole reading of usage: the most used window, and the most urgent colour any
 * window takes, so the details can wait behind it.
 */
export function usageSummary(
  rows: { provider: string; window: string; used: number | null; resets_at: string | null }[],
  now = Date.now()
): { used: number | null; label: string; tone: "primary" | "warning" | "critical" } {
  const known = rows.filter((r) => r.used !== null)
  const top = known.reduce<(typeof known)[number] | null>(
    (best, r) => (best === null || (r.used ?? 0) > (best.used ?? 0) ? r : best),
    null
  )
  const tone = known
    .map((r) => usageTone(r, now))
    .reduce<"primary" | "warning" | "critical">(
      (worst, t) => (URGENCY[t] > URGENCY[worst] ? t : worst),
      "primary"
    )
  if (!top || top.used === null) return { used: null, label: "Usage not reported", tone }
  return { used: top.used, label: `${windowName(top)} ${Math.round(top.used)}% used`, tone }
}

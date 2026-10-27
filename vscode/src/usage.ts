// The app's own reading of usage, bundled from its source so both say the same thing.
import { toolName, UNREAD, usageFoot, usageSummary, windowName } from "../../ui/src/lib/usage"

export type UsageRow = {
  provider: string
  window: string
  used: number | null
  status: string
  resets_at: string | null
}

export type Credits = { provider: string; balance: number | null; unlimited: boolean }

const BACKGROUND = {
  critical: "statusBarItem.errorBackground",
  warning: "statusBarItem.warningBackground",
  primary: undefined,
} as const

/**
 * The status bar's reading: the most used window's figure, coloured by the most urgent
 * window, and every window and Codex's credits on hover, as the app's gauge shows them.
 */
export function usageStatus(rows: UsageRow[], credits: Credits[], now = Date.now()) {
  const summary = usageSummary(rows, now)
  const windows = rows.map((row) => {
    const reading =
      row.used === null
        ? (UNREAD[row.status] ?? row.status)
        : [
            `${Math.round(row.used)}% used`,
            usageFoot(row, now),
            row.status !== "fresh" && (UNREAD[row.status] ?? row.status),
          ]
            .filter(Boolean)
            .join(" · ")
    return `${windowName(row)}: ${reading}`
  })
  const balances = credits.map((c) => {
    const left = c.unlimited
      ? "unlimited"
      : c.balance === null
        ? "not reported"
        : Math.round(c.balance).toLocaleString("en-US")
    return `${toolName(c.provider)} credits: ${left}`
  })
  return {
    text: `$(dashboard) ${summary.used === null ? "–" : `${Math.round(summary.used)}%`}`,
    background: BACKGROUND[summary.tone],
    tooltip: [`**${summary.label}**`, "", ...windows, ...balances],
  }
}

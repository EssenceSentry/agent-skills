// The app's own reading of usage and times, bundled from its source so both say the same.
import { resetStamp } from "../../ui/src/lib/time"
import { toolName, windowLabel } from "../../ui/src/lib/usage"

export type UsageRow = {
  provider: string
  window: string
  used: number | null
  status: string
  resets_at: string | null
}

export type Credits = { provider: string; balance: number | null; unlimited: boolean }

const TOOLS = ["claude", "codex"]

/** A tool's weekly window as a figure, or a dash while it isn't read. */
function weekly(rows: UsageRow[], provider: string): string {
  const used = rows.find((r) => r.provider === provider && r.window === "weekly")?.used
  return used === null || used === undefined ? "–" : `${Math.round(used)}%`
}

/** Lighter and smaller, as far as VS Code's hovers allow: a span coloured by the theme. */
const light = (text: string) =>
  `<span style="color:var(--vscode-descriptionForeground);"><small>${text}</small></span>`

function windowLine(row: UsageRow, now: number): string {
  const label = windowLabel(row.window)
  if (row.used === null) return `${label}: not reported`
  const resets = row.resets_at
    ? ` ${light(`resets ${resetStamp(row.resets_at, new Date(now))}`)}`
    : ""
  return `${label}: ${Math.round(row.used)}% used${resets}`
}

function creditLine(c: Credits): string {
  const left = c.unlimited
    ? "unlimited"
    : c.balance === null
      ? "not reported"
      : Math.round(c.balance).toLocaleString("en-US")
  return `Credits: ${left}`
}

/**
 * The status bar's reading: each tool's weekly window by the tool's icon, in the bar's own
 * colours; on hover, each tool's windows under its mark and name, as ax's panel heads
 * them, each with when it resets, and Codex's credits. Markdown, with theme icons and
 * HTML.
 */
export function usageStatus(rows: UsageRow[], credits: Credits[], now = Date.now()) {
  const sections = TOOLS.map((tool) => {
    const lines = [
      ...rows.filter((r) => r.provider === tool).map((row) => windowLine(row, now)),
      ...credits.filter((c) => c.provider === tool).map(creditLine),
    ]
    const heading = `$(ax-${tool}) **${toolName(tool)}**`
    return [heading, ...(lines.length ? lines : ["not reported"])].join("  \n")
  })
  return {
    text: `$(ax-claude) ${weekly(rows, "claude")}  $(ax-codex) ${weekly(rows, "codex")}`,
    tooltip: sections.join("\n\n"),
  }
}

/** The status bar while ax doesn't answer: a mark saying so, and how to bring it back,
 * rather than usage that silently disappears. */
export function offlineStatus(server: string): { text: string; tooltip: string } {
  return {
    text: "$(debug-disconnect) ax",
    tooltip: `ax isn't answering at ${server}, so the sessions shown may be out of date. Start it with \`ax app start\`, or check ax.server in Settings.`,
  }
}

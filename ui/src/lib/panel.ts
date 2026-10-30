/** The panel on VS Code's right: its list of sessions and the folders a new one can start in. */

import { PROVIDERS, type Provider, type Session } from "@/lib/sessions"

/** How long ago, as Codex's chat list says it: "now", "5m", "1h", "5d". */
export function since(iso: string | null, now = Date.now()): string {
  if (!iso) return ""
  const minutes = Math.floor((now - Date.parse(iso)) / 60_000)
  if (Number.isNaN(minutes)) return ""
  if (minutes < 1) return "now"
  if (minutes < 60) return `${minutes}m`
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)}h`
  return `${Math.floor(minutes / (24 * 60))}d`
}

export type PanelRow = {
  provider: Provider
  id: string
  name: string
  state: Session["state"]
  /** What it is doing, in words: "Needs approval", "Working", or nothing when idle. */
  status: string | null
  when: string
  tool: string
  project: string | null
}

const rank = (s: Session) => (s.state === "waiting" ? 0 : s.state === "working" ? 1 : 2)

function status(s: Session): string | null {
  if (s.state === "waiting")
    return s.waiting_for === "approval" ? "Needs approval" : "Waiting for you"
  return s.state === "working" ? "Working" : null
}

/** The sessions as rows: what waits for you first, then what works, newest first in each. */
export function panelRows(sessions: Session[], now = Date.now()): PanelRow[] {
  return [...sessions]
    .sort(
      (a, b) =>
        Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) ||
        (a.order ?? 0) - (b.order ?? 0) ||
        rank(a) - rank(b) ||
        (b.updated ?? "").localeCompare(a.updated ?? "")
    )
    .map((s) => ({
      provider: s.provider,
      id: s.id,
      name: s.name,
      state: s.state,
      status: status(s),
      when: since(s.updated, now),
      tool: PROVIDERS.find((p) => p.provider === s.provider)?.label ?? s.provider,
      project: s.project,
    }))
}

/** A row's key: its tool and its id. */
export const rowKey = (row: { provider: string; id: string }) => `${row.provider}:${row.id}`

/**
 * The rows in the order they had while the pointer is over the list, so none moves under
 * it as sessions change state: new ones join at the end, ended ones leave.
 */
export function keptOrder<T extends { provider: string; id: string }>(
  rows: T[],
  order: string[]
): T[] {
  const place = new Map(order.map((key, i) => [key, i]))
  const kept = rows.filter((r) => place.has(rowKey(r)))
  kept.sort((a, b) => (place.get(rowKey(a)) ?? 0) - (place.get(rowKey(b)) ?? 0))
  return [...kept, ...rows.filter((r) => !place.has(rowKey(r)))]
}

/** Why the list is empty when ax doesn't answer; VS Code's own error already says so. */
export function unanswered(error: string): string {
  return error.startsWith("ax isn't answering") ? error : `ax isn't answering: ${error}`
}

export type FolderChoice = { path: string; label: string }

const named = (path: string): FolderChoice => ({
  path,
  label: path.split("/").filter(Boolean).at(-1) ?? path,
})

/** Where a new session can start: the workspace's folders, then the folders recent
 * sessions ran in (newest first), each once, narrowed to the words searched. */
export function folderChoices(workspace: string[], sessions: Session[], query: string) {
  const words = query.trim().toLowerCase()
  const fits = (f: FolderChoice) => !words || f.path.toLowerCase().includes(words)
  const mine = [...new Set(workspace)]
  const recent = [...sessions]
    .sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""))
    .map((s) => s.cwd)
    .filter((cwd): cwd is string => Boolean(cwd) && !mine.includes(cwd as string))
  return {
    workspace: mine.map(named).filter(fits),
    recent: [...new Set(recent)].map(named).filter(fits),
  }
}

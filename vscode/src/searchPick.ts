/**
 * The rows of ax's search at the top centre, where VS Code's own pickers open: the live
 * sessions until something is typed, then what `ax find` found, each saying how it opens.
 */

import type { Provider, Session } from "./listing"

/** One of `ax find`'s hits, as `/api/find` gives it. */
export type Hit = {
  source: string
  path: string
  title: string
  snippet: string
  handle?: string
  /** A conversation's session id, to open it by. */
  session?: string
  provider?: string
  project?: string | null
  date?: string
  /** When a conversation began, to tell it from others of the same name. */
  started?: string
  line?: number | null
  /** A vault note's path inside the vault. */
  note?: string | null
}

/** A session's tab, or a file at its line. */
export type Open = { session: { provider: Provider; id: string; name: string } } | { file: string }

export type PickRow = {
  label: string
  description?: string
  detail?: string
  /** A hit stays whatever is typed; a live session narrows to what matches. */
  alwaysShow?: true
  open?: Open
}

const ICONS: Record<string, string> = {
  conversation: "comment-discussion",
  memory: "lightbulb",
  subagent: "hubot",
}
const SHORT: Record<string, string> = { claude: "Claude", codex: "Codex" }
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

const isProvider = (value: unknown): value is Provider => value === "claude" || value === "codex"

/** When, as a person says it: today, yesterday, 3 days ago, Aug 22, or Dec 30, 2025. */
export function when(date: string, now = Date.now()): string {
  const [y, m, d] = date.split("-").map(Number)
  if (!y || !m || !d) return date
  const today = new Date(now)
  today.setHours(0, 0, 0, 0)
  const days = Math.round((today.getTime() - new Date(y, m - 1, d).getTime()) / 86_400_000)
  if (days === 0) return "today"
  if (days === 1) return "yesterday"
  if (days > 1 && days < 7) return `${days} days ago`
  const day = `${MONTHS[m - 1]} ${d}`
  return y === today.getFullYear() ? day : `${day}, ${y}`
}

/** When a conversation began, to the minute: today 10:01, Sat 10:01, Aug 22, 10:01. Just
 * the day when the time isn't known. */
function began(hit: Hit, now: number): string | null {
  const at = hit.started ? new Date(hit.started) : null
  if (!at || Number.isNaN(at.getTime())) return hit.date ? when(hit.date, now) : null
  const pad = (n: number) => String(n).padStart(2, "0")
  const day = when(`${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`, now)
  const clock = `${pad(at.getHours())}:${pad(at.getMinutes())}`
  if (day.endsWith("days ago")) return `${DAYS[at.getDay()]} ${clock}`
  return day.includes(" ") ? `${day}, ${clock}` : `${day} ${clock}`
}

/** What tells a hit from the others beside it: a conversation's tool, project and start; a
 * memory's project. */
function where(hit: Hit, now: number): string {
  switch (hit.source) {
    case "conversation":
    case "subagent":
      return [
        hit.source === "subagent" ? "Subagent" : (SHORT[hit.provider ?? ""] ?? hit.provider),
        hit.project,
        began(hit, now),
      ]
        .filter(Boolean)
        .join(" · ")
    default:
      return ["Memory", hit.project].filter(Boolean).join(" · ")
  }
}

/**
 * A hit as a row: its kind's icon and what to call it, what tells it from the others,
 * and the passage that matched (what was said, a memory's description). Every row shows
 * whatever is typed: a hit found by meaning need not hold the words.
 */
export function hitItem(hit: Hit, now = Date.now()): PickRow {
  const open: Open =
    hit.source === "conversation" && hit.session && isProvider(hit.provider)
      ? { session: { provider: hit.provider, id: hit.session, name: hit.title } }
      : { file: `${hit.path}${hit.line ? `#L${hit.line}` : ""}` }
  return {
    label: `$(${ICONS[hit.source] ?? "search"}) ${hit.title}`,
    description: where(hit, now),
    ...(hit.snippet ? { detail: hit.snippet } : {}),
    alwaysShow: true,
    open,
  }
}

const TOOLS: Record<Provider, string> = { claude: "Claude Code", codex: "Codex" }

/** The live sessions, those waiting for you first, before anything is typed; typing
 * narrows them to the ones whose names match until the search answers. */
export function liveItems(sessions: Session[]): PickRow[] {
  const waiting = sessions.filter((s) => s.state === "waiting")
  const rest = sessions.filter((s) => s.state !== "waiting")
  return [...waiting, ...rest].map((s) => {
    const icon =
      s.state === "waiting"
        ? "bell-dot"
        : s.state === "working"
          ? "sync~spin"
          : "comment-discussion"
    const state =
      s.state === "waiting" ? "waiting for you" : s.state === "working" ? "working" : null
    return {
      label: `$(${icon}) ${s.name}`,
      description: [TOOLS[s.provider], s.project, state].filter(Boolean).join(" · "),
      open: { session: { provider: s.provider, id: s.id, name: s.name } },
    }
  })
}

/** The rows shown, narrowing to what is typed while a new search runs: an answer to the
 * words before can't be opened by Enter as if it answered these. */
export const narrowing = <T extends PickRow>(rows: readonly T[]): T[] =>
  rows.map(({ alwaysShow: _, ...row }) => row as T)

/** Within this many milliseconds of opening, a close nobody chose is focus taken back. */
const TAKEN_WITHIN = 300

/**
 * Whether the picker closed because focus was taken from it as it opened, rather than by
 * you: a session tab's menu that just closed hands its focus back to the page, and VS
 * Code closes a picker that loses focus. Then it opens again, once.
 */
export function focusTaken(closed: {
  openFor: number
  accepted: boolean
  reopened: boolean
}): boolean {
  return !closed.accepted && !closed.reopened && closed.openFor < TAKEN_WITHIN
}

/** A search's keyword stage (`fast`), or the whole search, by meaning too. */
export const searchUrl = (query: string, fast: boolean) =>
  `/api/find?q=${encodeURIComponent(query)}${fast ? "&fast=1" : ""}`

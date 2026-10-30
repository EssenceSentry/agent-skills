import type { Listing, Session } from "./listing"

const key = (s: Session) => `${s.provider}:${s.id}`

/**
 * The sessions that have started waiting for the user since the last reading. The first
 * reading announces nothing: the badge already counts what waits.
 */
export function newlyWaiting(before: Listing | null, now: Listing): Session[] {
  if (!before) return []
  const waited = new Set(before.sessions.filter((s) => s.state === "waiting").map(key))
  return now.sessions.filter((s) => s.state === "waiting" && !waited.has(key(s)))
}

const LIMIT = 160

/** One line: the session, what it needs, and the last thing it said. */
export function notice(s: Session): string {
  const needs = s.waiting_for === "approval" ? "needs your approval" : "is waiting for you"
  return short(`${s.name} ${needs}${s.last ? `: ${s.last}` : ""}`)
}

const short = (text: string) => (text.length > LIMIT ? `${text.slice(0, LIMIT - 1)}…` : text)

/**
 * What to say about the sessions that started waiting since the last reading: a session
 * alone gets its own notice, which opens it; two or more get one notice naming them,
 * which shows the panel, never a stack of them.
 */
export function announcement(fresh: Session[]): { text: string; open: Session | null } | null {
  const [first] = fresh
  if (!first) return null
  if (fresh.length === 1) return { text: notice(first), open: first }
  const names = fresh.map((s) => s.name)
  const listed = `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`
  return { text: short(`${fresh.length} sessions wait for you: ${listed}`), open: null }
}

import type { Listing, Session } from "./tree"

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
  const said = `${s.name} ${needs}${s.last ? `: ${s.last}` : ""}`
  return said.length > LIMIT ? `${said.slice(0, LIMIT - 1)}…` : said
}

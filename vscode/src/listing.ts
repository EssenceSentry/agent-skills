/** What `/api/sessions` lists: the fields the extension reads for the badge and notices. */

export type Provider = "claude" | "codex"

/** One live session, as `/api/sessions` lists it. */
export type Session = {
  provider: Provider
  id: string
  name: string
  cwd: string | null
  project: string | null
  state: "working" | "waiting" | "idle" | null
  waiting_for: string | null
  updated: string | null
  last: string | null
}

export type Listing = { sessions: Session[]; errors: string[] }

/** The sessions waiting for you: the count on the panel's badge. */
export function waitingCount(listing: Listing): number {
  return listing.sessions.filter((s) => s.state === "waiting").length
}

/** A session tab's icon, by what the session is doing: an amber bell while it waits for
 * you, a blue arc while it works, the plain chat mark otherwise. The shapes differ as
 * well as the colours, so the tabs read side by side at a glance. */
export function tabIcon(state: Session["state"]): string {
  if (state === "waiting") return "tab-waiting.svg"
  if (state === "working") return "tab-working.svg"
  return "tab.svg"
}

/** VS Code's ViewColumn.Beside, kept here so the rule below needs no VS Code. */
const BESIDE = -2

/** Where an open session's tab goes when it is opened again: beside the one in front when
 * asked to open to the side, so it can join another column; where it is otherwise. */
export function revealIn(current: number | undefined, requested: number): number {
  if (requested === BESIDE) return BESIDE
  return current ?? requested
}

/** The session tabs that aren't on screen: in each column, every tab behind the one in
 * front, which stays. */
export function offScreen<T extends { visible: boolean }>(tabs: T[]): T[] {
  return tabs.filter((t) => !t.visible)
}

/** How long a tab's own report of its state outranks the listing, which lags it. */
const REPORT_HOLDS = 10_000

/**
 * The state a session tab's icon shows: what its own page reported, which knows the
 * moment you act there, until the listing has had time to catch up; then the listing's.
 */
export function tabState(
  listed: Session["state"],
  reported: { state: Session["state"]; at: number } | undefined,
  now = Date.now()
): Session["state"] {
  return reported && now - reported.at < REPORT_HOLDS ? reported.state : listed
}

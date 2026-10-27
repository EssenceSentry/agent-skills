/** The sessions sidebar as plain data: what `/api/sessions` lists, grouped for a tree. */

export type Provider = "claude" | "codex"

/** One live session, as `/api/sessions` lists it (the fields the sidebar uses). */
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

/** A codicon, and the theme colour to paint it with. */
export type Icon = { id: string; color?: string }

export type TreeNode =
  | { kind: "group"; key: string; label: string; description?: string; children: TreeNode[] }
  | {
      kind: "session"
      key: string
      provider: Provider
      id: string
      label: string
      description: string
      tooltip: string
      icon: Icon
    }
  | { kind: "message"; key: string; label: string; tooltip?: string; icon: Icon }

const TOOLS: { provider: Provider; label: string }[] = [
  { provider: "claude", label: "Claude Code" },
  { provider: "codex", label: "Codex" },
]

const WARNING: Icon = { id: "warning", color: "list.warningForeground" }

const rank = (s: Session) => (s.state === "waiting" ? 0 : s.state === "working" ? 1 : 2)
const newer = (a: Session, b: Session) => (b.updated ?? "").localeCompare(a.updated ?? "")
const byUrgency = (a: Session, b: Session) => rank(a) - rank(b) || newer(a, b)

/** How long ago, in the fewest words a sidebar can hold. */
export function ago(when: string | null, now: number): string {
  if (!when) return ""
  const minutes = Math.floor((now - Date.parse(when)) / 60_000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`
  return `${Math.floor(minutes / (24 * 60))} d ago`
}

function describe(s: Session, now: number): string {
  if (s.state === "waiting")
    return s.waiting_for === "approval" ? "Needs approval" : "Waiting for you"
  if (s.state === "working") return "Working"
  return ago(s.updated, now)
}

function icon(s: Session): Icon {
  if (s.state === "waiting") return { id: "bell-dot", color: "list.warningForeground" }
  if (s.state === "working") return { id: "sync~spin" }
  return { id: "circle-outline" }
}

const projectOf = (s: Session) =>
  s.project ?? s.cwd?.split("/").filter(Boolean).at(-1) ?? "No folder"

const waitingNote = (sessions: Session[]) => {
  const n = sessions.filter((s) => s.state === "waiting").length
  return n ? `${n} waiting` : undefined
}

function sessionNode(s: Session, now: number): TreeNode {
  return {
    kind: "session",
    key: `${s.provider}:${s.id}`,
    provider: s.provider,
    id: s.id,
    label: s.name,
    description: describe(s, now),
    tooltip: [s.name, s.last, s.cwd].filter(Boolean).join("\n"),
    icon: icon(s),
  }
}

/**
 * Tool, then project, then session; a project with a session waiting comes first, and
 * within one, waiting sessions, then working, then idle, the latest first.
 */
export function sessionTree(listing: Listing | { error: string }, now: number): TreeNode[] {
  if ("error" in listing)
    return [
      {
        kind: "message",
        key: "offline",
        label: "ax isn't answering: start it with `ax app start`",
        tooltip: listing.error,
        icon: WARNING,
      },
    ]
  const tools: TreeNode[] = TOOLS.flatMap(({ provider, label }) => {
    const mine = listing.sessions.filter((s) => s.provider === provider)
    if (!mine.length) return []
    const projects = new Map<string, Session[]>()
    for (const s of mine) projects.set(projectOf(s), [...(projects.get(projectOf(s)) ?? []), s])
    const ordered = [...projects].map(([name, list]) => ({ name, list: list.sort(byUrgency) }))
    ordered.sort((a, b) => byUrgency(a.list[0] as Session, b.list[0] as Session))
    return [
      {
        kind: "group" as const,
        key: provider,
        label,
        description: waitingNote(mine),
        children: ordered.map(({ name, list }) => ({
          kind: "group" as const,
          key: `${provider}/${name}`,
          label: name,
          children: list.map((s) => sessionNode(s, now)),
        })),
      },
    ]
  })
  const errors: TreeNode[] = listing.errors.map((error, i) => ({
    kind: "message",
    key: `error:${i}`,
    label: error,
    icon: WARNING,
  }))
  if (!tools.length && !errors.length)
    return [{ kind: "message", key: "empty", label: "No live sessions", icon: { id: "info" } }]
  return [...tools, ...errors]
}

/** The sessions waiting for you: the count on the sidebar's badge. */
export function waitingCount(listing: Listing): number {
  return listing.sessions.filter((s) => s.state === "waiting").length
}

import type { Status } from "@/blocks/primitives"

export type Provider = "claude" | "codex"
export type SessionState = "working" | "waiting" | "idle"

/** One live session of either tool, as `/api/sessions` lists it. */
export type Session = {
  provider: Provider
  id: string
  name: string
  cwd: string | null
  project: string | null
  state: SessionState | null
  /** What a waiting session needs: "approval", "input needed", … */
  waiting_for: string | null
  kind: string | null
  started: string | null
  /** When it last said or did something. */
  updated: string | null
  /** The first line of the last thing it said. */
  last: string | null
  /** How many job cards it has. */
  jobs: number
}

export type Sessions = { sessions: Session[]; errors: string[] }

/** What a chat shows of a job its session is waiting on. */
export type Card = {
  key: string
  label: string
  kind: string
  status: string
  stage: string | null
  message: string | null
  progress: {
    done: number | null
    total: number | null
    unit: string | null
    percent: number | null
    text: string
  }
  eta: string | null
  /** Haiku's last look: only the last one. */
  look: { summary: string; at: string } | null
  notebook: {
    cell: { index: number; label: string | null } | null
    cells: { done: number; total: number }
    /** What the notebook started that still runs, such as a SageMaker job. */
    resources: { label: string; kind: string; status: string }[]
  } | null
  /** Set when the job ended and its agent never heard: then the card stays. */
  attention: string | null
  page: string
  updated: string
}

export type TranscriptEvent = {
  i: number
  kind: "user" | "assistant" | "tool" | "notice" | string
  text: string
  tool: string | null
  ok: boolean | null
  output: string
  ts: string | null
}

/**
 * Your messages and the agent's answers (finished commands and notices are left out),
 * and the command it runs now, if any. `next` counts every event; `earlier` is how many
 * messages came before the first one sent.
 */
export type TranscriptPage = {
  events: TranscriptEvent[]
  next: number
  first: number
  running: TranscriptEvent[]
  earlier: number
}

export type SessionView = TranscriptPage & { session: Session; cards: Card[] }

export const PROVIDERS: { provider: Provider; label: string }[] = [
  { provider: "claude", label: "Claude Code" },
  { provider: "codex", label: "Codex" },
]

/**
 * The cards under a session's transcript: hidden while it thinks, since its own output is
 * the news then, and back once it stops. A job that failed without its agent hearing of
 * it stays regardless.
 */
export function shownCards(session: Session | null, cards: Card[]): Card[] {
  if (session?.state !== "working") return cards
  return cards.filter((c) => c.attention)
}

export function groupSessions(sessions: Session[]) {
  return PROVIDERS.map(({ provider, label }) => ({
    provider,
    label,
    sessions: sessions.filter((s) => s.provider === provider),
  })).filter((g) => g.sessions.length)
}

export function stateBadge(session: Session): { status: Status; label: string } {
  if (session.state === "working") return { status: "running", label: "Working" }
  if (session.state === "waiting")
    return {
      status: "warning",
      label: session.waiting_for === "approval" ? "Needs approval" : "Waiting for you",
    }
  return { status: "paused", label: "Idle" }
}

const same = (a: TranscriptEvent[], b: TranscriptEvent[]) =>
  a.length === b.length && a.every((e, i) => e.i === b[i]?.i)

/**
 * New messages after the ones on screen, and the command running now from the latest
 * reading; a page that doesn't follow on replaces them.
 */
export function mergePage(shown: TranscriptPage, page: TranscriptPage): TranscriptPage {
  if (page.first > shown.next || page.next < shown.next) return page
  const running = page.running ?? []
  if (page.next === shown.next) return same(shown.running, running) ? shown : { ...shown, running }
  const fresh = page.events.filter((e) => e.i >= shown.next)
  return { ...shown, events: [...shown.events, ...fresh], next: page.next, running }
}

/** The one command worth a line: the one running now, while the session works. */
export function runningNow(session: Session | null, page: TranscriptPage): TranscriptEvent | null {
  if (session?.state !== "working") return null
  return page.running[page.running.length - 1] ?? null
}

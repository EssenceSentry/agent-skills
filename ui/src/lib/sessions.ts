import type { Status } from "@/blocks/primitives"
import { shortPath } from "@/lib/paths"

export type Provider = "claude" | "codex"
export type SessionState = "working" | "waiting" | "idle"

/** One live session of either tool, as `/api/sessions` lists it. */
export type Session = {
  pinned?: boolean
  archived?: boolean
  group?: string
  order?: number
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
    /** The notebook the run executes, which the editor can open at its cell. */
    path?: string | null
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

/** A picture in a conversation, read from the transcript by its place. */
export type Picture = { url: string; media: string; line: number; n: number }

/** One question an agent asked, with the options it offered. */
export type Question = {
  id: string | null
  header: string | null
  question: string
  options: { label: string; description: string }[]
  multi: boolean
  /** Whether words other than the options are taken. */
  other: boolean
  secret: boolean
}

/**
 * Questions asked together and their answers, one list per question (null where none
 * was given). `via` says how it is answered: Claude's AskUserQuestion, Codex's
 * request_user_input, or its async kind, answered by a reply message.
 */
export type Ask = {
  via: "claude" | "codex" | "codex-async"
  call: string | null
  status: "open" | "answered" | "declined"
  questions: Question[]
  answers: (string[] | null)[] | null
}

export type TranscriptEvent = {
  native_id?: string | null
  call_id?: string | null
  turn_id?: string | null
  i: number
  kind: "user" | "assistant" | "tool" | "notice" | string
  text: string
  tool: string | null
  ok: boolean | null
  exit_code?: number | null
  duration_ms?: number | null
  output: string
  ts: string | null
  /** Pictures the user pasted into this message. */
  images?: Picture[]
  /** Screenshots and pictures the agent's tools took before this answer. */
  shots?: Picture[]
  /** On a question event: what it asked and what was answered. */
  ask?: Ask
}

/**
 * Your messages and the agent's answers (finished commands and notices are left out),
 * and the command it runs now, if any. `next` counts every event; `earlier` is how many
 * messages came before the first one sent.
 */
export type TranscriptPage = {
  cursor?: string
  reset?: boolean
  events: TranscriptEvent[]
  next: number
  first: number
  running: TranscriptEvent[]
  earlier: number
  /** Screenshots taken since the last answer, still waiting for one. */
  shots?: Picture[]
}

/** An approval a session ax holds waits on. */
export type Approval = {
  id: string
  tool: string
  summary: string
  reason: string | null
  detail: string | null
  /** The plan, when Claude asks to leave plan mode and start on it. */
  plan?: string | null
}

/** Plan mode, approve for me, and the model and effort; null is the session's own. */
export type ChatSettings = {
  plan: boolean
  auto: boolean
  model: string | null
  effort: string | null
}

/** A model the session offers, and the efforts it takes. */
export type ModelInfo = {
  id: string
  label: string
  efforts: string[]
  default_effort: string | null
}

/** What the session keeps pursuing; Codex reports its progress, Claude only that it's set. */
export type Goal = {
  objective: string
  status: string
  tokens_used: number | null
  token_budget: number | null
  seconds: number | null
}

/**
 * Who holds the conversation and whether you can write to it now: "ax" (in the
 * background), "codex app", "elsewhere" (the Claude app or a terminal: take it over
 * first), or nobody yet.
 */
export type PendingMessage = {
  id: string
  text: string
  status: string
  error?: string | null
  delivery: "steer" | "queue"
  attachments?: number
}
export type PendingRequest = Approval & {
  kind: "approval" | "elicitation" | "question"
  questions?: Question[]
  via?: Ask["via"]
  elicitation?: Record<string, unknown>
}
export type ChatState = {
  delivery_paused?: boolean
  receipts?: string[]
  api_version?: number
  requests?: PendingRequest[]
  outbox?: PendingMessage[]
  ownership?: "ax" | "open" | "closed" | "unknown"
  delivery?: ("steer" | "queue")[]
  pending_settings?: Partial<ChatSettings>
  diagnostics?: string
  context?: { last?: { totalTokens?: number }; modelContextWindow?: number | null }

  holder: "ax" | "codex app" | "elsewhere" | null
  can_send: boolean
  take_over: boolean
  /** A message kept for a session another app holds, sent when ax takes it over. */
  queued?: string | null
  /** What the user sent while a turn ran, until the turn ends: it reads it as it goes. */
  mid_turn?: string[]
  pending: boolean
  busy: boolean
  /** The reply streaming in. */
  partial: string
  approval: Approval | null
  /** A question it waits on, in a session ax holds. */
  question?: { id: string; via: Ask["via"]; call: string | null; questions: Question[] } | null
  error: string | null
  note: string
  /** Null until ax holds the session. */
  settings?: ChatSettings | null
  models?: ModelInfo[]
  goal?: Goal | null
  tasks?: Tasks | null
}

/** What the session is doing now: the tool it runs, said as the desktop app says it. */
export type Activity = { text: string; since: string | null }

export type TaskStatus = "pending" | "in_progress" | "completed"

/** The current turn's task list, as the agent keeps it. */
export type Tasks = {
  items: { text: string; status: TaskStatus }[]
  explanation: string | null
}

export type SessionView = TranscriptPage & {
  session: Session
  cards: Card[]
  chat?: ChatState
  activity?: Activity | null
  tasks?: Tasks | null
}

export const PROVIDERS: { provider: Provider; label: string }[] = [
  { provider: "claude", label: "Claude Code" },
  { provider: "codex", label: "Codex" },
]

/** The line under a session's name: its tool, its project unless the folder already
 * says it, and its folder from ~. */
export function metaLine(provider: string, project: string | null, cwd: string | null): string {
  const tool = PROVIDERS.find((p) => p.provider === provider)?.label ?? provider
  const named = project && cwd?.split("/").filter(Boolean).at(-1) === project
  return [tool, named ? null : project, cwd && shortPath(cwd)].filter(Boolean).join(" · ")
}

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

/** The questions on screen still waiting for an answer, which each reading asks for again. */
export function openQuestions(page: TranscriptPage): number[] {
  return page.events.filter((e) => e.ask?.status === "open").map((e) => e.i)
}

/**
 * New messages after the ones on screen, questions on screen as they are now, and the
 * command running now from the latest reading; a page that doesn't follow on replaces
 * them.
 */
export function mergePage(shown: TranscriptPage, page: TranscriptPage): TranscriptPage {
  if (page.first > shown.next || page.next < shown.next) return page
  const running = page.running ?? []
  const shots = page.shots ?? []
  const now = new Map(page.events.filter((e) => e.i < shown.next).map((e) => [e.i, e]))
  const events = now.size ? shown.events.map((e) => now.get(e.i) ?? e) : shown.events
  if (page.next === shown.next)
    return !now.size && same(shown.running, running) && (shown.shots ?? []).length === shots.length
      ? shown
      : { ...shown, events, running, shots }
  const fresh = page.events.filter((e) => e.i >= shown.next)
  return { ...shown, events: [...events, ...fresh], next: page.next, running, shots }
}

/** The one command worth a line: the one running now, while the session works. */
export function runningNow(session: Session | null, page: TranscriptPage): TranscriptEvent | null {
  if (session?.state !== "working") return null
  return page.running[page.running.length - 1] ?? null
}

/** A session ax holds says itself what it does: it waits while it asks, else works or rests. */
export function heldState(chat: ChatState): SessionState {
  if (chat.approval || chat.question) return "waiting"
  return chat.busy ? "working" : "idle"
}

export type ComposerMode = "send" | "busy" | "take-over" | "waiting"

export function composerMode(chat: ChatState): ComposerMode {
  if (chat.take_over) return chat.pending ? "waiting" : "take-over"
  return chat.busy ? "busy" : "send"
}

export function canSend(chat: ChatState, text: string, images = 0): boolean {
  return chat.can_send && (text.trim().length > 0 || images > 0)
}

/** The folders the sessions work in, the most recently active first, once each. */
export function folderSuggestions(sessions: Session[]): string[] {
  const dated = sessions
    .filter((s): s is Session & { cwd: string } => Boolean(s.cwd))
    .sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""))
  return [...new Set(dated.map((s) => s.cwd))]
}

export function canStart(folder: string, text: string, images = 0): boolean {
  return folder.trim().length > 0 && (text.trim().length > 0 || images > 0)
}

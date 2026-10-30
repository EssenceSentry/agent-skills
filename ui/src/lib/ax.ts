import { useCallback, useEffect, useState } from "react"

import {
  exampleFind,
  exampleFolder,
  exampleModels,
  exampleNote,
  exampleNow,
  exampleSession,
  exampleSessions,
  exampleSlash,
} from "@/lib/example"
import type { ModelGroup } from "@/lib/models"
import type { Hit } from "@/lib/search"
import { SessionFeed } from "@/lib/session-feed"
import type { Sessions, SessionView } from "@/lib/sessions"
import type { SlashItem } from "@/lib/slash"
import { request, transportIdentity } from "@/lib/transport"

export type UsageRow = {
  provider: string
  window: string
  used: number | null
  status: string
  resets_at: string | null
  lasts: boolean | null
  projected_high: number | null
  runs_out_at: string | null
}

export type Credits = {
  provider: string
  balance: number | null
  unlimited: boolean
  has_credits: boolean
  observed_at: string
  status: string
}

export type ActionName =
  | "accept"
  | "reject"
  | "restore"
  | "dismiss"
  | "keep"
  | "retire"
  | "guard"
  | "done"
  | "drop"

export type Waiting = {
  kind: "job" | "usage" | "budget" | "proposal" | "review" | "instruction" | "todo"
  id: string
  title: string
  detail: string
  actions: ActionName[]
  note?: string | null
  scope?: string
  origin?: string | null
  maturity?: string
  status?: string
  updated?: string
  resets_at?: string | null
  created?: string
}

export type Job = {
  key: string
  label: string
  status: string
  stage: string | null
  progress: string
  percent: number | null
  eta: string | null
  check_error: string | null
  updated: string
  link: string | null
  /** The job's dashboard inside the app, reachable through the app's own link. */
  page?: string
  /** Seconds between Haiku's looks at the log, when it looks. */
  check_every?: number | null
  /** What Haiku saw last: where the job is, what looks wrong, and whether it fell behind. */
  look?: { at: string; summary: string; problem: string | null; slow?: string | null } | null
}

export type BudgetEntry = {
  ticket: string | null
  kind: "add" | "hold" | "pass"
  amount: number
  note: string | null
  agent: string | null
  intent: string | null
  at: string
  state: string | null
  actual: number | null
}

export type Budget = {
  name: string
  cap: number
  unit: string
  why: string | null
  owner: string | null
  owner_note: string | null
  scope: string | null
  project: string | null
  path: string | null
  created: string
  spent: number
  reserved: number
  left: number
  state: "ok" | "near" | "over"
  passes: number
  entries: BudgetEntry[]
}

/** A rule you accepted or set aside for now, or that was set aside for you. */
export type Decided = {
  id: string
  title: string
  status: "accepted" | "not-now"
  decided: string
  decided_by: string
  superseded_by: string | null
  scope: string
  note: string | null
  actions: ActionName[]
}

export type Conversation = {
  handle: string
  title: string
  provider: string
  project: string | null
  ended: string | null
  note: string
}

export type NowState = {
  generated: string
  last_sync: string | null
  usage: UsageRow[]
  credits: Credits[]
  waiting: Waiting[]
  jobs: Job[]
  budgets: Budget[]
  decided: Decided[]
  conversations: Conversation[]
  errors: string[]
}

export type Folder = {
  path: string
  parent: string | null
  folders: { name: string; path: string }[]
  notes: { path: string; title: string; modified: string }[]
}

export type Note = {
  path: string
  title: string
  properties: { key: string; value: string }[]
  markdown: string
  modified: string
}

export type LiveStatus = "example" | "connecting" | "live" | "offline" | "locked"

/** True when `ax serve` hosts the page; otherwise it shows example data. */
export const LIVE =
  typeof document !== "undefined" && document.querySelector('meta[name="ax-live"]') !== null

const getJson = <T>(path: string): Promise<T> => request<T>("GET", path)

/** Run one action; the promise resolves to what ax says it did. */
export async function act(action: string, payload: Record<string, string>): Promise<string> {
  if (!LIVE) return "This is example data; nothing was changed."
  const body = await request<{ message: string }>("POST", "/api/act", { action, ...payload })
  return body.message
}

export const loadFolder = (dir: string): Promise<Folder> =>
  LIVE ? getJson(`/api/notes?dir=${encodeURIComponent(dir)}`) : Promise.resolve(exampleFolder(dir))

export const loadNote = (path: string): Promise<Note> =>
  LIVE ? getJson(`/api/note?path=${encodeURIComponent(path)}`) : Promise.resolve(exampleNote(path))

export type Found = { query: string; hits: Hit[] }

/** `ax find` through the server: under a second for its keyword stage (`fast`), a few
 * seconds for the whole search, by meaning too. */
export const loadFind = (query: string, fast = false): Promise<Found> =>
  LIVE
    ? getJson(`/api/find?q=${encodeURIComponent(query)}${fast ? "&fast=1" : ""}`)
    : Promise.resolve(exampleFind(query))

type Stages = {
  key: string
  fast?: Found
  full?: Found
  fastError?: string
  fullError?: string
}

export type FoundStage = {
  data?: Found
  loading: boolean
  /** The keyword stage is shown while the search by meaning goes on. */
  refining: boolean
  /** Why only the keyword stage is shown: the search by meaning failed. */
  partial?: string
  error?: string
}

/** What a two-stage search shows from what has answered so far. */
export function foundStage(s: Stages): FoundStage {
  if (s.full) return { data: s.full, loading: false, refining: false }
  if (s.fast)
    return s.fullError
      ? { data: s.fast, loading: false, refining: false, partial: s.fullError }
      : { data: s.fast, loading: false, refining: true }
  if (s.fullError && s.fastError) return { loading: false, refining: false, error: s.fullError }
  return { loading: true, refining: false }
}

/**
 * `ax find` in two stages asked at once: keywords answer in under a second and show at
 * once, then the whole search, by meaning too, takes their place.
 */
export function useStagedFind(query: string | null): FoundStage | null {
  const [stages, setStages] = useState<Stages | null>(null)
  useEffect(() => {
    if (query === null) return
    let current = true
    setStages({ key: query })
    const settle = (part: Partial<Stages>) =>
      current && setStages((was) => (was?.key === query ? { ...was, ...part } : was))
    loadFind(query, true).then(
      (fast) => settle({ fast }),
      (e: Error) => settle({ fastError: e.message })
    )
    loadFind(query).then(
      (full) => settle({ full }),
      (e: Error) => settle({ fullError: e.message })
    )
    return () => {
      current = false
    }
  }, [query])
  return query !== null && stages?.key === query ? foundStage(stages) : null
}

/**
 * The Now state: fetched at once, pushed by `ax serve` on `/events` when it changes, and
 * fetched again after an action so its result shows at once. A proxy can hold the stream
 * back (Cloudflare's tunnel has), so while it is quiet the state is read every 15 s.
 * Live, it is null until the first reading: the example data never stands in for yours.
 */
export function useNow(): {
  state: NowState | null
  status: LiveStatus
  refresh: () => void
} {
  const [state, setState] = useState<NowState | null>(LIVE ? null : exampleNow)
  const [status, setStatus] = useState<LiveStatus>(LIVE ? "connecting" : "example")

  const refresh = useCallback(() => {
    if (!LIVE) return
    getJson<NowState>("/api/now").then(
      (now) => {
        setState(now)
        setStatus("live")
      },
      // Through a tunnel, a page that lost its cookie needs the link again.
      (error: Error) => setStatus(error.message.startsWith("401") ? "locked" : "offline")
    )
  }, [])

  useEffect(() => {
    if (!LIVE) return
    let pushed = 0
    refresh()
    const events = new EventSource("/events")
    events.onmessage = (message: MessageEvent<string>) => {
      try {
        setState(JSON.parse(message.data) as NowState)
        setStatus("live")
        pushed = Date.now()
      } catch {
        setStatus("offline")
      }
    }
    const poll = setInterval(() => {
      if (Date.now() - pushed > 20_000) refresh()
    }, 15_000)
    return () => {
      events.close()
      clearInterval(poll)
    }
  }, [refresh])

  return { state, status, refresh }
}

/** Loads one thing, again whenever its key changes. */
export function useLoad<T>(key: string | null, load: (key: string) => Promise<T>) {
  const [result, setResult] = useState<{ key: string; data?: T; error?: string } | null>(null)
  useEffect(() => {
    if (key === null) return
    let current = true
    load(key).then(
      (data) => current && setResult({ key, data }),
      (error: Error) => current && setResult({ key, error: error.message })
    )
    return () => {
      current = false
    }
  }, [key, load])
  const settled = result && result.key === key ? result : null
  return { data: settled?.data, error: settled?.error, loading: key !== null && !settled }
}

/** Re-renders every so often, so "5 min ago" stays true between pushes. */
export function useTick(ms = 30_000) {
  const [, setTick] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), ms)
    return () => clearInterval(timer)
  }, [ms])
}

/** The models each tool offers a new session, asked once; a tool that can't answer
 * offers none. */
export function useModels(): ModelGroup[] {
  const [found, setFound] = useState(() => (LIVE ? null : exampleModels()))
  useEffect(() => {
    if (!LIVE) return
    let current = true
    getJson<ReturnType<typeof exampleModels>>("/api/models").then(
      (data) => current && setFound(data),
      () => undefined
    )
    return () => {
      current = false
    }
  }, [])
  if (!found) return []
  const groups: ModelGroup[] = [
    { provider: "claude", label: "Claude Code", models: found.claude },
    { provider: "codex", label: "Codex", models: found.codex },
  ]
  return groups.filter((g) => g.models.length > 0)
}

/** Both tools' usage windows and Codex's credits, read again every 10 s; null until the
 * first reading. */
export function useUsage(every = 10_000): Pick<NowState, "usage" | "credits"> | null {
  const [found, setFound] = useState<Pick<NowState, "usage" | "credits"> | null>(() =>
    LIVE ? null : { usage: exampleNow.usage, credits: exampleNow.credits }
  )
  useEffect(() => {
    if (!LIVE) return
    let current = true
    const load = () =>
      getJson<Pick<NowState, "usage" | "credits">>("/api/usage").then(
        (data) => current && setFound(data),
        () => undefined
      )
    load()
    const timer = setInterval(load, every)
    return () => {
      current = false
      clearInterval(timer)
    }
  }, [every])
  return found
}

export type SlashOffers = { commands: SlashItem[]; skills: SlashItem[]; error?: string }

const offers = new Map<string, Promise<SlashOffers>>()

/** What a session's tool offers its / menu, asked once a page per folder, when the menu
 * first opens; a failed answer is asked again the next time. */
export function useSlashOffers(
  provider: string,
  cwd: string | null,
  wanted: boolean
): { data?: SlashOffers; loading: boolean } {
  const key = `${provider}:${cwd ?? ""}`
  const [found, setFound] = useState<{ key: string; data: SlashOffers } | null>(null)
  const have = found?.key === key
  useEffect(() => {
    if (!wanted || have) return
    let current = true
    let asked = offers.get(key)
    if (!asked) {
      const where = cwd ? `&cwd=${encodeURIComponent(cwd)}` : ""
      asked = LIVE
        ? getJson<SlashOffers>(`/api/commands?provider=${encodeURIComponent(provider)}${where}`)
        : Promise.resolve(exampleSlash(provider))
      asked = asked.then(
        (data) => {
          if (data.error) offers.delete(key)
          return data
        },
        (e: Error) => {
          offers.delete(key)
          return { commands: [], skills: [], error: e.message }
        }
      )
      offers.set(key, asked)
    }
    asked.then((data) => current && setFound({ key, data }))
    return () => {
      current = false
    }
  }, [key, wanted, have, provider, cwd])
  return have && found ? { data: found.data, loading: false } : { loading: wanted }
}

/** Every live session of both tools, read again every few seconds while on screen. */
export function useSessions(every = 5_000) {
  // `at`: when ax last answered, kept with its last reading for once it stops answering.
  const [found, setFound] = useState<{ data?: Sessions; error?: string; at?: string }>(
    LIVE ? {} : { data: exampleSessions() }
  )
  useEffect(() => {
    if (!LIVE) return
    let current = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = () =>
      getJson<Sessions>("/api/sessions")
        .then(
          (data) => current && setFound({ data, at: new Date().toISOString() }),
          (error: Error) => current && setFound((was) => ({ ...was, error: error.message }))
        )
        .finally(() => {
          if (current) timer = setTimeout(load, every)
        })
    void load()
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [every])
  return found
}

/** The questions a reading asks for again, as the query takes them. */

/**
 * One session: its state and job cards, and its transcript, to which each reading adds
 * what happened since the last one and the answers to questions it showed open.
 */
const feeds = new Map<string, SessionFeed>()

export function useSession(provider: string, id: string, every = 3_000, streaming = 1_000) {
  const key = `${transportIdentity()}:${provider}:${id}`
  let feed = feeds.get(key)
  if (!feed) {
    const base = `/api/session?provider=${encodeURIComponent(provider)}&id=${encodeURIComponent(id)}`
    feed = new SessionFeed((query) => getJson<SessionView>(`${base}&${query}`), every, streaming)
    feeds.set(key, feed)
  }
  const currentFeed = feed
  const [snapshot, setSnapshot] = useState(() => ({ feed: currentFeed, value: currentFeed.state }))
  const found = LIVE
    ? snapshot.feed === currentFeed
      ? snapshot.value
      : currentFeed.state
    : { data: exampleSession(provider, id) }
  useEffect(() => {
    if (!LIVE) return
    const visible = () =>
      currentFeed.visibility(!document.hidden && document.body.dataset.hostVisible !== "false")
    visible()
    const unsubscribe = currentFeed.subscribe((value) => setSnapshot({ feed: currentFeed, value }))
    const refresh = () => void currentFeed.refresh()
    const hostVisible = (e: Event) => {
      document.body.dataset.hostVisible = String((e as CustomEvent<boolean>).detail)
      visible()
    }
    window.addEventListener("ax:hurry", refresh)
    window.addEventListener("ax:visibility", hostVisible)
    document.addEventListener("visibilitychange", visible)
    visible()
    return () => {
      unsubscribe()
      window.removeEventListener("ax:hurry", refresh)
      window.removeEventListener("ax:visibility", hostVisible)
      document.removeEventListener("visibilitychange", visible)
    }
  }, [currentFeed])
  return { ...found, loadEarlier: () => currentFeed.earlier() }
}

export const hurry = () => window.dispatchEvent(new Event("ax:hurry"))

/** What `/api/chat` answers. */
export type ChatAnswer = {
  ok: boolean
  message?: string
  via?: string
  waiting?: boolean
}

/** Send, answer, stop, take over or hand back; the server says why not as an error. */
export async function chatAct(payload: Record<string, unknown>): Promise<ChatAnswer> {
  if (!LIVE) return { ok: true, message: "This is example data; nothing was sent." }
  return request<ChatAnswer>("POST", "/api/chat", payload)
}

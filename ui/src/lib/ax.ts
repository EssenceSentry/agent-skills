import { useCallback, useEffect, useState } from "react"

import { exampleFolder, exampleNote, exampleNow } from "@/lib/example"

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

export type ActionName = "accept" | "reject" | "keep" | "retire" | "guard" | "done" | "drop"

export type Waiting = {
  kind: "job" | "usage" | "proposal" | "review" | "todo"
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

export type LiveStatus = "example" | "connecting" | "live" | "offline"

/** True when `ax serve` hosts the page; otherwise it shows example data. */
export const LIVE =
  typeof document !== "undefined" && document.querySelector('meta[name="ax-live"]') !== null

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.error ?? `${response.status} ${response.statusText}`)
  return body as T
}

/** Run one action; the promise resolves to what ax says it did. */
export async function act(action: string, payload: Record<string, string>): Promise<string> {
  if (!LIVE) return "This is example data; nothing was changed."
  const response = await fetch("/api/act", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ action, ...payload }),
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.error ?? `${response.status} ${response.statusText}`)
  return body.message as string
}

export const loadFolder = (dir: string): Promise<Folder> =>
  LIVE ? getJson(`/api/notes?dir=${encodeURIComponent(dir)}`) : Promise.resolve(exampleFolder(dir))

export const loadNote = (path: string): Promise<Note> =>
  LIVE ? getJson(`/api/note?path=${encodeURIComponent(path)}`) : Promise.resolve(exampleNote(path))

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
      () => setStatus("offline")
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

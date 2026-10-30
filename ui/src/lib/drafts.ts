import { useCallback, useEffect, useRef, useState } from "react"
import type { Pasted } from "./images"
import type { Reference } from "./plus"
import { askExtension, inExtension, transportIdentity } from "./transport"

export type FailedDraft = {
  id: string
  text: string
  payload: Record<string, unknown>
  refs?: Reference[]
  pictures?: Pasted[]
}
export type Draft = {
  text: string
  refs: Reference[]
  pictures: Pasted[]
  failed?: FailedDraft[]
  start?: { id: string; signature: string }
  ui?: Record<string, string | boolean>
}
const EMPTY: Draft = { text: "", refs: [], pictures: [] }
const memory = new Map<string, Draft>()
const writes = new Map<string, Promise<unknown>>()

async function database() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open("ax-drafts", 1)
    open.onupgradeneeded = () => open.result.createObjectStore("drafts")
    open.onsuccess = () => resolve(open.result)
    open.onerror = () => reject(open.error)
  })
}

export async function readDraft(key: string): Promise<Draft> {
  if (memory.has(key)) return memory.get(key) ?? EMPTY
  if (inExtension()) return (await askExtension<Draft | null>("draftRead", key)) ?? EMPTY
  if (typeof indexedDB === "undefined") return EMPTY
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const read = db.transaction("drafts").objectStore("drafts").get(key)
      read.onsuccess = () => resolve(read.result ?? EMPTY)
      read.onerror = () => reject(read.error)
    })
  } finally {
    db.close()
  }
}

export function writeDraft(key: string, value: Draft): Promise<unknown> {
  memory.set(key, value)
  const next = (writes.get(key) ?? Promise.resolve())
    .catch(() => {})
    .then(async () => {
      if (inExtension()) return askExtension("draftWrite", { key, value })
      if (typeof indexedDB === "undefined") return
      const db = await database()
      try {
        await new Promise<void>((resolve, reject) => {
          const tx = db.transaction("drafts", "readwrite")
          tx.objectStore("drafts").put(value, key)
          tx.oncomplete = () => resolve()
          tx.onerror = () => reject(tx.error)
        })
      } finally {
        db.close()
      }
    })
  writes.set(key, next)
  return next
}

export function useDraft(id: string) {
  const key = `${transportIdentity()}:${id}`
  const [state, setState] = useState(() => ({ key, value: memory.get(key) ?? EMPTY }))
  const [error, setError] = useState<string | null>(null)
  const value = state.key === key ? state.value : (memory.get(key) ?? EMPTY)
  const latest = useRef({ key, value })
  latest.current = { key, value }
  const versions = useRef(new Map<string, number>())
  useEffect(() => {
    let current = true
    const version = versions.current.get(key) ?? 0
    void readDraft(key).then(
      (saved) => {
        if (current && (versions.current.get(key) ?? 0) === version) setState({ key, value: saved })
      },
      (e: Error) => current && setError(`Draft recovery failed: ${e.message}`)
    )
    return () => {
      current = false
    }
  }, [key])
  const update = useCallback(
    (change: Draft | ((was: Draft) => Draft)) => {
      const previous =
        latest.current.key === key ? latest.current.value : (memory.get(key) ?? EMPTY)
      const next = typeof change === "function" ? change(previous) : change
      versions.current.set(key, (versions.current.get(key) ?? 0) + 1)
      latest.current = { key, value: next }
      // Save independently of React's commit, including when the parent closes this view.
      void writeDraft(key, next).catch((e: Error) =>
        setError(`Draft could not be saved: ${e.message}`)
      )
      setState({ key, value: next })
    },
    [key]
  )
  return [value, update, error] as const
}

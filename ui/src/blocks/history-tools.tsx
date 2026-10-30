import { useEffect, useRef, useState } from "react"
import { useDraft } from "@/lib/drafts"
import type { Session, TranscriptEvent } from "@/lib/sessions"
import { request } from "@/lib/transport"

export function ToolEvent({ event, session }: { event: TranscriptEvent; session: Session }) {
  const [output, setOutput] = useState<string | null>(null)
  const [next, setNext] = useState<number | null>(0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const revision = `${event.call_id}:${event.native_id}:${event.ok}:${event.output}`
  const latest = useRef(revision)
  latest.current = revision
  // biome-ignore lint/correctness/useExhaustiveDependencies: invalidate pages when this tool completes or its retained output changes
  useEffect(() => {
    setOutput(null)
    setNext(0)
    setError(null)
  }, [event.ok, event.output])
  const load = async () => {
    setBusy(true)
    try {
      const params = new URLSearchParams({
        provider: session.provider,
        id: session.id,
        event: String(event.i),
        offset: String(next ?? 0),
      })
      const page = await request<{ text: string; next: number | null }>(
        "GET",
        `/api/session/tool?${params}`
      )
      if (latest.current !== revision) return
      setOutput((was) => (was ?? "") + page.text)
      setNext(page.next)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <details
      data-view-key={`tool:${event.call_id ?? event.native_id ?? event.i}`}
      className="rounded-lg border bg-sunken/40 p-2 text-xs"
    >
      <summary className="cursor-pointer break-words">
        {event.ok === false ? "Failed · " : event.ok ? "Completed · " : "Tool · "}
        {event.text || event.tool}
        {event.exit_code != null && <span> · exit {event.exit_code}</span>}
        {event.duration_ms != null && <span> · {(event.duration_ms / 1000).toFixed(2)}s</span>}
        {event.ts && (
          <time className="ml-2 text-muted-foreground">
            {new Date(event.ts).toLocaleTimeString()}
          </time>
        )}
      </summary>
      <pre className="my-2 max-h-80 overflow-auto whitespace-pre-wrap break-words">
        {output ?? (event.output || "No output recorded.")}
      </pre>
      {next !== null && (
        <button type="button" disabled={busy} className="underline" onClick={() => void load()}>
          {busy ? "Loading…" : output === null ? "Read full output" : "Load more output"}
        </button>
      )}
      {error && <p role="alert">{error}</p>}
    </details>
  )
}

export function HistorySearch({ session }: { session: Session }) {
  const [saved, setSaved] = useDraft(`search:${session.provider}:${session.id}`)
  const query = saved.text
  const setQuery = (text: string) => setSaved((was) => ({ ...was, text }))
  const [context, setContext] = useState<TranscriptEvent[]>([])
  useEffect(() => {
    const find = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
        const input = document.querySelector<HTMLInputElement>("[data-history-search]")
        if (!input) return
        event.preventDefault()
        event.stopPropagation()
        let parent: HTMLElement | null = input
        while (parent) {
          if (parent instanceof HTMLDetailsElement) parent.open = true
          parent = parent.parentElement
        }
        input.focus()
        input.select()
      }
    }
    window.addEventListener("keydown", find, true)
    return () => window.removeEventListener("keydown", find, true)
  }, [])
  const [matches, setMatches] = useState<TranscriptEvent[]>([])
  const [earlier, setEarlier] = useState(0)
  const [first, setFirst] = useState(0)
  const [searched, setSearched] = useState("")
  const [error, setError] = useState<string | null>(null)
  const search = async (older = false) => {
    try {
      const params = new URLSearchParams({
        provider: session.provider,
        id: session.id,
        q: older ? searched : query,
        tools: "1",
        ...(older ? { before: String(first) } : {}),
      })
      const found = await request<{ events: TranscriptEvent[]; earlier: number; first: number }>(
        "GET",
        `/api/session/search?${params}`
      )
      setMatches((was) => (older ? [...found.events, ...was] : found.events))
      setEarlier(found.earlier)
      setFirst(found.first)
      if (!older) setSearched(query)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <details data-view-key="history-search" className="text-xs">
      <summary className="cursor-pointer">Search this conversation</summary>
      <form
        className="mt-2 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          void search()
        }}
      >
        <input
          data-history-search
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search full conversation"
          className="min-w-0 flex-1 rounded border bg-card px-2 py-1"
        />
        <button type="submit">Find</button>
      </form>
      {error && <p role="alert">{error}</p>}
      <ol className="my-2 max-h-80 space-y-3 overflow-auto">
        {matches.map((event) => (
          <li key={event.i} className="rounded border p-2">
            <button
              type="button"
              className="underline"
              onClick={async () => {
                try {
                  const page = await request<{ events: TranscriptEvent[] }>(
                    "GET",
                    `/api/session?${new URLSearchParams({ provider: session.provider, id: session.id, tools: "1", before: String(event.i + 15) })}`
                  )
                  setContext(page.events.filter((e) => Math.abs(e.i - event.i) < 15))
                } catch (e) {
                  setError((e as Error).message)
                }
              }}
            >
              Read surrounding messages
            </button>
            <p className="font-medium">
              {event.kind} · {event.ts ?? ""}
            </p>
            <p className="whitespace-pre-wrap break-words">{event.text}</p>
            {event.output && (
              <pre className="overflow-auto whitespace-pre-wrap">{event.output}</pre>
            )}
          </li>
        ))}
      </ol>
      {earlier > 0 && (
        <button type="button" className="underline" onClick={() => void search(true)}>
          Load {earlier} earlier matches
        </button>
      )}
      {context.length > 0 && (
        <section
          aria-label="Surrounding messages"
          className="max-h-96 space-y-3 overflow-auto rounded border p-2"
        >
          {context.map((event) => (
            <article key={event.i}>
              <strong>{event.kind}</strong>
              <p className="whitespace-pre-wrap">{event.text}</p>
            </article>
          ))}
        </section>
      )}
    </details>
  )
}

import { Loader2 } from "lucide-react"
import { useState } from "react"

import { Eyebrow } from "@/blocks/primitives"
import { SearchBox } from "@/blocks/search-box"
import { useStagedFind } from "@/lib/ax"
import { readHref } from "@/lib/routes"
import { type Hit, KINDS, kindCounts, ofKind } from "@/lib/search"
import type { Provider } from "@/lib/sessions"
import { cn } from "@/lib/utils"

/** Opens a session in VS Code, in its own tab. */
type Open = (provider: Provider, id: string, name: string) => void

const one = (source: string) => KINDS.find((k) => k.kind === source)?.one ?? source

const isProvider = (value: unknown): value is Provider => value === "claude" || value === "codex"

/**
 * One hit. On the web a vault note opens in the reader; in VS Code (`onOpen`) a
 * conversation opens as its session's tab and anything else in the editor, at its line.
 */
function HitRow({ hit, onOpen }: { hit: Hit; onOpen?: Open }) {
  const meta = [hit.handle, hit.date, hit.project, hit.provider].filter(Boolean).join(" · ")
  const body = (
    <>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="label-mono rounded-full bg-muted px-2 text-[10.5px] text-ink-2">
          {one(hit.source)}
        </span>
        {meta && <span className="label-mono text-[11px] text-muted-foreground">{meta}</span>}
      </div>
      <div className="text-[14px] leading-snug font-medium break-words">{hit.title}</div>
      {hit.snippet && (
        <p className="line-clamp-4 text-[13px] leading-relaxed break-words whitespace-pre-line text-ink-2">
          {hit.snippet}
        </p>
      )}
      {!hit.note && (
        <div className="label-mono text-[11px] break-all text-muted-foreground">
          {hit.path}
          {hit.line ? `:${hit.line}` : ""}
        </div>
      )}
    </>
  )
  const row = "block w-full space-y-1 px-5 py-3.5 text-left hover:bg-muted"
  if (onOpen) {
    const { provider, session } = hit
    if (hit.source === "conversation" && session && isProvider(provider))
      return (
        <li>
          <button
            type="button"
            aria-label={`Open the session ${hit.title}`}
            className={row}
            onClick={() => onOpen(provider, session, hit.title)}
          >
            {body}
          </button>
        </li>
      )
    return (
      <li>
        <a href={`${hit.path}${hit.line ? `#L${hit.line}` : ""}`} className={cn(row, "search-hit")}>
          {body}
        </a>
      </li>
    )
  }
  return hit.note ? (
    <li>
      <a href={readHref(hit.note)} className="block space-y-1 px-5 py-3.5 hover:bg-muted">
        {body}
      </a>
    </li>
  ) : (
    <li className="space-y-1 px-5 py-3.5">{body}</li>
  )
}

export function Results({ hits, onOpen }: { hits: Hit[]; onOpen?: Open }) {
  const [kind, setKind] = useState<string | null>(null)
  const chips = kindCounts(hits)
  const shown = ofKind(hits, kind)
  const chip = (active: boolean) =>
    cn(
      "rounded-full px-3 py-1 text-[13px] transition-colors",
      active
        ? "bg-primary-soft font-medium text-primary-ink"
        : "bg-muted text-ink-2 hover:text-foreground"
    )
  return (
    <>
      <fieldset className="flex flex-wrap gap-1.5">
        <legend className="sr-only">Kinds of results</legend>
        <button type="button" className={chip(kind === null)} onClick={() => setKind(null)}>
          All <span className="num">{hits.length}</span>
        </button>
        {chips.map((c) => (
          <button
            key={c.kind}
            type="button"
            aria-pressed={kind === c.kind}
            className={chip(kind === c.kind)}
            onClick={() => setKind(c.kind)}
          >
            {c.label} <span className="num">{c.count}</span>
          </button>
        ))}
      </fieldset>
      <ul className="panel divide-y overflow-hidden">
        {shown.map((hit) => (
          <HitRow key={`${hit.path}:${hit.line ?? ""}`} hit={hit} onOpen={onOpen} />
        ))}
      </ul>
    </>
  )
}

/** `ax find` in the app: past conversations and memories. In VS Code's search
 * tab the query is the tab's own (`onSearch`), and hits open in the editor (`onOpen`). */
export function SearchScreen({
  query,
  onSearch,
  onOpen,
}: {
  query: string
  onSearch?: (query: string) => void
  onOpen?: Open
}) {
  const found = useStagedFind(query || null)
  return (
    <main className="mx-auto max-w-[960px] space-y-4 p-4 md:p-6">
      <header className="space-y-3">
        <div className="space-y-1">
          <Eyebrow>Search</Eyebrow>
          <h1 className="text-[22px] leading-tight">Past conversations and memories</h1>
        </div>
        <SearchBox key={query} initial={query} autoFocus={!query} onSearch={onSearch} />
      </header>
      {!query && (
        <p className="text-sm text-muted-foreground">
          Claude Code's and Codex's past conversations and both tools' memories, by meaning as well
          as words. Press Enter to search.
        </p>
      )}
      {found?.loading && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" /> Searching…
        </p>
      )}
      {found?.error && (
        <div className="panel p-5 text-sm text-muted-foreground">
          The search didn't run: {found.error}
        </div>
      )}
      {found?.refining && (
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground" role="status">
          <Loader2 className="size-3.5 animate-spin" /> Matches by words so far; looking by meaning
          too…
        </p>
      )}
      {found?.partial && (
        <p className="text-[13px] text-muted-foreground">
          Matches by words only: the search by meaning didn't run ({found.partial}).
        </p>
      )}
      {found?.data &&
        (found.data.hits.length ? (
          <Results key={found.data.query} hits={found.data.hits} onOpen={onOpen} />
        ) : found.refining ? null : (
          <p className="text-sm text-muted-foreground">Nothing found for “{found.data.query}”.</p>
        ))}
    </main>
  )
}

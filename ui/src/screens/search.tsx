import { Loader2 } from "lucide-react"
import { useState } from "react"

import { Eyebrow } from "@/blocks/primitives"
import { SearchBox } from "@/blocks/search-box"
import { loadFind, useLoad } from "@/lib/ax"
import { readHref } from "@/lib/routes"
import { type Hit, KINDS, kindCounts, ofKind } from "@/lib/search"
import { cn } from "@/lib/utils"

const one = (source: string) => KINDS.find((k) => k.kind === source)?.one ?? source

function HitRow({ hit }: { hit: Hit }) {
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
        <p
          className={cn(
            "line-clamp-4 text-[13px] leading-relaxed break-words whitespace-pre-line text-ink-2",
            hit.source === "code" && "label-mono text-[12px]"
          )}
        >
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

function Results({ hits }: { hits: Hit[] }) {
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
          <HitRow key={`${hit.path}:${hit.line ?? ""}`} hit={hit} />
        ))}
      </ul>
    </>
  )
}

/** `ax find` in the app: conversations, memories, notes, docs and code. */
export function SearchScreen({ query }: { query: string }) {
  const found = useLoad(query || null, loadFind)
  return (
    <main className="mx-auto max-w-[960px] space-y-4 p-4 md:p-6">
      <header className="space-y-3">
        <div className="space-y-1">
          <Eyebrow>Search</Eyebrow>
          <h1 className="text-[22px] leading-tight">Everything you've worked on</h1>
        </div>
        <SearchBox key={query} initial={query} autoFocus={!query} />
      </header>
      {!query && (
        <p className="text-sm text-muted-foreground">
          Past conversations, both tools' memories, vault notes, and every repository's docs and
          code, by meaning as well as words. Press Enter to search.
        </p>
      )}
      {found.loading && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" /> Searching; this takes a few seconds.
        </p>
      )}
      {found.error && (
        <div className="panel p-5 text-sm text-muted-foreground">
          The search didn't run: {found.error}
        </div>
      )}
      {found.data &&
        (found.data.hits.length ? (
          <Results key={found.data.query} hits={found.data.hits} />
        ) : (
          <p className="text-sm text-muted-foreground">Nothing found for “{found.data.query}”.</p>
        ))}
    </main>
  )
}

import { Activity, ArrowUpRight, Cloud, NotebookPen, Sparkles, TriangleAlert } from "lucide-react"

import { Meter, type Status, StatusBadge } from "@/blocks/primitives"
import type { Card } from "@/lib/sessions"
import { ago } from "@/lib/time"

function badge(card: Card): { status: Status; label: string } {
  if (card.attention) return { status: "warning", label: "Unheard" }
  if (card.status === "failed" || card.status === "ended")
    return { status: "failed", label: "Failed" }
  if (card.stage?.startsWith("paused")) return { status: "warning", label: "Paused" }
  return { status: "running", label: "Running" }
}

/**
 * A job its session waits on, inline in the conversation: only what is still going, and
 * Haiku's last word on it.
 */
export function JobCard({ card }: { card: Card }) {
  const state = badge(card)
  const progress = card.progress
  const facts = [progress.text !== "-" ? progress.text : "", card.eta ?? ""].filter(Boolean)
  const notebook = card.notebook
  return (
    <article
      className="space-y-3 rounded-xl border border-border bg-card p-4"
      aria-label={card.label}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <Activity className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <div className="text-[13.5px] leading-snug font-medium">{card.label}</div>
            <div className="label-mono truncate text-[11px] text-muted-foreground">
              {card.key}
              {card.stage && ` · ${card.stage}`}
            </div>
          </div>
        </div>
        <StatusBadge status={state.status} label={state.label} />
      </header>

      {progress.percent !== null && <Meter value={progress.percent} max={100} />}
      {facts.length > 0 && <div className="text-xs text-muted-foreground">{facts.join(" · ")}</div>}

      {notebook && (
        <div className="space-y-2 rounded-lg bg-sunken/70 px-3 py-2.5">
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="flex min-w-0 items-center gap-1.5">
              <NotebookPen className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate">
                {notebook.cell
                  ? `Cell ${notebook.cell.index}${notebook.cell.label ? ` · ${notebook.cell.label}` : ""}`
                  : "Notebook"}
              </span>
            </span>
            <span className="num shrink-0 text-muted-foreground">
              {notebook.cells.done} of {notebook.cells.total} cells
            </span>
          </div>
          {notebook.cells.total > 0 && (
            <Meter value={notebook.cells.done} max={notebook.cells.total} />
          )}
          {notebook.resources.map((r) => (
            <div key={r.label} className="flex items-center justify-between gap-3 text-xs">
              <span className="flex min-w-0 items-center gap-1.5">
                <Cloud className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="label-mono truncate">{r.label}</span>
                <span className="hidden truncate text-muted-foreground sm:inline">{r.kind}</span>
              </span>
              <span className="label-mono shrink-0 text-ink-2">{r.status}</span>
            </div>
          ))}
        </div>
      )}

      {card.look && (
        <div className="space-y-1 rounded-lg bg-sunken/70 px-3 py-2">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Sparkles className="size-3.5" aria-hidden /> Haiku · {ago(card.look.at)}
          </div>
          <p className="text-[13px] leading-snug text-ink-2">{card.look.summary}</p>
        </div>
      )}

      {card.attention && (
        <div className="flex items-start gap-1.5 text-xs">
          <TriangleAlert className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
          {card.message ? `${card.message}. ` : ""}
          {card.attention}
        </div>
      )}

      <a
        href={card.page}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 text-xs text-primary-ink hover:underline"
      >
        The job's page <ArrowUpRight className="size-3" aria-hidden />
      </a>
    </article>
  )
}

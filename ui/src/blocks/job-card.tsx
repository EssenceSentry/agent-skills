import {
  Activity,
  ArrowUpRight,
  ChevronDown,
  Cloud,
  NotebookPen,
  Sparkles,
  TriangleAlert,
} from "lucide-react"
import { type ReactNode, useContext, useEffect, useId, useRef, useState } from "react"

import { Meter, type Status, StatusBadge } from "@/blocks/primitives"
import { LIVE } from "@/lib/ax"
import { EditorHost } from "@/lib/host"
import { describeJobEvent, detailPath, type JobDetail } from "@/lib/job"
import type { Card } from "@/lib/sessions"
import { ago, clock, every } from "@/lib/time"
import { askExtension, request } from "@/lib/transport"
import { cn } from "@/lib/utils"

function badge(card: Card): { status: Status; label: string } {
  if (card.attention) return { status: "warning", label: "Unheard" }
  if (card.status === "failed" || card.status === "ended")
    return { status: "failed", label: "Failed" }
  if (card.stage?.startsWith("paused")) return { status: "warning", label: "Paused" }
  return { status: "running", label: "Running" }
}

/** The job's details while its card is open, read again every 5 seconds. */
function useDetail(page: string, open: boolean, given: JobDetail | null | undefined) {
  const [detail, setDetail] = useState<JobDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!open || given !== undefined || !LIVE) return
    let current = true
    const load = () =>
      request<JobDetail>("GET", detailPath(page)).then(
        (found) => {
          if (!current) return
          setDetail(found)
          setError(null)
        },
        (e: Error) => current && setError(e.message)
      )
    void load()
    const timer = setInterval(load, 5_000)
    return () => {
      current = false
      clearInterval(timer)
    }
  }, [open, page, given])
  return { detail: given ?? detail, error }
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h4 className="chat-card-heading text-[11.5px] font-medium text-muted-foreground">{title}</h4>
      {children}
    </section>
  )
}

/** What the job's page shows, in the card: times, where it runs, its events, Haiku's looks
 * and its output. */
function Details({ detail, error }: { detail: JobDetail | null; error: string | null }) {
  if (!detail)
    return (
      <p className="text-muted-foreground">
        {error ? `Couldn't read the job: ${error}` : "Reading the job…"}
      </p>
    )
  const facts: [string, ReactNode][] = [
    ["Started", clock(detail.created)],
    ["Updated", ago(detail.updated)],
    ...(detail.eta ? [["Finish", detail.eta.text] as [string, ReactNode]] : []),
    ...(detail.finished ? [["Finished", clock(detail.finished)] as [string, ReactNode]] : []),
    [
      "Source",
      <span key="source" className="label-mono">
        {[detail.kind, detail.ref].filter(Boolean).join(" · ")}
      </span>,
    ],
    ...(detail.check_every
      ? [["Checked", `every ${every(detail.check_every)}`] as [string, ReactNode]]
      : []),
  ]
  return (
    <>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {facts.map(([name, value]) => (
          <div key={name} className="contents">
            <dt className="text-muted-foreground">{name}</dt>
            <dd className="m-0 min-w-0">{value}</dd>
          </div>
        ))}
      </dl>
      {detail.message && <p>{detail.message}</p>}
      {detail.check_error && (
        <p className="text-critical">Last check failed: {detail.check_error}</p>
      )}
      {detail.console_url && (
        <a
          href={detail.console_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-primary-ink hover:underline"
        >
          AWS console <ArrowUpRight className="size-3" aria-hidden />
        </a>
      )}
      {detail.events.length > 0 && (
        <Section title="Events">
          <ol className="space-y-0.5">
            {[...detail.events].reverse().map((event) => (
              <li key={`${event.ts}-${event.type}`} className="flex gap-2">
                <time className="num shrink-0 text-muted-foreground">{clock(event.ts)}</time>
                <span className="min-w-0 [overflow-wrap:anywhere]">{describeJobEvent(event)}</span>
              </li>
            ))}
          </ol>
        </Section>
      )}
      {detail.looks.length > 0 && (
        <Section title="Haiku's looks">
          <ol className="space-y-1.5">
            {detail.looks.map((look) => (
              <li key={look.at} className="space-y-0.5">
                <div className="text-muted-foreground">{ago(look.at)}</div>
                <p className="m-0 text-ink-2">{look.summary || "(no summary)"}</p>
                {look.problem && (
                  <p className="m-0 flex items-start gap-1">
                    <TriangleAlert className="mt-px size-3 shrink-0 text-warning" aria-hidden />
                    {look.problem}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </Section>
      )}
      {detail.log !== undefined && (
        <Section title="Output">
          <pre className="chat-card-log label-mono m-0 max-h-40 overflow-auto rounded-md bg-sunken/70 p-2 text-[11px] whitespace-pre-wrap">
            {detail.log || "(no output yet)"}
          </pre>
        </Section>
      )}
    </>
  )
}

const SHOW_JOB = "ax:show-job"

/** Open the card of the job a link names and bring it into view; false when the page
 * shows no card for that job. */
export function showJob(key: string): boolean {
  const shown = [...document.querySelectorAll<HTMLElement>("[data-job]")].some(
    (card) => card.dataset.job === key
  )
  if (shown) window.dispatchEvent(new CustomEvent(SHOW_JOB, { detail: key }))
  return shown
}

/**
 * A job its session waits on, inline in the conversation: only what is still going, and
 * Haiku's last word on it. It opens in place on the rest of what its page shows, in an
 * area that scrolls, and closes when anything outside it takes the focus. A link to the
 * job's page opens it too.
 */
export function JobCard({
  card,
  open: initially = false,
  detail: given,
}: {
  card: Card
  open?: boolean
  /** The details to show instead of reading them from ax. */
  detail?: JobDetail | null
}) {
  const [open, setOpen] = useState(initially)
  const frame = useRef<HTMLElement>(null)
  const id = useId()
  const { detail, error } = useDetail(card.page, open, given)
  useEffect(() => {
    if (!open) return
    const outside = (e: Event) => {
      if (!frame.current?.contains(e.target as Node)) setOpen(false)
    }
    const away = () => setOpen(false)
    document.addEventListener("pointerdown", outside, true)
    document.addEventListener("focusin", outside, true)
    window.addEventListener("blur", away)
    return () => {
      document.removeEventListener("pointerdown", outside, true)
      document.removeEventListener("focusin", outside, true)
      window.removeEventListener("blur", away)
    }
  }, [open])
  // A link to this job's page opens the card instead, and brings it into view.
  useEffect(() => {
    const show = (e: Event) => {
      if ((e as CustomEvent<string>).detail !== card.key) return
      setOpen(true)
      // Its top at the top of the view: the bottom is the composer's, which stays put.
      requestAnimationFrame(() =>
        frame.current?.scrollIntoView({ block: "start", behavior: "smooth" })
      )
    }
    window.addEventListener(SHOW_JOB, show)
    return () => window.removeEventListener(SHOW_JOB, show)
  }, [card.key])
  const state = badge(card)
  const editor = useContext(EditorHost)
  const at = card.notebook?.cell
  const cellName = at ? `Cell ${at.index}${at.label ? ` · ${at.label}` : ""}` : "Notebook"
  const cellSaid = at ? `cell ${at.index}${at.label ? `, ${at.label}` : ""}` : "its notebook"
  const progress = card.progress
  const facts = [progress.text !== "-" ? progress.text : "", card.eta ?? ""].filter(Boolean)
  const notebook = card.notebook
  return (
    <article
      ref={frame}
      className="chat-card scroll-mt-3 space-y-3 rounded-xl border border-border bg-card p-4"
      aria-label={card.label}
      data-job={card.key}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        title={open ? "Close the job's details" : "Open the job's details"}
        onClick={() => setOpen((was) => !was)}
        className="chat-card-toggle flex w-full flex-wrap items-start justify-between gap-x-3 gap-y-1 text-left"
      >
        {/* In a narrow column the badge drops under the title rather than squeezing it. */}
        <div className="flex min-w-[12rem] flex-1 items-start gap-2.5">
          <Activity className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0">
            <div className="text-[13.5px] leading-snug font-medium">{card.label}</div>
            <div className="label-mono truncate text-[11px] text-muted-foreground">
              {card.key}
              {card.stage && ` · ${card.stage}`}
            </div>
          </div>
        </div>
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          <StatusBadge status={state.status} label={state.label} />
          <ChevronDown
            className={cn(
              "size-4 text-muted-foreground transition-transform",
              open && "rotate-180"
            )}
            aria-hidden
          />
        </span>
      </button>

      {progress.percent !== null && <Meter value={progress.percent} max={100} />}
      {facts.length > 0 && <div className="text-xs text-muted-foreground">{facts.join(" · ")}</div>}

      {notebook && (
        <div className="space-y-2 rounded-lg bg-sunken/70 px-3 py-2.5">
          <div className="flex items-center justify-between gap-3 text-xs">
            {editor && notebook.path ? (
              <button
                type="button"
                className="chat-card-cell flex min-w-0 items-center gap-1.5 rounded text-left hover:underline"
                aria-label={`Open the notebook at ${cellSaid}`}
                title={notebook.path}
                onClick={() =>
                  void askExtension("openNotebook", {
                    path: notebook.path,
                    cell: notebook.cell?.index ?? null,
                  }).catch(() => undefined)
                }
              >
                <NotebookPen className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate">{cellName}</span>
              </button>
            ) : (
              <span className="flex min-w-0 items-center gap-1.5">
                <NotebookPen className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate">{cellName}</span>
              </span>
            )}
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

      {open && (
        <div
          id={id}
          className="chat-card-details max-h-72 space-y-3 overflow-y-auto rounded-lg border bg-sunken/40 p-3 text-xs"
        >
          <Details detail={detail} error={error} />
        </div>
      )}
    </article>
  )
}

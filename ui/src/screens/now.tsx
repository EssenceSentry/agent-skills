import {
  Check,
  CircleCheck,
  Copy,
  ExternalLink,
  FileText,
  Gauge,
  Lightbulb,
  ListTodo,
  Loader2,
  Plus,
  RefreshCcw,
  TriangleAlert,
  Wallet,
  X,
} from "lucide-react"
import { type FormEvent, useMemo, useState } from "react"

import { Meter, SectionHeader, StatusBadge, StatusIcon } from "@/blocks/primitives"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { type ActionName, act, type Budget, type Job, type NowState, type Waiting } from "@/lib/ax"
import { amount, budgetBar, budgetSummary, budgetTone } from "@/lib/budget"
import { readHref } from "@/lib/routes"
import { ago, until } from "@/lib/time"
import { cn } from "@/lib/utils"

const GROUPS: { kind: Waiting["kind"]; title: string }[] = [
  { kind: "job", title: "Jobs that need a look" },
  { kind: "usage", title: "Near a limit" },
  { kind: "budget", title: "Over a budget" },
  { kind: "proposal", title: "Rule proposals" },
  { kind: "review", title: "Rules to review" },
  { kind: "todo", title: "To-dos" },
]

type ActionSpec = {
  label: string
  api: string
  variant: "default" | "outline"
  question: string
  explain: () => string
  model?: string
}

const COMPILE = "It reaches Claude and Codex after you run `ax profile compile --apply`."

const ACTIONS: Record<ActionName, ActionSpec> = {
  accept: {
    label: "Accept",
    api: "accept",
    variant: "default",
    question: "Accept this rule?",
    explain: () => `It becomes an active rule. ${COMPILE}`,
  },
  reject: {
    label: "Reject",
    api: "reject",
    variant: "outline",
    question: "Reject this proposal?",
    explain: () => "Its note is removed. It comes back only if its evidence doubles.",
  },
  keep: {
    label: "Keep",
    api: "keep",
    variant: "default",
    question: "Keep this rule as it is?",
    explain: () => "Keeping it counts as fresh evidence and clears the review flag.",
  },
  retire: {
    label: "Retire",
    api: "retire",
    variant: "outline",
    question: "Retire this rule?",
    explain: () =>
      "Its note stays, marked retired. It stops applying after `ax profile compile --apply`.",
  },
  guard: {
    label: "Guard",
    api: "guard",
    variant: "outline",
    model: "Haiku",
    question: "Try a guard for this rule?",
    explain: () =>
      "Haiku writes a command pattern from the rule's evidence (one model call), then ax tests it on your recent commands. If it passes, it is enforced before shell commands once you run `ax profile compile --apply`.",
  },
  done: {
    label: "Done",
    api: "todo-done",
    variant: "default",
    question: "Mark this to-do done?",
    explain: () => "It closes as done.",
  },
  drop: {
    label: "Drop",
    api: "todo-drop",
    variant: "outline",
    question: "Drop this to-do?",
    explain: () => "It closes as dropped; its note stays.",
  },
}

type Notice = { tone: "ok" | "error"; text: string }

function scopeLabel(scope?: string) {
  if (!scope) return null
  if (scope === "global") return "everywhere"
  return scope.replace(/^(project|repo):/, "")
}

function KindIcon({ item }: { item: Waiting }) {
  const box = "well grid size-8 shrink-0 place-items-center [&_svg]:size-4"
  if (item.kind === "job")
    return (
      <div className={box}>
        <StatusIcon status={item.status === "running" ? "warning" : "failed"} />
      </div>
    )
  const Icon = {
    usage: Gauge,
    budget: Wallet,
    proposal: Lightbulb,
    review: RefreshCcw,
    todo: ListTodo,
  }[item.kind]
  const tone = { usage: "text-warning", budget: "text-critical" }[item.kind as string]
  return (
    <div className={box}>
      <Icon className={tone ?? "text-muted-foreground"} />
    </div>
  )
}

function eyebrow(item: Waiting) {
  if (item.kind === "job") return item.status === "running" ? "Job flagged" : `Job ${item.status}`
  if (item.kind === "todo") return `To-do ${item.id}`
  if (item.kind === "usage") return "Usage"
  if (item.kind === "budget") return "Budget"
  return item.id
}

function WaitingRow({
  item,
  onAction,
}: {
  item: Waiting
  onAction: (item: Waiting, action: ActionName) => void
}) {
  const scope = scopeLabel(item.scope)
  return (
    <li className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start">
      <div className="flex min-w-0 flex-1 gap-3">
        <KindIcon item={item} />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="label-mono truncate text-[11px] text-muted-foreground">
              {eyebrow(item)}
            </span>
            {scope && (
              <span className="label-mono rounded-full bg-muted px-2 text-[10.5px] text-ink-2">
                {scope}
              </span>
            )}
          </div>
          <div className="text-[14px] leading-snug font-medium">{item.title}</div>
          {item.detail && item.kind !== "job" && (
            <p className="line-clamp-3 text-[13px] leading-relaxed whitespace-pre-line text-ink-2">
              {item.detail}
            </p>
          )}
          {item.kind === "job" && item.detail !== item.status && (
            <p className="text-[13px] text-ink-2">{item.detail}</p>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-0.5 text-xs text-muted-foreground">
            {item.origin && <span className="label-mono">from {item.origin}</span>}
            {item.updated && <span>{ago(item.updated)}</span>}
            {item.resets_at && <span>resets {until(item.resets_at)}</span>}
            {item.note && (
              <a
                href={readHref(item.note)}
                className="inline-flex items-center gap-1 hover:text-foreground"
              >
                <FileText className="size-3.5" /> Note
              </a>
            )}
          </div>
        </div>
      </div>
      {item.actions.length > 0 && (
        <div className="flex shrink-0 flex-wrap gap-1.5 pl-11 sm:pl-0">
          {item.actions.map((name) => {
            const spec = ACTIONS[name]
            return (
              <Button
                key={name}
                size="sm"
                variant={spec.variant}
                onClick={() => onAction(item, name)}
              >
                {spec.label}
                {spec.model && (
                  <span className="label-mono rounded bg-muted px-1 text-[10px] text-muted-foreground">
                    {spec.model}
                  </span>
                )}
              </Button>
            )
          })}
        </div>
      )}
    </li>
  )
}

function AddTodo({
  projects,
  onDone,
}: {
  projects: string[]
  onDone: (notice: Notice | null) => void
}) {
  const [text, setText] = useState("")
  const [scope, setScope] = useState("global")
  const [detail, setDetail] = useState("")
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      onDone({ tone: "ok", text: await act("todo-add", { text, scope, detail }) })
    } catch (error) {
      onDone({ tone: "error", text: (error as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2.5 border-b bg-sunken/60 px-5 py-4">
      <Input
        autoFocus
        required
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="What to do, in one line"
        aria-label="To-do"
      />
      <div className="flex flex-col gap-2.5 sm:flex-row">
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          aria-label="Where it belongs"
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm sm:w-56"
        >
          <option value="global">Everywhere</option>
          {projects.map((p) => (
            <option key={p} value={`project:${p}`}>
              {p}
            </option>
          ))}
        </select>
        <Textarea
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          placeholder="Context, links, what done looks like (optional)"
          aria-label="Detail"
          className="min-h-8 flex-1"
          rows={1}
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={() => onDone(null)}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={busy || !text.trim()}>
          {busy ? <Loader2 className="animate-spin" /> : <Plus />} Add to-do
        </Button>
      </div>
    </form>
  )
}

function WaitingPanel({ state, refresh }: { state: NowState; refresh: () => void }) {
  const [pending, setPending] = useState<{ item: Waiting; action: ActionName } | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [adding, setAdding] = useState(false)
  const projects = useMemo(
    () =>
      [
        ...new Set([
          ...state.conversations.map((c) => c.project ?? ""),
          ...state.waiting.flatMap((w) =>
            w.scope?.startsWith("project:") ? [w.scope.slice(8)] : []
          ),
        ]),
      ]
        .filter((p) => /^[A-Za-z0-9._-]+$/.test(p))
        .sort(),
    [state]
  )

  async function confirm() {
    if (!pending) return
    setBusy(true)
    try {
      const said = await act(ACTIONS[pending.action].api, { id: pending.item.id })
      setNotice({ tone: "ok", text: said })
      refresh()
    } catch (error) {
      setNotice({ tone: "error", text: (error as Error).message })
    } finally {
      setBusy(false)
      setPending(null)
    }
  }

  const spec = pending ? ACTIONS[pending.action] : null
  const count = state.waiting.length
  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b px-5 py-4">
        <div className="space-y-1">
          <div className="eyebrow">Waiting for you</div>
          <h1 className="text-[22px] leading-tight">
            {count
              ? `${count} ${count === 1 ? "thing needs" : "things need"} you`
              : "Nothing waits for you"}
          </h1>
        </div>
        <Button size="sm" variant="outline" onClick={() => setAdding((a) => !a)}>
          <Plus /> Add a to-do
        </Button>
      </div>
      {adding && (
        <AddTodo
          projects={projects}
          onDone={(result) => {
            setAdding(false)
            if (result) {
              setNotice(result)
              refresh()
            }
          }}
        />
      )}
      {notice && (
        <div
          role="status"
          className={cn(
            "flex items-start gap-2.5 border-b px-5 py-3 text-[13px]",
            notice.tone === "ok" ? "bg-primary-soft/60" : "bg-critical/[0.07]"
          )}
        >
          {notice.tone === "ok" ? (
            <Check className="mt-0.5 size-4 shrink-0 text-primary" />
          ) : (
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-critical" />
          )}
          <span className="min-w-0 flex-1 break-words whitespace-pre-line">{notice.text}</span>
          <button
            type="button"
            aria-label="Dismiss"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => setNotice(null)}
          >
            <X className="size-4" />
          </button>
        </div>
      )}
      {count === 0 ? (
        <div className="flex items-center gap-2.5 px-5 py-8 text-sm text-muted-foreground">
          <CircleCheck className="size-4 text-good" /> No proposals, flags, failed jobs or open
          to-dos.
        </div>
      ) : (
        GROUPS.map((group) => {
          const items = state.waiting.filter((w) => w.kind === group.kind)
          if (!items.length) return null
          return (
            <div key={group.kind}>
              <div className="flex items-center justify-between border-b bg-sunken/50 px-5 py-1.5">
                <span className="eyebrow">{group.title}</span>
                <span className="label-mono num text-[11px] text-muted-foreground">
                  {items.length}
                </span>
              </div>
              <ul className="divide-y border-b last:border-b-0">
                {items.map((item) => (
                  <WaitingRow
                    key={`${item.kind}:${item.id}`}
                    item={item}
                    onAction={(i, action) => setPending({ item: i, action })}
                  />
                ))}
              </ul>
            </div>
          )
        })
      )}
      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => !open && !busy && setPending(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{spec?.question}</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <span className="block font-medium text-foreground">{pending?.item.title}</span>
              <span className="block">{spec?.explain()}</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <Button onClick={confirm} disabled={busy}>
              {busy && <Loader2 className="animate-spin" />}
              {spec?.label}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

function JobRow({ job }: { job: Job }) {
  const detail = [
    job.progress !== "-" ? job.progress : "",
    job.eta ?? "",
    `updated ${ago(job.updated)}`,
  ]
    .filter(Boolean)
    .join(" · ")
  return (
    <div className="space-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13.5px] leading-snug font-medium">{job.label}</div>
          <div className="label-mono truncate text-[11px] text-muted-foreground">
            {job.key}
            {job.stage && ` · ${job.stage}`}
          </div>
        </div>
        <StatusBadge
          status={job.check_error ? "warning" : "running"}
          label={job.check_error ? "Flagged" : "Running"}
        />
      </div>
      {job.percent !== null && <Meter value={job.percent} max={100} />}
      <div className="text-xs text-muted-foreground">{detail}</div>
      {job.check_error && (
        <div className="flex items-start gap-1.5 text-xs">
          <TriangleAlert className="mt-px size-3.5 shrink-0 text-warning" /> {job.check_error}
        </div>
      )}
      {job.link && (
        <a
          href={job.link}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary-ink hover:underline"
        >
          Its dashboard <ExternalLink className="size-3" />
        </a>
      )}
    </div>
  )
}

const FILL = { primary: "bg-primary", warning: "bg-warning", critical: "bg-critical" }
const TRACK = { primary: "bg-primary-soft", warning: "bg-warning/20", critical: "bg-critical/15" }
const ENTRY = { add: "spent", hold: "held", pass: "passed" }

function BudgetRow({ budget }: { budget: Budget }) {
  const tone = budgetTone(budget)
  const bar = budgetBar(budget)
  const whose = budget.scope?.startsWith("project:")
    ? `for ${budget.scope.slice(8)}`
    : "for its conversation"
  return (
    <div className="space-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13.5px] leading-snug font-medium">{budget.name}</div>
          {budget.why && <div className="text-xs text-ink-2">{budget.why}</div>}
        </div>
        {budget.state !== "ok" && (
          <StatusBadge
            status={budget.state === "over" ? "failed" : "warning"}
            label={budget.state === "over" ? "Over" : "Near"}
          />
        )}
      </div>
      <div
        className={cn("flex h-1.5 w-full overflow-hidden rounded-full", TRACK[tone])}
        role="img"
        aria-label={budgetSummary(budget)}
      >
        <div className={cn("h-full", FILL[tone])} style={{ width: `${bar.spent}%` }} />
        <div
          className={cn("h-full opacity-40", FILL[tone])}
          style={{ width: `${bar.reserved}%` }}
        />
      </div>
      <div className="num text-xs text-ink-2">{budgetSummary(budget)}</div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {budget.owner &&
          (budget.owner_note ? (
            <a href={readHref(budget.owner_note)} className="label-mono hover:text-foreground">
              set by {budget.owner}
            </a>
          ) : (
            <span className="label-mono">set by {budget.owner}</span>
          ))}
        <span>{whose}</span>
        {budget.path && (
          <span className="label-mono truncate" title={budget.path}>
            measures {budget.path.split("/").slice(-2).join("/")}
          </span>
        )}
      </div>
      {budget.entries.length > 0 && (
        <details className="group text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            Ledger · {budget.entries.length}
            {budget.passes > 0 && ` · ${budget.passes} passed with a reason`}
          </summary>
          <ul className="mt-2 space-y-1.5 border-l pl-3">
            {budget.entries.map((e) => (
              <li key={`${e.at}-${e.kind}-${e.ticket ?? e.note}`} className="space-y-0.5">
                <div className="flex flex-wrap gap-x-2 text-ink-2">
                  <span className="num font-medium text-foreground">
                    {ENTRY[e.kind]} {amount(e.amount)}
                  </span>
                  {e.ticket && (
                    <span className="label-mono">
                      {e.ticket} {e.state}
                    </span>
                  )}
                  {e.note && <span>{e.note}</span>}
                </div>
                <div className="text-muted-foreground">
                  {[e.agent, ago(e.at)].filter(Boolean).join(" · ")}
                </div>
                {e.intent && <div className="text-ink-2">Reason: “{e.intent}”</div>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function CopyHandle({ handle }: { handle: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      title="Copy the handle; `ax recall` brings this conversation into another one"
      className="label-mono inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
      onClick={() => {
        navigator.clipboard?.writeText(handle).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
      {handle}
    </button>
  )
}

export function NowScreen({ state, refresh }: { state: NowState; refresh: () => void }) {
  return (
    <main className="mx-auto grid max-w-[1360px] grid-cols-12 gap-4 p-4 md:gap-5 md:p-6">
      {state.errors.length > 0 && (
        <section className="panel col-span-12 flex gap-3 p-4">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" />
          <div className="min-w-0 space-y-1 text-[13px]">
            <div className="font-medium">Some sources could not be read</div>
            {state.errors.map((e) => (
              <div key={e} className="label-mono break-words text-[12px] text-ink-2">
                {e}
              </div>
            ))}
          </div>
        </section>
      )}
      <div className="col-span-12 lg:col-span-7">
        <WaitingPanel state={state} refresh={refresh} />
      </div>
      <div className="col-span-12 flex flex-col gap-4 md:gap-5 lg:col-span-5">
        <section className="panel space-y-4 p-5">
          <SectionHeader
            eyebrow="Jobs"
            title="Running now"
            meta={<span className="label-mono num">{state.jobs.length}</span>}
          />
          {state.jobs.length ? (
            <div className="divide-y">
              {state.jobs.map((job) => (
                <JobRow key={job.key} job={job} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No jobs running.</p>
          )}
        </section>
        {state.budgets.length > 0 && (
          <section className="panel space-y-4 p-5">
            <SectionHeader
              eyebrow="Budgets"
              title="Caps agents keep"
              meta={<span className="label-mono num">{state.budgets.length}</span>}
            />
            <div className="divide-y">
              {state.budgets.map((b) => (
                <BudgetRow key={b.name} budget={b} />
              ))}
            </div>
          </section>
        )}
        <section className="panel space-y-3 p-5">
          <SectionHeader
            eyebrow="Conversations"
            title="Recent, both tools"
            meta={<span>last sync {ago(state.last_sync)}</span>}
          />
          <div className="divide-y">
            {state.conversations.map((c) => (
              <div key={c.handle} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
                <span className="label-mono mt-0.5 w-12 shrink-0 text-[11px] text-muted-foreground">
                  {c.provider === "claude"
                    ? "Claude"
                    : c.provider === "codex"
                      ? "Codex"
                      : c.provider}
                </span>
                <div className="min-w-0 flex-1">
                  <a
                    href={readHref(c.note)}
                    className="line-clamp-2 text-[13.5px] leading-snug font-medium hover:underline"
                  >
                    {c.title}
                  </a>
                  <div className="truncate text-xs text-muted-foreground">
                    {[c.project, ago(c.ended)].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <CopyHandle handle={c.handle} />
              </div>
            ))}
            {!state.conversations.length && (
              <p className="text-sm text-muted-foreground">No conversations archived yet.</p>
            )}
          </div>
        </section>
      </div>
    </main>
  )
}

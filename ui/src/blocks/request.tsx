import {
  Check,
  ChevronDown,
  Columns2,
  FilePen,
  Loader2,
  Save,
  SquareTerminal,
  Wrench,
} from "lucide-react"
import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react"

import { Markdown } from "@/blocks/markdown"
import { Button } from "@/components/ui/button"
import { describeApproval } from "@/lib/approval"
import { EditorHost } from "@/lib/host"
import { openPlanBeside, savePlan } from "@/lib/plan"
import type { Approval } from "@/lib/sessions"
import { cn } from "@/lib/utils"

/*
 * What an agent waits on, in the message box's place, as Codex shows it: a card in the
 * box's own frame with a heading, what it asks about, and its answers at the foot.
 */

export const RECOMMENDED = " (Recommended)"

/** An option's label without the "(Recommended)" the agents append; a badge says it. */
export function plainLabel(label: string): { text: string; recommended: boolean } {
  return label.endsWith(RECOMMENDED)
    ? { text: label.slice(0, -RECOMMENDED.length), recommended: true }
    : { text: label, recommended: false }
}

export function RequestCard({
  label,
  onSubmit,
  onKeyDown,
  children,
}: {
  label: string
  onSubmit: () => void
  onKeyDown?: (e: KeyboardEvent<HTMLFormElement>) => void
  children: ReactNode
}) {
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }
  return (
    <form
      className="chat-request flex flex-col overflow-hidden rounded-3xl border bg-card"
      aria-label={label}
      onSubmit={submit}
      onKeyDown={onKeyDown}
    >
      {children}
    </form>
  )
}

export function RequestHeading({
  icon,
  label,
  title,
  aside,
}: {
  icon?: ReactNode
  label?: string | null
  title: ReactNode
  aside?: ReactNode
}) {
  return (
    <div className="flex items-start gap-2 ps-4 pe-3 pt-4 pb-2">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {label && (
          <div className="chat-request-label flex items-center gap-1.5 text-[12px] text-muted-foreground [&_svg]:size-3.5">
            {icon}
            <span className="truncate">{label}</span>
          </div>
        )}
        <div className="chat-request-title text-[13.5px] leading-5 font-medium">{title}</div>
      </div>
      {aside}
    </div>
  )
}

/** A key that answers, shown on its button as Codex shows it. */
export function Key({ children }: { children: ReactNode }) {
  return (
    <kbd className="chat-key inline-flex h-4 min-w-4 items-center justify-center rounded-md bg-current/10 px-1 font-sans text-[11px] leading-4">
      {children}
    </kbd>
  )
}

export function RequestFooter({ children }: { children: ReactNode }) {
  // In a narrow column the buttons wrap rather than run off the card's left edge.
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 px-4 pt-2 pb-4">{children}</div>
  )
}

/** The round buttons at a request's foot: the answer it expects, solid; the others plain. */
export function Pill({
  kind,
  children,
  ...props
}: { kind: "primary" | "outline" | "ghost" } & React.ComponentProps<typeof Button>) {
  return (
    <Button
      size="sm"
      variant={kind === "primary" ? "default" : kind}
      className={cn("chat-pill h-7 gap-1.5 rounded-full px-3", `chat-pill-${kind}`)}
      {...props}
    >
      {children}
    </Button>
  )
}

/** One answer to choose: a number (or a box, for several), its words and what they mean. */
export function ChoiceRow({
  type,
  name,
  number,
  checked,
  disabled,
  onChoose,
  label,
  description,
}: {
  type: "radio" | "checkbox"
  name: string
  number: number
  checked: boolean
  disabled?: boolean
  onChoose: () => void
  label: string
  description?: string | null
}) {
  const shown = plainLabel(label)
  return (
    <label
      data-checked={checked || undefined}
      className="chat-choice flex min-h-8 w-full cursor-pointer items-center gap-2 rounded-xl px-2 py-1.5 text-start text-[13px] hover:bg-muted has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring/50 data-[checked]:bg-muted"
    >
      <input
        type={type}
        name={name}
        checked={checked}
        disabled={disabled}
        onChange={onChoose}
        className="sr-only"
      />
      <ChoiceMark type={type} number={number} checked={checked} />
      <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{shown.text}</span>
          {shown.recommended && (
            <span className="chat-recommended shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
              Recommended
            </span>
          )}
        </span>
        {description && (
          <span className="chat-choice-note min-w-0 text-muted-foreground [overflow-wrap:anywhere]">
            {description}
          </span>
        )}
      </span>
    </label>
  )
}

export function ChoiceMark({
  type,
  number,
  checked,
}: {
  type: "radio" | "checkbox" | "text"
  number: number
  checked: boolean
}) {
  return (
    <span
      aria-hidden
      data-checked={checked || undefined}
      className="chat-choice-mark flex size-5 shrink-0 items-center justify-center rounded-[5px] border bg-muted text-[11px] leading-none font-medium text-muted-foreground data-[checked]:border-foreground data-[checked]:bg-foreground data-[checked]:text-background"
    >
      {type === "checkbox" ? checked && <Check className="size-3.5" /> : number}
    </span>
  )
}

/** Focus the answer a request expects, unless the user is typing somewhere. */
function useOfferedFocus() {
  const button = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const at = document.activeElement
    const typing = at?.closest("input, textarea, [contenteditable]:not([contenteditable='false'])")
    if (!typing) button.current?.focus()
  }, [])
  return button
}

const LABEL_ICON: Record<string, ReactNode> = {
  Terminal: <SquareTerminal aria-hidden />,
  "Edit files": <FilePen aria-hidden />,
}

/** An action it waits to be allowed: the command or files, why it asks, and two answers. */
export function ApprovalPanel({
  approval,
  provider,
  busy = false,
  onAnswer,
}: {
  approval: Approval
  provider: string
  busy?: boolean
  onAnswer: (allow: boolean, response?: Record<string, unknown>) => void
}) {
  const asked = describeApproval(approval, provider)
  const input = (() => {
    try {
      return JSON.parse(approval.detail ?? "{}") as Record<string, unknown>
    } catch {
      return {}
    }
  })()
  const editable = provider === "claude" && typeof (input.new_string ?? input.content) === "string"
  const field = "new_string" in input ? "new_string" : "content"
  const [replacement, setReplacement] = useState(String(input[field] ?? ""))
  const allow = useOfferedFocus()
  const onEscape = (e: KeyboardEvent<HTMLFormElement>) => {
    if (e.key === "Escape" && !busy) {
      e.preventDefault()
      onAnswer(false)
    }
  }
  const shown = asked.command ?? [asked.files.join("\n"), asked.detail].filter(Boolean).join("\n\n")
  return (
    <RequestCard
      label="Approval"
      onSubmit={() =>
        !busy &&
        onAnswer(
          true,
          editable
            ? { updatedInput: { ...input, _patch: undefined, [field]: replacement } }
            : undefined
        )
      }
      onKeyDown={onEscape}
    >
      <RequestHeading
        icon={LABEL_ICON[asked.label] ?? <Wrench aria-hidden />}
        label={asked.label}
        title={asked.title}
      />
      {(shown || approval.reason) && (
        <div className="flex flex-col gap-2 px-4 pb-1">
          {shown && (
            <pre className="chat-command label-mono max-h-80 overflow-auto rounded-md bg-muted px-2.5 py-2 text-[12px] font-medium [overflow-wrap:anywhere] whitespace-pre-wrap">
              {shown}
            </pre>
          )}
          {approval.reason && (
            <dl className="flex min-w-0 items-baseline gap-2 text-[12.5px]">
              <dt className="shrink-0 text-muted-foreground">Reason</dt>
              <dd className="m-0 min-w-0 [overflow-wrap:anywhere]">{approval.reason}</dd>
            </dl>
          )}
        </div>
      )}
      {editable && (
        <label className="mx-4 text-xs text-muted-foreground">
          Edit proposed replacement
          <textarea
            className="mt-1 block max-h-60 w-full rounded border bg-background p-2 font-mono text-xs"
            value={replacement}
            onChange={(e) => setReplacement(e.target.value)}
          />
        </label>
      )}
      <RequestFooter>
        <Pill kind="outline" type="button" disabled={busy} onClick={() => onAnswer(false)}>
          Deny <Key>Esc</Key>
        </Pill>
        <Pill kind="primary" ref={allow} type="submit" disabled={busy}>
          {busy && <Loader2 className="animate-spin" />}
          Allow once <Key>⏎</Key>
        </Pill>
      </RequestFooter>
    </RequestCard>
  )
}

const PLAN_TOOL =
  "grid size-6 place-items-center rounded-md hover:bg-muted hover:text-foreground [&_svg]:size-3.5"

/**
 * The plan, folded to its first lines until opened, as Codex shows one. It also opens as
 * a Markdown tab beside the session's, in VS Code, and saves as a Markdown file.
 */
function PlanBox({ plan, cwd }: { plan: string; cwd?: string | null }) {
  const editor = useContext(EditorHost)
  const [open, setOpen] = useState(false)
  const [saved, setSaved] = useState(false)
  const save = () =>
    savePlan(plan, { editor, cwd }).then(
      (where) => {
        if (!where) return
        setSaved(true)
        setTimeout(() => setSaved(false), 1500)
      },
      () => undefined
    )
  return (
    <div className="chat-plan-box relative mx-4 overflow-hidden rounded-xl border">
      <div className="chat-plan-head flex h-9 items-center justify-between gap-2 px-3 text-[12px] text-muted-foreground">
        <span className="font-medium">Plan</span>
        <div className="flex items-center gap-1">
          {editor && (
            <button
              type="button"
              className={PLAN_TOOL}
              aria-label="Open the plan to the side"
              title="Open to the side, as Markdown"
              onClick={() => void openPlanBeside(plan, cwd).catch(() => undefined)}
            >
              <Columns2 />
            </button>
          )}
          <button
            type="button"
            className={PLAN_TOOL}
            aria-label="Save the plan"
            title={saved ? "Saved" : editor ? "Save as a Markdown file" : "Download as Markdown"}
            onClick={() => void save()}
          >
            {saved ? <Check /> : <Save />}
          </button>
          {/* Folded, it opens from where it fades; opened, it folds from here. */}
          {open && (
            <button
              type="button"
              className="ms-1 flex items-center gap-1 hover:text-foreground"
              aria-expanded
              onClick={() => setOpen(false)}
            >
              Collapse
              <ChevronDown className="size-3.5 rotate-180" />
            </button>
          )}
        </div>
      </div>
      <div
        className={cn("px-3 pb-3", open ? "max-h-96 overflow-auto" : "max-h-40 overflow-hidden")}
      >
        <Markdown className="text-[13px] leading-relaxed">{plan}</Markdown>
      </div>
      {!open && (
        <div className="chat-plan-fade pointer-events-none absolute inset-x-0 bottom-0 flex h-20 items-end justify-center bg-gradient-to-t from-card to-transparent pb-2">
          <button
            type="button"
            className="chat-pill-outline pointer-events-auto rounded-full border bg-card px-3 py-1 text-[12px]"
            aria-expanded={false}
            onClick={() => setOpen(true)}
          >
            Expand plan
          </button>
        </div>
      )}
    </div>
  )
}

/** A plan waiting for the go-ahead: yes, or no and what to do differently. */
export function PlanPanel({
  plan,
  provider,
  cwd,
  busy = false,
  onAnswer,
}: {
  plan: string
  provider: string
  /** The session's folder, where saving the plan starts. */
  cwd?: string | null
  busy?: boolean
  onAnswer: (allow: boolean, message?: string) => void
}) {
  const actor = provider === "codex" ? "Codex" : "Claude"
  const [choice, setChoice] = useState<"yes" | "no">("yes")
  const [words, setWords] = useState("")
  const submit = () => {
    if (busy) return
    if (choice === "yes") onAnswer(true)
    else if (words.trim()) onAnswer(false, words.trim())
  }
  return (
    <RequestCard label="Plan" onSubmit={submit}>
      <RequestHeading title="Implement this plan?" />
      <PlanBox plan={plan} cwd={cwd} />
      <div className="flex flex-col gap-1 px-2 pt-2">
        <ChoiceRow
          type="radio"
          name="plan"
          number={1}
          checked={choice === "yes"}
          disabled={busy}
          onChoose={() => setChoice("yes")}
          label="Yes, implement this plan"
        />
        <label
          data-checked={choice === "no" || undefined}
          className="chat-choice flex min-h-8 w-full items-center gap-2 rounded-xl px-2 py-1.5 text-[13px] focus-within:bg-muted hover:bg-muted data-[checked]:bg-muted"
        >
          <ChoiceMark type="radio" number={2} checked={choice === "no"} />
          <input
            type="text"
            value={words}
            disabled={busy}
            onFocus={() => setChoice("no")}
            onChange={(e) => {
              setWords(e.target.value)
              setChoice("no")
            }}
            placeholder={`No, and tell ${actor} what to do differently`}
            aria-label={`What ${actor} should do differently`}
            className="chat-freeform min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
          />
        </label>
      </div>
      <RequestFooter>
        <Pill kind="primary" type="submit" disabled={busy || (choice === "no" && !words.trim())}>
          {busy && <Loader2 className="animate-spin" />}
          Submit <Key>⏎</Key>
        </Pill>
      </RequestFooter>
    </RequestCard>
  )
}

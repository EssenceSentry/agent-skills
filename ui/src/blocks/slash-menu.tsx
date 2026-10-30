import { Box, Lightbulb, Loader2, ShieldCheck, SquareSlash, Target } from "lucide-react"
import { Fragment, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react"

import { useSlashOffers } from "@/lib/ax"
import { type Ranked, rankSlash, type SlashItem, slashQuery } from "@/lib/slash"
import { cn } from "@/lib/utils"

const ICONS = {
  goal: Target,
  plan: Lightbulb,
  auto: ShieldCheck,
  command: SquareSlash,
  skill: Box,
}

export type SlashRow = {
  key: string
  title: string
  description: string
  /** Where a skill comes from: Personal, Project. */
  scope?: string | null
  /** The places in the title that match what is typed, shown in bold. */
  marks: number[]
  icon: keyof typeof ICONS
}

/** The title with each run of matched letters in bold. */
function Marked({ text, marks }: { text: string; marks: number[] }) {
  const marked = new Set(marks)
  const runs: ReactNode[] = []
  let i = 0
  while (i < text.length) {
    const bold = marked.has(i)
    let j = i
    while (j < text.length && marked.has(j) === bold) j++
    const part = text.slice(i, j)
    runs.push(bold ? <strong key={i}>{part}</strong> : <Fragment key={i}>{part}</Fragment>)
    i = j
  }
  return <>{runs}</>
}

/**
 * The menu over the message box while it holds a slash, as Codex's: its commands, then
 * its skills under their heading, the letters typed in bold, the one Enter picks
 * highlighted. `active` counts rows across the sections.
 */
export function SlashMenu({
  sections,
  active,
  onPick,
  onHover,
  note,
}: {
  sections: { label: string | null; rows: SlashRow[] }[]
  active: number
  onPick: (n: number) => void
  onHover: (n: number) => void
  /** Said under the rows: still asking the tool, or why it couldn't answer. */
  note?: string | null
}) {
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    list.current?.querySelector(`[data-row="${active}"]`)?.scrollIntoView({ block: "nearest" })
  }, [active])
  let n = 0
  return (
    <div
      ref={list}
      role="listbox"
      aria-label="Commands and skills"
      className="chat-slash max-h-80 overflow-y-auto rounded-xl border bg-card p-1.5"
    >
      {sections.map((section) =>
        section.rows.length ? (
          <div key={section.label ?? "commands"}>
            {section.label && (
              <div className="chat-slash-heading px-2.5 pt-2 pb-1 text-[12px] text-muted-foreground">
                {section.label}
              </div>
            )}
            {section.rows.map((row) => {
              const at = n++
              const Icon = ICONS[row.icon]
              return (
                <div
                  key={row.key}
                  role="option"
                  aria-selected={at === active}
                  data-row={at}
                  tabIndex={-1}
                  className={cn(
                    "chat-slash-row flex cursor-default items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px]",
                    at === active && "bg-muted"
                  )}
                  onMouseMove={() => at !== active && onHover(at)}
                  onMouseDown={(e) => {
                    e.preventDefault() // the box keeps the focus
                    onPick(at)
                  }}
                >
                  <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="shrink-0">
                    <Marked text={row.title} marks={row.marks} />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">
                    {row.description}
                  </span>
                  {row.scope && (
                    <span className="shrink-0 text-[12px] text-muted-foreground">{row.scope}</span>
                  )}
                </div>
              )
            })}
          </div>
        ) : null
      )}
      {note && (
        <p className="m-0 flex items-center gap-1.5 px-2.5 py-1.5 text-[12px] text-muted-foreground">
          {note.endsWith("…") && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
          {note}
        </p>
      )}
    </div>
  )
}

/** One of ax's own commands in the / menu: a mode, or the goal. */
export type SlashAction = {
  name: string
  title: string
  description: string
  icon: "goal" | "plan" | "auto"
  run: () => void
}

function slashRow({ item, marks }: Ranked<SlashAction | SlashItem>, skill: boolean): SlashRow {
  if ("run" in item)
    return {
      key: `ax:${item.name}`,
      title: item.title,
      description: item.description,
      marks,
      icon: item.icon,
    }
  return {
    key: `${skill ? "skill" : "command"}:${item.name}`,
    title: item.title,
    description: item.description,
    scope: item.scope,
    marks,
    icon: skill ? "skill" : "command",
  }
}

/**
 * The / menu of a message box, as Codex's, for a session's box and for the one that
 * starts a session alike: ax's own commands, then the tool's commands and skills,
 * filtered by what follows the slash. Arrows move, Enter or Tab picks, and Escape shuts
 * it until the text changes. `onKey` takes the box's keys first and says whether it used
 * one; `menu` goes above the box.
 */
export function useSlash({
  text,
  setText,
  provider,
  cwd,
  actions,
  focus,
  off = false,
  execute,
}: {
  execute?: (action: string) => void
  text: string
  setText: (text: string) => void
  provider: string
  cwd: string | null
  actions: SlashAction[]
  /** The box takes the focus back after a pick. */
  focus: () => void
  /** No menu, as while a goal is being typed. */
  off?: boolean
}): { open: boolean; menu: ReactNode; onKey: (e: KeyboardEvent<HTMLTextAreaElement>) => boolean } {
  const query = off ? null : slashQuery(text)
  const [shut, setShut] = useState<string | null>(null)
  const open = query !== null && shut !== text
  const offers = useSlashOffers(provider, cwd, open)
  const [active, setActive] = useState(0)
  // biome-ignore lint/correctness/useExhaustiveDependencies: back to the top when the query changes
  useEffect(() => setActive(0), [query])
  const builtins: SlashItem[] = execute
    ? [
        ["compact", "Compact conversation context"],
        ["review", "Review workspace changes"],
        ["fork", "Fork this conversation"],
        ["archive", "Archive this conversation"],
        ["history", "Search the full conversation"],
        ["session", "Manage this conversation"],
      ].map(([name, description]) => ({
        name,
        description,
        title: `/${name}`,
        action: name,
        insert: `/${name}`,
        hint: "",
        scope: "ax",
      }))
    : []
  const commandHits = rankSlash<SlashAction | SlashItem>(
    [
      ...actions,
      ...builtins,
      ...(offers.data?.commands ?? []).filter(
        (c) => (!c.action || execute) && !builtins.some((b) => b.name === c.name)
      ),
    ],
    query ?? ""
  )
  const skillHits = rankSlash<SlashItem>(offers.data?.skills ?? [], query ?? "")
  const picks = [...commandHits, ...skillHits]
  const at = Math.min(active, Math.max(picks.length - 1, 0))
  const tool = provider === "codex" ? "Codex" : "Claude"
  const note = offers.loading
    ? `Asking ${tool} for its commands…`
    : offers.data?.error
      ? `${tool} didn't say what it offers: ${offers.data.error}`
      : picks.length
        ? null
        : `Nothing matches /${query}`
  const pick = (n: number) => {
    const chosen = picks[n]?.item
    if (!chosen) return
    if ("run" in chosen) {
      setText("")
      chosen.run()
    } else if (chosen.action && execute) {
      setText("")
      execute(chosen.action)
    } else setText(chosen.insert)
    setActive(0)
    setTimeout(focus, 0)
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!open) return false
    if (e.key === "Escape") {
      e.preventDefault()
      setShut(text)
      return true
    }
    if (picks.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault()
      const step = e.key === "ArrowDown" ? 1 : picks.length - 1
      setActive((at + step) % picks.length)
      return true
    }
    const enter = e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing
    if (picks.length && (enter || e.key === "Tab")) {
      e.preventDefault()
      pick(at)
      return true
    }
    return false
  }
  const menu = open ? (
    <SlashMenu
      sections={[
        { label: null, rows: commandHits.map((hit) => slashRow(hit, false)) },
        { label: "Skills", rows: skillHits.map((hit) => slashRow(hit, true)) },
      ]}
      active={at}
      onPick={pick}
      onHover={setActive}
      note={note}
    />
  ) : null
  return { open, menu, onKey }
}

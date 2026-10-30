import {
  ArrowUp,
  BellDot,
  ChevronRight,
  Columns2,
  GitCompareArrows,
  Loader2,
  Target,
  X,
} from "lucide-react"
import { type KeyboardEvent, type ReactNode, useContext, useEffect, useRef, useState } from "react"

import { ModeChips, PlusMenu, ReferenceTray } from "@/blocks/composer-tools"
import { ContextPicker } from "@/blocks/context-picker"
import { FolderPicker } from "@/blocks/folder-picker"
import { PictureTray, usePictures } from "@/blocks/message-input"
import { ModelEffortPicker } from "@/blocks/model-picker"
import { useSlash } from "@/blocks/slash-menu"
import { StaleNote } from "@/blocks/stale-note"
import { MARK, UsageDetails } from "@/blocks/usage-band"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { chatAct, useModels, useSessions, useUsage } from "@/lib/ax"
import { useDraft } from "@/lib/drafts"
import { EditorHost } from "@/lib/host"
import { type ModelPick, startingPick } from "@/lib/models"
import { folderChoices, keptOrder, type PanelRow, panelRows, rowKey, unanswered } from "@/lib/panel"
import { mergeReferences, type Reference, withReferences } from "@/lib/plus"
import type { ChatSettings, Provider, Session } from "@/lib/sessions"
import { askExtension } from "@/lib/transport"
import { toolName, usageSummary } from "@/lib/usage"
import { cn } from "@/lib/utils"

const SHOWN = 8

type Open = (provider: Provider, id: string, name: string, beside: boolean) => void
type Changes = (provider: Provider, id: string, name: string) => void

function StateMark({ state }: { state: PanelRow["state"] }) {
  if (state === "waiting")
    return <BellDot className="chat-panel-waiting size-3.5 shrink-0 text-warning" aria-hidden />
  if (state === "working")
    return <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
  return <span className="size-3.5 shrink-0" aria-hidden />
}

/**
 * A session's row: a link to it on the web page, the one open marked; in VS Code a button
 * opening its tab, with its changes and a tab beside it on hover.
 */
function Row({
  row,
  project,
  href,
  current,
  onOpen,
  onChanges,
}: {
  row: PanelRow
  /** Its project, when it isn't the workspace's own. */
  project: string | null
  href?: string
  current: boolean
  onOpen?: Open
  onChanges?: Changes
}) {
  const editor = useContext(EditorHost)
  const body = (
    <>
      <StateMark state={row.state} />
      {/* The tool by its mark in VS Code, which has the marks' font; by name elsewhere. */}
      <span className="ax-mark chat-panel-mark shrink-0 text-[13px]" title={row.tool} aria-hidden>
        {MARK[row.provider]}
      </span>
      {/* The name keeps the room: the project gives way first, and in a narrow panel the
          project and time hide (look.css). On hover the row's buttons take their place. */}
      <span className="min-w-[3rem] truncate">{row.name}</span>
      <span className="chat-panel-tool-name shrink-0 text-xs text-muted-foreground">
        {toolName(row.provider)}
      </span>
      {project && (
        <span className="chat-panel-project max-w-[45%] min-w-0 shrink-[4] truncate text-xs text-muted-foreground">
          {project}
        </span>
      )}
      <span className="chat-panel-when ml-auto shrink-0 text-xs text-muted-foreground">
        {row.when}
      </span>
    </>
  )
  const title = [row.tool, row.project, row.status].filter(Boolean).join(" · ")
  const actions = editor && (onChanges || onOpen)
  const look = cn(
    "flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left text-[13px]",
    actions && "chat-panel-roomy"
  )
  return (
    <li
      className="chat-panel-row group relative flex items-center rounded-lg hover:bg-muted"
      data-current={current || undefined}
    >
      {href ? (
        <a aria-current={current ? "page" : undefined} href={href} className={look} title={title}>
          {body}
        </a>
      ) : (
        <button
          type="button"
          className={look}
          title={title}
          onClick={() => onOpen?.(row.provider, row.id, row.name, false)}
        >
          {body}
        </button>
      )}
      {actions && (
        <span className="chat-panel-actions absolute right-1 hidden items-center gap-0.5 group-focus-within:flex group-hover:flex">
          {onChanges && (
            <Button
              size="icon"
              variant="ghost"
              className="size-6"
              aria-label={`Show what ${row.name} changed this turn`}
              title="Show changes this turn"
              onClick={() => onChanges(row.provider, row.id, row.name)}
            >
              <GitCompareArrows className="size-3.5" />
            </Button>
          )}
          {onOpen && (
            <Button
              size="icon"
              variant="ghost"
              className="size-6"
              aria-label={`Open ${row.name} to the side`}
              title="Open to the side"
              onClick={() => onOpen(row.provider, row.id, row.name, true)}
            >
              <Columns2 className="size-3.5" />
            </Button>
          )}
        </span>
      )}
    </li>
  )
}

/**
 * The box a session starts from, as Codex's panel has it: the + menu, the modes, the
 * model picker over both tools and a round send, and the folder under it. A started
 * session opens in its own tab.
 */
function StartBox({
  folders,
  sessions,
  onStarted,
}: {
  folders: string[]
  sessions: Session[]
  onStarted: (provider: Provider, id: string, name: string) => void
}) {
  const editor = useContext(EditorHost)
  const groups = useModels()
  const [chosenPick, setPick] = useState<ModelPick | null>(null)
  const pick = chosenPick ?? startingPick(groups)
  const [chosenFolder, setFolder] = useState<string | null>(folders[0] ?? null)
  const folder = chosenFolder ?? folderChoices(folders, sessions, "").recent[0]?.path ?? ""
  const [draft, setDraft, draftError] = useDraft(`new:panel:${folder}`)
  const text = draft.text
  const setText = (text: string) => setDraft((was) => ({ ...was, text }))
  const refs = draft.refs
  const setRefs = (change: Reference[] | ((was: Reference[]) => Reference[])) =>
    setDraft((was) => ({ ...was, refs: typeof change === "function" ? change(was.refs) : change }))
  const [modes, setModes] = useState({ plan: false, auto: false })
  const [goal, setGoal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pictures = usePictures(setError, {
    pictures: draft.pictures,
    set: (change) =>
      setDraft((was) => ({
        ...was,
        pictures: typeof change === "function" ? change(was.pictures) : change,
      })),
  })
  const box = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const settings: ChatSettings = { ...modes, model: pick.model, effort: pick.effort }

  // "New Session" in VS Code brings the cursor here.
  useEffect(() => {
    const focus = (e: MessageEvent) => {
      if ((e.data as { type?: string } | null)?.type === "focusComposer") input.current?.focus()
    }
    window.addEventListener("message", focus)
    return () => window.removeEventListener("message", focus)
  }, [])

  const ready =
    Boolean(folder.trim()) &&
    (text.trim().length > 0 || pictures.pictures.length > 0 || refs.length > 0) &&
    !busy
  async function start() {
    if (!ready) return
    setBusy(true)
    setError(null)
    const sentDraft = draft
    try {
      const payload = {
        action: "start",
        provider: pick.provider,
        cwd: folder.trim(),
        text: withReferences(text, refs).trim(),
        images: pictures.payload(),
        model: pick.model,
        effort: pick.effort,
        plan: modes.plan,
        auto: modes.auto,
        goal,
      }
      const signature = JSON.stringify(payload)
      const start =
        draft.start?.signature === signature ? draft.start : { signature, id: crypto.randomUUID() }
      setDraft((was) => ({ ...was, start }))
      const said = await chatAct({ ...payload, client_message_id: start.id })
      const id = (said as { id?: string }).id
      if (!id) throw new Error(said.message ?? "ax started nothing")
      setDraft((was) =>
        was.text === sentDraft.text &&
        was.refs === sentDraft.refs &&
        was.pictures === sentDraft.pictures
          ? { ...was, text: "", refs: [], pictures: [], start: undefined }
          : was
      )
      setGoal(false)
      onStarted(pick.provider, id, text.trim().split("\n")[0]?.slice(0, 60) || "New session")
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const add = (found: Reference[]) => setRefs((was) => mergeReferences(was, found))
  // The same / menu as a session's box: the modes it starts in, the goal, and the
  // commands and skills of the tool and folder it starts in.
  const slash = useSlash({
    text,
    setText,
    provider: pick.provider,
    cwd: folder || null,
    off: goal,
    focus: () => input.current?.focus(),
    actions: [
      {
        name: "goal",
        title: "Goal",
        description: "Start on a goal to keep pursuing",
        icon: "goal",
        run: () => setGoal(true),
      },
      {
        name: "plan",
        title: "Plan mode",
        description: modes.plan ? "Start without plan mode" : "Start in plan mode",
        icon: "plan",
        run: () => setModes((was) => ({ ...was, plan: !was.plan })),
      },
      {
        name: "approve",
        title: "Approve for me",
        description: modes.auto ? "Ask before its actions" : "Approve its actions for you",
        icon: "auto",
        run: () => setModes((was) => ({ ...was, auto: !was.auto })),
      },
    ],
  })
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (slash.onKey(e)) return
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void start()
    }
  }

  return (
    <div className="chat-panel-foot shrink-0 space-y-1.5 px-3 pt-2 pb-3">
      {slash.menu}
      <div
        ref={box}
        className="chat-box rounded-xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring/40"
      >
        {goal && (
          <button
            type="button"
            className="chat-chip chat-goal-chip"
            aria-label="Goal: cancel"
            title="It starts on this goal and keeps pursuing it. Click to send a plain message."
            onClick={() => setGoal(false)}
          >
            <Target /> Goal <X />
          </button>
        )}
        <PictureTray pictures={pictures.pictures} onRemove={pictures.remove} />
        <ReferenceTray
          refs={refs}
          onRemove={(i) => setRefs((was) => was.filter((_, j) => j !== i))}
        />
        <div className="flex items-end gap-2">
          <PlusMenu
            box={box}
            settings={settings}
            disabled={busy}
            onFiles={
              editor
                ? () =>
                    askExtension<Reference[]>("pickFiles").then(add, (e: Error) =>
                      setError(e.message)
                    )
                : undefined
            }
            onSelection={
              editor
                ? () =>
                    askExtension<Reference | null>("selection").then(
                      (found) =>
                        found ? add([found]) : setError("Select some code in an editor first."),
                      (e: Error) => setError(e.message)
                    )
                : undefined
            }
            onPictures={(files) => void pictures.attach(files)}
            onChange={(c) => setModes((was) => ({ ...was, ...c }))}
            onGoal={() => {
              setGoal(true)
              setTimeout(() => input.current?.focus(), 0)
            }}
          />
          <ModeChips
            settings={settings}
            disabled={busy}
            onChange={(c) => setModes((was) => ({ ...was, ...c }))}
          />
          <Textarea
            ref={input}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onPaste={pictures.onPaste}
            onKeyDown={onKey}
            placeholder={goal ? "What should it keep working toward?" : "Start a session…"}
            aria-label="First message"
            rows={2}
            className="chat-input max-h-48 min-h-10 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
          />
          {groups.length > 0 && (
            <ModelEffortPicker groups={groups} pick={pick} onPick={setPick} disabled={busy} />
          )}
          <Button
            size="icon"
            aria-label="Start the session"
            title="Start (Enter)"
            className="chat-send"
            onClick={() => void start()}
            disabled={!ready}
          >
            {busy ? <Loader2 className="animate-spin" /> : <ArrowUp />}
          </Button>
        </div>
      </div>
      <FolderPicker
        folder={folder}
        workspace={folders}
        sessions={sessions}
        onChange={setFolder}
        onChoose={
          editor ? () => askExtension<string | null>("pickFolder").catch(() => null) : undefined
        }
        disabled={busy}
      />
      <ContextPicker text={text} setText={setText} cwd={folder} add={add} />
      {draftError && <p className="px-1 text-xs text-critical">{draftError}</p>}
      {error && <p className="px-1 text-xs text-critical">{error}</p>}
      {error?.includes("already starting") && (
        <button
          type="button"
          className="text-xs underline"
          onClick={() => {
            setDraft((was) => ({ ...was, start: undefined }))
            setError(null)
          }}
        >
          Use a new start ID (may create a duplicate chat)
        </button>
      )}
    </div>
  )
}

type Usage = NonNullable<ReturnType<typeof useUsage>>

const TONE = { primary: "", warning: "text-warning", critical: "text-critical" } as const
const FOLD_KEY = "ax.panel.usageFolded"

/** Whether the usage is folded, as this viewer left it; open until they fold it. */
function useFolded(): [boolean, () => void] {
  const [folded, setFolded] = useState(() => {
    try {
      return window.localStorage.getItem(FOLD_KEY) === "1"
    } catch {
      return false
    }
  })
  const toggle = () =>
    setFolded((was) => {
      try {
        window.localStorage.setItem(FOLD_KEY, was ? "0" : "1")
      } catch {
        // The choice holds for this visit only.
      }
      return !was
    })
  return [folded, toggle]
}

/**
 * Both tools' usage under a heading that folds it, as VS Code folds a view's sections:
 * open, every window and the credits; folded, one line with each tool's most used
 * window, in the colour its worst window takes, so the sessions get the room.
 */
export function UsageSection({
  usage,
  folded,
  onToggle,
}: {
  usage: Usage | null
  folded: boolean
  onToggle: () => void
}) {
  const tools = ["claude", "codex"].map((provider) => ({
    provider,
    ...usageSummary((usage?.usage ?? []).filter((r) => r.provider === provider)),
  }))
  return (
    <div className="shrink-0 px-2 pt-2 pb-2">
      <button
        type="button"
        aria-expanded={!folded}
        title={folded ? "Show every window" : "Fold to one line"}
        onClick={onToggle}
        className="chat-panel-head flex w-full items-center gap-1 rounded-md px-1 pb-1.5 text-left text-[12.5px] font-normal text-muted-foreground hover:text-foreground"
      >
        <ChevronRight
          className={cn("size-3.5 shrink-0 transition-transform", !folded && "rotate-90")}
          aria-hidden
        />
        Usage
        {folded && usage && (
          <span className="ml-auto flex items-center gap-3">
            {tools.map((t) => (
              <span key={t.provider} className="flex items-center gap-1">
                {/* By its mark in VS Code, compact in a narrow panel; by name elsewhere. */}
                <span className="ax-mark text-[13px]" title={toolName(t.provider)} aria-hidden>
                  {MARK[t.provider]}
                </span>
                <span className="chat-usage-name">{toolName(t.provider)}</span>
                <span className={cn("num text-foreground", TONE[t.tone])}>
                  {t.used === null ? "–" : `${Math.round(t.used)}%`}
                </span>
              </span>
            ))}
          </span>
        )}
      </button>
      {!folded && (
        <div className="px-2">
          {usage ? (
            <UsageDetails rows={usage.usage} credits={usage.credits} stacked />
          ) : (
            <p className="text-[12.5px] text-muted-foreground">Reading…</p>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * ax's panel: both tools' usage, then every live session, what waits for you first; and a
 * box at the foot that starts a new one. In VS Code's right sidebar, where Codex and
 * Copilot sit, each session opens in its own tab; on the web page the panel is the
 * sidebar, each session a link, the one open marked, and `head` above it all.
 */
export function SessionsPanel({
  folders,
  onOpen,
  hrefFor,
  current,
  onStarted,
  onChanges,
  head,
}: {
  folders: string[]
  onOpen?: Open
  /** Where each session's row links to, when rows are links. */
  hrefFor?: (provider: Provider, id: string) => string
  /** The session open beside the panel. */
  current?: { provider: string; id: string } | null
  onStarted: (provider: Provider, id: string, name: string) => void
  onChanges?: Changes
  head?: ReactNode
}) {
  const found = useSessions()
  const sessions = found.data?.sessions ?? []
  // While the pointer is over the list its order holds, so a click lands where aimed.
  const [held, setHeld] = useState<string[] | null>(null)
  const [panelDraft, setPanelDraft] = useDraft("session-filters")
  const filter = String(panelDraft.ui?.filter ?? "")
  const providerFilter = String(panelDraft.ui?.provider ?? "")
  const stateFilter = String(panelDraft.ui?.state ?? "")
  const archived = panelDraft.ui?.archived === true
  const setFilter = (filter: string) =>
    setPanelDraft((was) => ({ ...was, ui: { ...was.ui, filter } }))
  const setProviderFilter = (provider: string) =>
    setPanelDraft((was) => ({ ...was, ui: { ...was.ui, provider } }))
  const setStateFilter = (state: string) =>
    setPanelDraft((was) => ({ ...was, ui: { ...was.ui, state } }))
  const setArchived = (archived: boolean) =>
    setPanelDraft((was) => ({ ...was, ui: { ...was.ui, archived } }))
  const filtered = sessions.filter(
    (s) =>
      Boolean(s.archived) === archived &&
      (!providerFilter || s.provider === providerFilter) &&
      (!stateFilter || s.state === stateFilter) &&
      `${s.name} ${s.project ?? ""} ${s.group ?? ""}`.toLowerCase().includes(filter.toLowerCase())
  )
  const sorted = panelRows(filtered)
  const rows = held ? keptOrder(sorted, held) : sorted
  // The workspace's own projects go unsaid; a session from another repository says which.
  const home = new Set(folders.map((f) => f.split("/").filter(Boolean).at(-1)))
  const [all, setAll] = useState(false)
  const isCurrent = (row: PanelRow) => row.provider === current?.provider && row.id === current.id
  // The one open stays in view, however far down the list it is.
  const shown = all ? rows : rows.filter((row, n) => n < SHOWN || isCurrent(row))
  const usage = useUsage()
  const [folded, toggleFolded] = useFolded()
  return (
    <div className="chat-panel flex h-dvh flex-col">
      {head}
      <UsageSection usage={usage} folded={folded} onToggle={toggleFolded} />
      <section
        aria-label="Sessions"
        className="min-h-0 flex-1 overflow-y-auto px-2 pt-2"
        onPointerEnter={() => setHeld(rows.map(rowKey))}
        onPointerLeave={() => setHeld(null)}
      >
        <h2 className="chat-panel-head px-2 pb-1 text-[12.5px] font-normal text-muted-foreground">
          Sessions
        </h2>
        <div className="mb-2 flex flex-wrap gap-1 px-2 text-xs">
          <input
            className="min-w-0 flex-1 rounded border bg-card px-2 py-1"
            aria-label="Filter sessions"
            placeholder="Filter name, project or group"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <select
            aria-label="Filter provider"
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
          >
            <option value="">Both tools</option>
            <option value="claude">Claude</option>
            <option value="codex">Codex</option>
          </select>
          <select
            aria-label="Filter state"
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
          >
            <option value="">All states</option>
            <option value="working">Working</option>
            <option value="waiting">Waiting</option>
            <option value="idle">Idle</option>
          </select>
          <label>
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
            />{" "}
            Archived
          </label>
        </div>
        {found.data && <StaleNote error={found.error} at={found.at} />}
        {found.data?.errors?.map((error) => (
          <p key={error} role="alert" className="px-2 py-1 text-xs text-critical">
            {error}
          </p>
        ))}
        {rows.length === 0 ? (
          <p className="px-2 py-1 text-[12.5px] text-muted-foreground">
            {found.error
              ? unanswered(found.error)
              : found.data?.errors?.length
                ? "Some providers could not be checked. Retry the session list."
                : found.data
                  ? "No live sessions. Start one below."
                  : "Reading…"}
          </p>
        ) : (
          <ul className="space-y-px">
            {shown.map((row) => (
              <Row
                key={`${row.provider}:${row.id}`}
                row={row}
                project={row.project && !home.has(row.project) ? row.project : null}
                href={hrefFor?.(row.provider, row.id)}
                current={isCurrent(row)}
                onOpen={onOpen}
                onChanges={onChanges}
              />
            ))}
          </ul>
        )}
        {rows.length > SHOWN && (
          <button
            type="button"
            className="chat-panel-more px-2 py-1.5 text-[12.5px] text-muted-foreground hover:text-foreground"
            onClick={() => setAll((was) => !was)}
          >
            {all ? "Show fewer" : `View all (${rows.length})`}
          </button>
        )}
      </section>
      <StartBox folders={folders} sessions={sessions} onStarted={onStarted} />
    </div>
  )
}

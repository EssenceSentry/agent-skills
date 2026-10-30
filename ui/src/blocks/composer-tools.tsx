import {
  FileText,
  Folder,
  ImagePlus,
  Lightbulb,
  LogOut,
  Paperclip,
  Plus,
  ShieldCheck,
  Target,
  TextSelect,
  X,
} from "lucide-react"
import { type RefObject, useRef } from "react"
import { ModelEffortPicker } from "@/blocks/model-picker"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { ModelGroup, ModelPick } from "@/lib/models"
import { goalLine, type Reference, referenceKey, referenceLabel } from "@/lib/plus"
import type { ChatSettings, ChatState, Goal, Provider } from "@/lib/sessions"

export type Change = Partial<ChatSettings>

/**
 * The + menu, as in Codex: what to add to the message (files and folders, the editor's
 * selection, pictures) and the session's modes (plan mode, a goal, approve for me). It
 * opens over the message box, as wide as it, each item's hint right after its name.
 */
export function PlusMenu({
  box,
  settings,
  disabled,
  onFiles,
  onSelection,
  onPictures,
  onChange,
  onGoal,
  modesNote,
  handBack,
}: {
  box: RefObject<HTMLElement | null>
  settings: ChatSettings | null | undefined
  disabled?: boolean
  /** Files and the editor's selection, offered only where an editor is behind the page. */
  onFiles?: () => void
  onSelection?: () => void
  onPictures: (files: File[]) => void
  onChange: (change: Change) => void
  onGoal: () => void
  /** Where the modes are set when ax can't change them; they show, disabled, saying so. */
  modesNote?: string | null
  /** For a session ax holds: let go of it, to continue it elsewhere; `note` says how. */
  handBack?: { note: string; disabled: boolean; onSelect: () => void }
}) {
  const picker = useRef<HTMLInputElement>(null)
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="chat-plus"
          aria-label="Add and modes"
          title="Add files, the selection or pictures; set modes"
          disabled={disabled}
        >
          <Plus />
        </DropdownMenuTrigger>
        <DropdownMenuContent
          anchor={box}
          side="top"
          align="start"
          sideOffset={6}
          className="chat-menu chat-menu-wide"
        >
          <DropdownMenuGroup>
            <DropdownMenuLabel>Add</DropdownMenuLabel>
            {onFiles && (
              <DropdownMenuItem onClick={onFiles}>
                <Paperclip /> Files and folders
                <span className="chat-menu-hint">From the workspace or anywhere</span>
              </DropdownMenuItem>
            )}
            {onSelection && (
              <DropdownMenuItem onClick={onSelection}>
                <TextSelect /> Current selection
                <span className="chat-menu-hint">The code selected in the editor</span>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => picker.current?.click()}>
              <ImagePlus /> Pictures
              <span className="chat-menu-hint">Or paste them in the box</span>
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Mode</DropdownMenuLabel>
            <DropdownMenuItem onClick={onGoal} disabled={Boolean(modesNote)}>
              <Target /> Goal
              <span className="chat-menu-hint">{modesNote ?? "Set a goal to keep pursuing"}</span>
            </DropdownMenuItem>
            <DropdownMenuCheckboxItem
              checked={settings?.plan ?? false}
              disabled={Boolean(modesNote)}
              onCheckedChange={(on) => onChange({ plan: on })}
            >
              <Lightbulb /> Plan mode
              <span className="chat-menu-hint">
                {modesNote ?? (settings?.plan ? "Turn plan mode off" : "Turn plan mode on")}
              </span>
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={settings?.auto ?? false}
              disabled={Boolean(modesNote)}
              onCheckedChange={(on) => onChange({ auto: on })}
            >
              <ShieldCheck /> Approve for me
              <span className="chat-menu-hint">
                {modesNote ??
                  (settings?.auto ? "Ask before its actions again" : "Approve its actions for you")}
              </span>
            </DropdownMenuCheckboxItem>
          </DropdownMenuGroup>
          {handBack && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuLabel>Session</DropdownMenuLabel>
                <DropdownMenuItem
                  onClick={handBack.onSelect}
                  disabled={handBack.disabled}
                  title={handBack.note}
                >
                  <LogOut /> Hand back
                  <span className="chat-menu-hint">Let go of it, to continue it elsewhere</span>
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <input
        ref={picker}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => {
          onPictures(Array.from(e.target.files ?? []))
          e.target.value = ""
        }}
      />
    </>
  )
}

/** The modes that are on, each a chip that turns it off. */
export function ModeChips({
  settings,
  disabled,
  onChange,
}: {
  settings: ChatSettings | null | undefined
  disabled?: boolean
  onChange: (change: Change) => void
}) {
  if (!settings) return null
  return (
    <>
      {settings.plan && (
        <button
          type="button"
          className="chat-chip"
          aria-label="Plan mode is on: turn it off"
          title="Plan mode: it plans first and asks before acting. Click to turn it off."
          onClick={() => onChange({ plan: false })}
          disabled={disabled}
        >
          <Lightbulb /> Plan
        </button>
      )}
      {settings.auto && (
        <button
          type="button"
          className="chat-chip"
          aria-label="Approve for me is on: turn it off"
          title="Approve for me: its actions are approved without asking you. Click to turn it off."
          onClick={() => onChange({ auto: false })}
          disabled={disabled}
        >
          <ShieldCheck /> Approve for me
        </button>
      )}
    </>
  )
}

/** The session's model and effort, in Codex's picker, among its own tool's models. */
export function ModelPicker({
  chat,
  provider,
  disabled,
  onChange,
}: {
  chat: ChatState
  provider: Provider
  disabled?: boolean
  onChange: (change: Change) => void
}) {
  const models = chat.models ?? []
  if (!chat.settings || !models.length) return null
  const groups: ModelGroup[] = [{ provider, label: provider, models }]
  const pick: ModelPick = { provider, model: chat.settings.model, effort: chat.settings.effort }
  return (
    <ModelEffortPicker
      groups={groups}
      pick={pick}
      disabled={disabled}
      onPick={(next) => {
        const change: Change = {}
        // Claude's "Default" entry is set as itself on a running session.
        const model = next.model ?? (provider === "claude" ? "default" : null)
        if (model && model !== chat.settings?.model) change.model = model
        if (next.effort !== chat.settings?.effort || next.model !== chat.settings?.model)
          change.effort = next.effort
        if (Object.keys(change).length) onChange(change)
      }}
    />
  )
}

/** The goal the session pursues, its progress, and a way to clear it. */
export function GoalBar({
  goal,
  disabled,
  clearNote,
  onClear,
}: {
  goal: Goal
  disabled?: boolean
  /** When clearing takes effect, if not at once. */
  clearNote?: string | null
  onClear: () => void
}) {
  return (
    <div className="chat-goal flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2 text-xs">
      <Target className="size-3.5 shrink-0" aria-hidden />
      {/* In a narrow column the goal keeps half the line; its time and tokens give way. */}
      <span className="min-w-[45%] flex-1 truncate" title={goal.objective}>
        {goal.objective}
      </span>
      <span
        className="chat-goal-line min-w-0 truncate text-muted-foreground"
        title={goalLine(goal)}
      >
        {goalLine(goal)}
      </span>
      <button
        type="button"
        className="chat-goal-clear grid size-5 shrink-0 place-items-center rounded-full"
        aria-label="Clear the goal"
        title={clearNote ? `Clear the goal. ${clearNote}` : "Clear the goal"}
        onClick={onClear}
        disabled={disabled}
      >
        <X className="size-3" />
      </button>
    </div>
  )
}

const ICONS = { file: FileText, folder: Folder, selection: TextSelect }

/** The files, folders and selections going with the message, each removable. */
export function ReferenceTray({
  refs,
  onRemove,
}: {
  refs: Reference[]
  onRemove: (i: number) => void
}) {
  if (!refs.length) return null
  return (
    <ul className="chat-refs flex flex-wrap gap-1.5 px-1 pt-1 pb-1.5" aria-label="Sent with it">
      {refs.map((ref, i) => {
        const Icon = ICONS[ref.kind]
        return (
          <li key={referenceKey(ref)} className="chat-ref" title={ref.path}>
            <Icon aria-hidden />
            {referenceLabel(ref)}
            <button
              type="button"
              aria-label={`Remove ${referenceLabel(ref)}`}
              onClick={() => onRemove(i)}
            >
              <X />
            </button>
          </li>
        )
      })}
    </ul>
  )
}

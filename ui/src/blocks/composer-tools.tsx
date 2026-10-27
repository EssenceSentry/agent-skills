import {
  ChevronDown,
  FileText,
  Folder,
  ImagePlus,
  Lightbulb,
  Paperclip,
  Plus,
  ShieldCheck,
  Target,
  TextSelect,
  X,
} from "lucide-react"
import { type RefObject, useRef } from "react"

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { effortLabel, goalLine, modelChoice, type Reference, referenceLabel } from "@/lib/plus"
import type { ChatSettings, ChatState, Goal } from "@/lib/sessions"

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
}: {
  box: RefObject<HTMLElement | null>
  settings: ChatSettings | null | undefined
  disabled?: boolean
  onFiles: () => void
  onSelection: () => void
  onPictures: (files: File[]) => void
  onChange: (change: Change) => void
  onGoal: () => void
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
            <DropdownMenuItem onClick={onFiles}>
              <Paperclip /> Files and folders
              <span className="chat-menu-hint">From the workspace or anywhere</span>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onSelection}>
              <TextSelect /> Current selection
              <span className="chat-menu-hint">The code selected in the editor</span>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => picker.current?.click()}>
              <ImagePlus /> Pictures
              <span className="chat-menu-hint">Or paste them in the box</span>
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuLabel>Mode</DropdownMenuLabel>
            <DropdownMenuItem onClick={onGoal}>
              <Target /> Goal
              <span className="chat-menu-hint">Set a goal to keep pursuing</span>
            </DropdownMenuItem>
            <DropdownMenuCheckboxItem
              checked={settings?.plan ?? false}
              onCheckedChange={(on) => onChange({ plan: on })}
            >
              <Lightbulb /> Plan mode
              <span className="chat-menu-hint">
                {settings?.plan ? "Turn plan mode off" : "Turn plan mode on"}
              </span>
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={settings?.auto ?? false}
              onCheckedChange={(on) => onChange({ auto: on })}
            >
              <ShieldCheck /> Approve for me
              <span className="chat-menu-hint">
                {settings?.auto ? "Ask before its actions again" : "Approve its actions for you"}
              </span>
            </DropdownMenuCheckboxItem>
          </DropdownMenuGroup>
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

/** The model and effort the session runs, and the others it offers. */
export function ModelPicker({
  chat,
  disabled,
  onChange,
}: {
  chat: ChatState
  disabled?: boolean
  onChange: (change: Change) => void
}) {
  const choice = modelChoice(chat)
  if (!choice) return null
  const models = chat.models ?? []
  const pick = (id: string) => {
    const model = models.find((m) => m.id === id)
    const keeps = choice.effort !== null && model?.efforts.includes(choice.effort)
    const effort =
      model?.efforts.length && !keeps ? (model.default_effort ?? model.efforts[0]) : undefined
    onChange(effort ? { model: id, effort } : { model: id })
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="chat-model"
        aria-label={`Model: ${choice.label}`}
        disabled={disabled}
      >
        {choice.label}
        <ChevronDown />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="chat-menu w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Model</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={choice.model} onValueChange={(id) => pick(String(id))}>
            {models.map((m) => (
              <DropdownMenuRadioItem key={m.id} value={m.id}>
                {m.label}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        {choice.efforts.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuLabel>Effort</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={choice.effort ?? ""}
                onValueChange={(effort) => onChange({ effort: String(effort) })}
              >
                {choice.efforts.map((e) => (
                  <DropdownMenuRadioItem key={e} value={e}>
                    {effortLabel(e)}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** The goal the session pursues, its progress, and a way to clear it. */
export function GoalBar({
  goal,
  disabled,
  onClear,
}: {
  goal: Goal
  disabled?: boolean
  onClear: () => void
}) {
  return (
    <div className="chat-goal flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2 text-xs">
      <Target className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate" title={goal.objective}>
        {goal.objective}
      </span>
      <span className="chat-goal-line shrink-0 text-muted-foreground">{goalLine(goal)}</span>
      <button
        type="button"
        className="chat-goal-clear grid size-5 shrink-0 place-items-center rounded-full"
        aria-label="Clear the goal"
        title="Clear the goal"
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
          <li key={`${ref.kind}:${referenceLabel(ref)}`} className="chat-ref" title={ref.path}>
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

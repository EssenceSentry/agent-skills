import { Popover } from "@base-ui/react/popover"
import { Check, ChevronDown, ChevronLeft, ChevronRight, RotateCcw } from "lucide-react"
import { useState } from "react"

import {
  choose,
  chosen,
  featured,
  isMaximum,
  type ModelGroup,
  type ModelPick,
  modelName,
  shownName,
} from "@/lib/models"
import { effortLabel } from "@/lib/plus"
import type { Provider } from "@/lib/sessions"
import { cn } from "@/lib/utils"

/*
 * The model and its effort, as Codex picks them: a button naming both, opening on a
 * slider of the model's efforts with the effort named above it in the accent colour, and
 * below that the model, which opens the list of models. A new session lists both tools'
 * models, so picking one also picks the tool.
 */

export type PanelView = "effort" | "models"

const TOOL: Record<Provider, string> = { claude: "Claude Code", codex: "Codex" }

/** The efforts as a track of dots, filled up to a round thumb on the one chosen. */
function EffortSlider({
  efforts,
  effort,
  onChange,
}: {
  efforts: string[]
  effort: string | null
  onChange: (effort: string) => void
}) {
  const at = effort ? efforts.indexOf(effort) : -1
  const last = Math.max(efforts.length - 1, 1)
  // Centres from the track's left end to its right, 14px in from each, where the thumb fits.
  const place = (i: number) => `calc(14px + (100% - 28px) * ${i / last})`
  return (
    <div
      className="chat-slider relative mx-1.5 my-1 h-8"
      data-maximum={isMaximum(effort) || undefined}
    >
      <div className="chat-slider-track absolute inset-x-0 top-1 h-6 overflow-hidden rounded-full bg-muted">
        {at >= 0 && (
          <div
            className="chat-slider-range absolute inset-y-0 left-0 bg-primary"
            style={{ width: `calc(${place(at)} + 4px)` }}
          />
        )}
      </div>
      {efforts.map((e, i) => (
        <span
          key={e}
          aria-hidden
          data-on={i <= at || undefined}
          className="chat-slider-tick pointer-events-none absolute top-1/2 size-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted-foreground/50 data-[on]:bg-primary-foreground/40"
          style={{ left: place(i) }}
        />
      ))}
      {at >= 0 && (
        <span
          aria-hidden
          className="chat-slider-thumb pointer-events-none absolute top-1/2 size-7 -translate-x-1/2 -translate-y-1/2 rounded-full border bg-white shadow-sm transition-[left]"
          style={{ left: place(at) }}
        />
      )}
      <input
        type="range"
        min={0}
        max={efforts.length - 1}
        step={1}
        value={Math.max(at, 0)}
        onChange={(e) => onChange(efforts[Number(e.target.value)] ?? efforts[0])}
        aria-label="Effort"
        aria-valuetext={effort ? effortLabel(effort) : "The tool's default"}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </div>
  )
}

/** What the picker opens on: the effort slider, or the list of models. */
export function ModelPanel({
  groups,
  pick,
  onPick,
  view,
  onView,
  onDone,
  more: opened = [],
}: {
  groups: ModelGroup[]
  pick: ModelPick
  onPick: (pick: ModelPick) => void
  view: PanelView
  onView: (view: PanelView) => void
  onDone?: () => void
  /** The tools whose whole list shows, not only their latest models. */
  more?: Provider[]
}) {
  const [more, setMore] = useState<Provider[]>(opened)
  const now = chosen(groups, pick)
  const model = now.model
  if (view === "effort" && model && model.efforts.length > 0) {
    return (
      <div className="chat-model-panel flex flex-col p-1">
        <div className="relative flex min-h-9 items-center justify-center px-9">
          <button
            type="button"
            className="chat-model-switch flex min-w-0 flex-col items-center rounded-md px-1.5 py-0.5 hover:bg-muted"
            onClick={() => onView("models")}
          >
            <span
              className="chat-effort-title text-[15px] leading-5 font-medium text-primary"
              data-maximum={isMaximum(now.effort) || undefined}
            >
              {/* The model's default, by name when the tool says which it is. */}
              {pick.effort
                ? effortLabel(pick.effort)
                : now.effort
                  ? `${effortLabel(now.effort)} · default`
                  : "Default effort"}
            </span>
            <span className="flex max-w-full min-w-0 items-center gap-0.5 text-xs text-muted-foreground">
              <span className="truncate">{shownName(model)}</span>
              <ChevronRight className="size-3 shrink-0" />
            </span>
          </button>
          <button
            type="button"
            aria-label="Reset to default"
            title="Reset to default"
            disabled={pick.effort === null}
            className="chat-model-reset absolute top-0 right-0 flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
            onClick={() => onPick({ ...pick, effort: null })}
          >
            <RotateCcw className="size-4" />
          </button>
        </div>
        <EffortSlider
          efforts={model.efforts}
          effort={now.effort}
          onChange={(effort) => onPick({ ...pick, effort })}
        />
        {!now.effort && (
          <p className="chat-model-note m-0 px-2 pb-1 text-center text-[12px] text-muted-foreground">
            {TOOL[pick.provider]} picks its own until you choose one
          </p>
        )}
      </div>
    )
  }
  const several = groups.length > 1
  return (
    <div className="chat-model-panel flex flex-col p-1">
      <div className="flex items-center gap-1 px-1 pt-0.5 pb-1">
        {model && model.efforts.length > 0 && (
          <button
            type="button"
            aria-label="Back to the effort"
            className="flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={() => onView("effort")}
          >
            <ChevronLeft className="size-3.5" />
          </button>
        )}
        <span className="chat-model-heading px-1 text-[12.5px] text-muted-foreground">
          Select model
        </span>
      </div>
      <div className="max-h-80 overflow-y-auto" role="listbox" aria-label="Models">
        {groups.map((group) => {
          // The latest of each featured family first, and the one chosen if it isn't one.
          const top = featured(group.provider, group.models)
          const current = group.provider === now.group?.provider ? model : null
          const first = current && !top.includes(current) ? [...top, current] : top
          const rest = group.models.filter((m) => !first.includes(m))
          const all = more.includes(group.provider) || first.length === 0
          const rows = all ? [...first, ...rest] : first
          return (
            <fieldset key={group.provider} className="m-0 min-w-0 border-0 p-0 pb-1">
              <legend
                className={cn(
                  "chat-model-group px-2 pt-1.5 pb-0.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase",
                  !several && "sr-only"
                )}
              >
                {group.label}
              </legend>
              {rows.map((m) => {
                const on = group.provider === now.group?.provider && m.id === model?.id
                return (
                  <button
                    key={m.id}
                    type="button"
                    role="option"
                    aria-selected={on}
                    aria-checked={on}
                    className="chat-model-row flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-muted"
                    onClick={() => {
                      const next = choose(groups, pick, group.provider, m.id)
                      onPick(next)
                      const picked = chosen(groups, next).model
                      if (picked?.efforts.length) onView("effort")
                      else onDone?.()
                    }}
                  >
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{modelName(m.label)}</span>
                      {m.default && /^default/i.test(m.label) && m.description && (
                        <span className="truncate text-xs text-muted-foreground">
                          {m.description}
                        </span>
                      )}
                    </span>
                    {on && <Check className="size-4 shrink-0" />}
                  </button>
                )
              })}
              {rest.length > 0 && first.length > 0 && (
                <button
                  type="button"
                  aria-expanded={all}
                  className="chat-model-more flex w-full items-center gap-1 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={() =>
                    setMore((was) =>
                      all ? was.filter((p) => p !== group.provider) : [...was, group.provider]
                    )
                  }
                >
                  {all ? "Show fewer" : `Show ${rest.length} more`}
                  <ChevronDown
                    className={cn("size-3.5 transition-transform", all && "rotate-180")}
                  />
                </button>
              )}
            </fieldset>
          )
        })}
      </div>
    </div>
  )
}

/** The button naming the model and effort, and the panel it opens above it. */
export function ModelEffortPicker({
  groups,
  pick,
  onPick,
  disabled,
}: {
  groups: ModelGroup[]
  pick: ModelPick
  onPick: (pick: ModelPick) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const now = chosen(groups, pick)
  const [view, setView] = useState<PanelView>("effort")
  const name = now.model ? shownName(now.model) : `${pick.provider}: unavailable`
  const effort = now.effort ? effortLabel(now.effort) : null
  // Its own box, so the focus guards an open popover adds beside the button stay in it
  // and the row around it doesn't move.
  return (
    <span className="chat-model-wrap inline-flex min-w-0">
      <Popover.Root
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (next) setView("effort")
        }}
      >
        <Popover.Trigger
          className={cn(
            "chat-model inline-flex max-w-64 min-w-0 items-center gap-1 rounded-full px-2.5 py-1 text-[12.5px] hover:bg-muted disabled:opacity-50"
          )}
          aria-label={`Model: ${name}${effort ? `, ${effort}` : ""}`}
          disabled={disabled}
        >
          <span className="chat-model-name truncate">{name}</span>
          {effort && (
            <span
              className="chat-model-effort shrink-0 text-muted-foreground"
              data-maximum={isMaximum(now.effort) || undefined}
            >
              {effort}
            </span>
          )}
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Positioner side="top" align="end" sideOffset={8} className="isolate z-50">
            <Popover.Popup
              className="chat-model-popup w-64 origin-(--transform-origin) rounded-2xl border bg-popover text-popover-foreground shadow-lg outline-none"
              aria-label="Model and effort"
            >
              <ModelPanel
                groups={groups}
                pick={pick}
                onPick={onPick}
                view={view}
                onView={setView}
                onDone={() => setOpen(false)}
              />
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
    </span>
  )
}

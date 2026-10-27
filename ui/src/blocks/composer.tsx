import {
  ArrowUp,
  Info,
  Loader2,
  LogOut,
  SendHorizontal,
  ShieldQuestion,
  Square,
  Target,
  X,
} from "lucide-react"
import { type KeyboardEvent, useContext, useRef, useState } from "react"

import {
  type Change,
  GoalBar,
  ModeChips,
  ModelPicker,
  PlusMenu,
  ReferenceTray,
} from "@/blocks/composer-tools"
import { Markdown } from "@/blocks/markdown"
import { AttachButton, ConfirmDialog, PictureTray, usePictures } from "@/blocks/message-input"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { chatAct, hurry } from "@/lib/ax"
import { EditorHost } from "@/lib/host"
import { type Reference, referenceLabel, withReferences } from "@/lib/plus"
import { type Approval, type ChatState, canSend, composerMode, type Session } from "@/lib/sessions"
import { askExtension } from "@/lib/transport"

type Payload = Record<string, unknown>

/** Text with `code` in backticks, as the server writes commands and paths. */
export function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split("`").map((part, i) =>
        i % 2 ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: the parts of one fixed string
          <code key={i} className="label-mono rounded bg-muted px-1 py-px text-[0.92em]">
            {part}
          </code>
        ) : (
          part
        )
      )}
    </>
  )
}

function ApprovalCard({
  approval,
  onAnswer,
  busy,
}: {
  approval: Approval
  onAnswer: (allow: boolean) => void
  busy: boolean
}) {
  return (
    <div className="chat-approval space-y-2.5 rounded-xl border border-warning/40 bg-warning/8 p-3.5">
      <div className="flex items-start gap-2">
        <ShieldQuestion className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <div className="min-w-0 space-y-1">
          <div className="text-[13.5px] font-medium">
            It asks to <Inline text={approval.summary} />
          </div>
          {approval.reason && (
            <div className="text-xs text-muted-foreground">{approval.reason}</div>
          )}
        </div>
      </div>
      {approval.plan && (
        <div className="chat-plan max-h-80 overflow-auto rounded-lg border bg-card px-3.5 py-3">
          <Markdown className="text-[13px] leading-relaxed">{approval.plan}</Markdown>
        </div>
      )}
      {approval.detail && (
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">Details</summary>
          <pre className="label-mono mt-1.5 max-h-48 overflow-auto rounded-md bg-sunken/70 p-2.5 text-[11.5px] whitespace-pre-wrap">
            {approval.detail}
          </pre>
        </details>
      )}
      <div className="flex gap-2">
        <Button size="sm" onClick={() => onAnswer(true)} disabled={busy}>
          {approval.plan ? "Go ahead" : "Allow"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => onAnswer(false)} disabled={busy}>
          {approval.plan ? "Keep planning" : "Refuse"}
        </Button>
      </div>
    </div>
  )
}

/**
 * Writing to the session: a box to send from, approvals to answer, a stop, and a way to
 * take a session over from the Claude app. Through a shared link, each message and
 * approval asks a second yes.
 */
export function Composer({ session, chat }: { session: Session; chat: ChatState }) {
  const [text, setText] = useState("")
  const [inFlight, setInFlight] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ask, setAsk] = useState<{ question: string; payload: Payload } | null>(null)
  const pictures = usePictures(setError)
  const [refs, setRefs] = useState<Reference[]>([])
  const [goalMode, setGoalMode] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const frame = useRef<HTMLDivElement>(null)
  const mode = composerMode(chat)
  // In VS Code, as in Codex: an up arrow to send, and the note about who holds the session
  // folded into the hand-back icon beside the plus instead of a line under the box.
  const editor = useContext(EditorHost)
  const SendIcon = editor ? ArrowUp : SendHorizontal
  const base = { provider: session.provider, id: session.id, cwd: session.cwd, name: session.name }

  async function run(payload: Payload) {
    setInFlight(true)
    setError(null)
    try {
      const said = await chatAct({ ...base, ...payload })
      if (said.confirm) {
        setAsk({
          question: said.question ?? "Confirm?",
          payload: { ...payload, confirm: said.confirm },
        })
        return
      }
      setAsk(null)
      if (payload.action === "send" || payload.action === "goal") {
        setText("")
        pictures.clear()
        setRefs([])
        setGoalMode(false)
      }
      hurry()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setInFlight(false)
    }
  }

  const ready = goalMode
    ? text.trim().length > 0 && !chat.busy
    : canSend(chat, text, pictures.pictures.length + refs.length)
  const send = () =>
    ready &&
    !inFlight &&
    run(
      goalMode
        ? { action: "goal", objective: withReferences(text, refs) }
        : { action: "send", text: withReferences(text, refs), images: pictures.payload() }
    )
  const change = (c: Change) => run({ action: "settings", ...c })
  // Files and the selection come from the editor; each joins the message once.
  const add = (found: Reference[]) =>
    setRefs((was) => {
      const seen = new Set(was.map(referenceLabel))
      return [...was, ...found.filter((r) => !seen.has(referenceLabel(r)))]
    })
  const addFiles = () =>
    askExtension<Reference[]>("pickFiles").then(add, (e: Error) => setError(e.message))
  const addSelection = () =>
    askExtension<Reference | null>("selection").then(
      (found) =>
        found ? add([found]) : setError("Select some code in an editor first, then add it."),
      (e: Error) => setError(e.message)
    )
  const startGoal = () => {
    setGoalMode(true)
    // After the menu has closed and handed the focus back to its button.
    setTimeout(() => box.current?.focus(), 0)
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }
  const placeholder = goalMode
    ? "What should it keep working toward?"
    : chat.holder === "codex app"
      ? "Message it through the Codex app…"
      : `Message ${session.name}…`

  return (
    <div className="chat-composer sticky bottom-0 z-10 -mx-4 space-y-2 bg-background/90 px-4 pt-2 pb-4 backdrop-blur-md md:-mx-6 md:px-6">
      {chat.goal && (
        <GoalBar
          goal={chat.goal}
          disabled={inFlight || chat.busy}
          onClear={() => run({ action: "goal-clear" })}
        />
      )}
      {chat.approval && (
        <ApprovalCard
          approval={chat.approval}
          busy={inFlight}
          onAnswer={(allow) => run({ action: "answer", request: chat.approval?.id, allow })}
        />
      )}

      {mode === "take-over" || mode === "waiting" ? (
        <div className="chat-takeover flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-3.5">
          <p className="min-w-0 flex-1 text-[13px] text-ink-2">
            <Inline text={chat.note} />
          </p>
          {mode === "take-over" ? (
            <Button size="sm" onClick={() => run({ action: "take-over" })} disabled={inFlight}>
              Take over
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={() => run({ action: "release" })}>
              <Loader2 className="animate-spin" /> Waiting · cancel
            </Button>
          )}
        </div>
      ) : (
        <div
          ref={frame}
          className="chat-box rounded-xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring/40"
        >
          {goalMode && (
            <button
              type="button"
              className="chat-chip chat-goal-chip"
              aria-label="Goal: cancel"
              title="Your message sets a goal it keeps pursuing. Click to send a plain message."
              onClick={() => setGoalMode(false)}
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
            {editor ? (
              <PlusMenu
                box={frame}
                settings={chat.settings}
                disabled={inFlight}
                onFiles={addFiles}
                onSelection={addSelection}
                onPictures={(files) => void pictures.attach(files)}
                onChange={change}
                onGoal={startGoal}
              />
            ) : (
              <AttachButton onFiles={(files) => void pictures.attach(files)} disabled={inFlight} />
            )}
            {editor && chat.holder === "ax" && (
              <Button
                size="icon"
                variant="ghost"
                aria-label="Hand back"
                title={`Hand back. ${chat.note.replaceAll("`", "")}`}
                className="chat-handback"
                onClick={() => run({ action: "release" })}
                disabled={inFlight || chat.busy}
              >
                <LogOut />
              </Button>
            )}
            {editor && <ModeChips settings={chat.settings} disabled={inFlight} onChange={change} />}
            <Textarea
              ref={box}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onPaste={pictures.onPaste}
              onKeyDown={onKey}
              placeholder={placeholder}
              aria-label="Message"
              rows={2}
              className="chat-input max-h-48 min-h-10 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
            />
            {editor && <ModelPicker chat={chat} disabled={inFlight} onChange={change} />}
            {mode === "busy" ? (
              <Button
                size="icon"
                variant="outline"
                aria-label="Stop"
                className="chat-send"
                title="Stop it"
                onClick={() => run({ action: "stop" })}
                disabled={inFlight}
              >
                <Square className="fill-current" />
              </Button>
            ) : (
              <Button
                size="icon"
                aria-label="Send"
                className="chat-send"
                title="Send (Enter)"
                onClick={send}
                disabled={!ready || inFlight}
              >
                {inFlight ? <Loader2 className="animate-spin" /> : <SendIcon />}
              </Button>
            )}
          </div>
        </div>
      )}

      {error && <p className="text-xs text-critical">{error}</p>}
      {chat.error && !error && <p className="text-xs text-critical">{chat.error}</p>}
      {!editor && mode !== "take-over" && mode !== "waiting" && chat.note && (
        <div className="chat-hint flex items-start justify-between gap-3 text-[11.5px] text-muted-foreground">
          <span className="flex min-w-0 items-start gap-1.5">
            <Info className="mt-px size-3.5 shrink-0" aria-hidden />
            <span>
              <Inline text={chat.note} />
            </span>
          </span>
          {chat.holder === "ax" && (
            <button
              type="button"
              className="shrink-0 underline-offset-2 hover:text-foreground hover:underline"
              onClick={() => run({ action: "release" })}
              disabled={inFlight || chat.busy}
            >
              Hand back
            </button>
          )}
        </div>
      )}

      <ConfirmDialog
        question={ask?.question ?? null}
        busy={inFlight}
        onCancel={() => setAsk(null)}
        onYes={() => ask && run(ask.payload)}
      />
    </div>
  )
}

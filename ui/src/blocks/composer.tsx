import { ArrowUp, CornerDownRight, Info, Loader2, SendHorizontal, Target, X } from "lucide-react"
import { type KeyboardEvent, useContext, useEffect, useRef, useState } from "react"
import {
  type Change,
  GoalBar,
  ModeChips,
  ModelPicker,
  PlusMenu,
  ReferenceTray,
} from "@/blocks/composer-tools"
import { ContextPicker } from "@/blocks/context-picker"
import { AttachButton, PictureTray, usePictures } from "@/blocks/message-input"
import { PendingMessages } from "@/blocks/pending-messages"
import { PendingRequests } from "@/blocks/pending-requests"
import { QuestionPanel } from "@/blocks/question"
import { ApprovalPanel, PlanPanel } from "@/blocks/request"
import { useSlash } from "@/blocks/slash-menu"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { chatAct, hurry } from "@/lib/ax"
import { useDraft } from "@/lib/drafts"
import { EditorHost, EditorLook } from "@/lib/host"
import {
  mergeReferences,
  modesElsewhere,
  type Reference,
  referenceKey,
  withReferences,
} from "@/lib/plus"
import { usePreferences } from "@/lib/preferences"
import { type ChatState, canSend, composerMode, type Question, type Session } from "@/lib/sessions"
import { askExtension, inExtension } from "@/lib/transport"
import { cn } from "@/lib/utils"
import { CopyButton } from "./copy-button"

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

/**
 * Writing to the session: a box to send from, always there, and a stop. What it waits on
 * (an approval, a plan, questions) shows above the box until answered. A Claude session
 * open in another app keeps its box too: a message sent waits until it is closed there.
 * Through a shared link, each message and answer asks a second yes.
 */
export function Composer({
  session,
  chat,
  asked,
}: {
  session: Session
  chat: ChatState
  /** Codex's async question still open, answered by a reply. */
  asked?: { call: string; questions: Question[] } | null
}) {
  const [draft, setDraft, draftError] = useDraft(`${session.provider}:${session.id}`)
  const text = draft.text
  const setText = (text: string) => setDraft((was) => ({ ...was, text }))
  const [inFlight, setInFlight] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // What handing it back did, such as adding it to the Claude app's sessions.
  const [handedBack, setHandedBack] = useState<string | null>(null)
  const pictures = usePictures(setError, {
    pictures: draft.pictures,
    set: (change) =>
      setDraft((was) => ({
        ...was,
        pictures: typeof change === "function" ? change(was.pictures) : change,
      })),
  })
  const refs = draft.refs
  const setRefs = (change: Reference[] | ((was: Reference[]) => Reference[])) =>
    setDraft((was) => ({ ...was, refs: typeof change === "function" ? change(was.refs) : change }))
  const [goalMode, setGoalMode] = useState(false)
  const [setAside, setSetAside] = useState<string | null>(null)
  const box = useRef<HTMLTextAreaElement>(null)
  const frame = useRef<HTMLDivElement>(null)
  const mode = composerMode(chat)
  const preferences = usePreferences()
  const excludedContext = useRef(new Set<string>())
  // In VS Code, as in Codex: an up arrow to send, and the note about who holds the session
  // folded into the hand-back icon beside the plus instead of a line under the box.
  const editor = useContext(EditorHost)
  const look = useContext(EditorLook)
  const SendIcon = look ? ArrowUp : SendHorizontal
  const base = { provider: session.provider, id: session.id, cwd: session.cwd, name: session.name }

  useEffect(() => {
    const receipts = new Set(chat.receipts ?? [])
    if (draft.failed?.some((item) => receipts.has(item.id)))
      setDraft((was) => ({ ...was, failed: was.failed?.filter((item) => !receipts.has(item.id)) }))
  }, [chat.receipts, draft.failed, setDraft])

  async function run(payload: Payload, retryId?: string) {
    setInFlight(true)
    setError(null)
    setHandedBack(null)
    const sending = payload.action === "send" || payload.action === "goal"
    const messageId = retryId ?? crypto.randomUUID()
    const outgoing = retryId
      ? payload
      : { ...base, ...payload, ...(sending ? { client_message_id: messageId } : {}) }
    if (sending && !retryId) {
      setDraft((was) => ({
        ...was,
        text: "",
        refs: [],
        pictures: [],
        failed: [
          ...(was.failed ?? []),
          {
            id: messageId,
            text: was.text,
            payload: outgoing,
            refs: was.refs,
            pictures: was.pictures,
          },
        ],
      }))
      setGoalMode(false)
    }
    try {
      const reply = await chatAct(outgoing)
      if (payload.action === "release") setHandedBack(reply.message ?? null)
      if (sending)
        setDraft((was) => ({ ...was, failed: was.failed?.filter((f) => f.id !== messageId) }))
      hurry()
      return reply
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setInFlight(false)
    }
  }

  const ready = goalMode
    ? text.trim().length > 0 && !chat.busy
    : canSend(chat, text, pictures.pictures.length + refs.length)
  const send = (
    delivery: "steer" | "queue" = chat.delivery?.includes("steer") === false ? "queue" : "steer"
  ) =>
    ready &&
    !inFlight &&
    run(
      goalMode
        ? { action: "goal", objective: withReferences(text, refs) }
        : { action: "send", text: withReferences(text, refs), images: pictures.payload(), delivery }
    )
  const change = (c: Change) => run({ action: "settings", ...c })
  // Files and the selection come from the editor; each joins the message once.
  const add = (found: Reference[]) => setRefs((was) => mergeReferences(was, found))
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
  const settings = chat.settings
  const slash = useSlash({
    text,
    setText,
    provider: session.provider,
    cwd: session.cwd,
    off: goalMode,
    execute: (action) => {
      if (action === "history" || action === "session") {
        const target = document.querySelector<HTMLElement>(
          action === "history" ? "[data-history-search]" : "[data-session-actions]"
        )
        let parent: HTMLElement | null = target
        while (parent) {
          if (parent instanceof HTMLDetailsElement) parent.open = true
          parent = parent.parentElement
        }
        target?.focus()
      } else
        void run({ action }).then(async (reply) => {
          const fork = reply as { id?: string } | undefined
          if (action === "fork" && fork?.id) {
            if (inExtension())
              await askExtension("openSession", { provider: session.provider, id: fork.id })
            else location.hash = `#/sessions/${session.provider}/${fork.id}`
          }
        })
    },
    focus: () => box.current?.focus(),
    actions: [
      {
        name: "goal",
        title: "Goal",
        description: "Set a goal to keep pursuing",
        icon: "goal",
        run: startGoal,
      },
      {
        name: "plan",
        title: "Plan mode",
        description: settings?.plan ? "Turn plan mode off" : "Turn plan mode on",
        icon: "plan",
        run: () => change({ plan: !settings?.plan }),
      },
      {
        name: "approve",
        title: "Approve for me",
        description: settings?.auto
          ? "Ask before its actions again"
          : "Approve its actions for you",
        icon: "auto",
        run: () => change({ auto: !settings?.auto }),
      },
    ],
  })
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (slash.onKey(e)) return
    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey) {
        e.preventDefault()
        send("queue")
        return
      }
      if (!e.shiftKey && (preferences.sendKey === "enter" || e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        send()
      }
    }
  }
  const placeholder = goalMode
    ? "What should it keep working toward?"
    : chat.holder === "codex app"
      ? "Queue its next turn in the Codex app…"
      : mode === "busy"
        ? "Message it while it works…"
        : `Message ${session.name}…`

  const live = chat.question
  const later = asked && asked.call !== setAside ? asked : null
  const approval = chat.approval
  const request = chat.requests?.length ? (
    <PendingRequests
      requests={chat.requests}
      session={session}
      answer={(payload) => void run(payload)}
      busy={inFlight}
    />
  ) : approval ? (
    approval.plan != null ? (
      <PlanPanel
        key={approval.id}
        plan={approval.plan}
        provider={session.provider}
        cwd={session.cwd}
        busy={inFlight}
        onAnswer={(allow, message) =>
          run({ action: "answer", request: approval.id, allow, message })
        }
      />
    ) : (
      <ApprovalPanel
        key={approval.id}
        approval={approval}
        provider={session.provider}
        busy={inFlight}
        onAnswer={(allow) => run({ action: "answer", request: approval.id, allow })}
      />
    )
  ) : live ? (
    <QuestionPanel
      key={live.id}
      questions={live.questions}
      busy={inFlight}
      onAnswer={(answers) => run({ action: "answer-question", request: live.id, answers })}
      onSkipAll={
        live.via === "claude"
          ? () => run({ action: "answer", request: live.id, allow: false })
          : undefined
      }
    />
  ) : later ? (
    <QuestionPanel
      key={later.call}
      questions={later.questions}
      busy={inFlight}
      onAnswer={(answers) =>
        run({
          action: "answer-question",
          via: "codex-async",
          call: later.call,
          questions: later.questions.map((q) => q.question),
          answers,
        })
      }
      onSkipAll={() => setSetAside(later.call)}
    />
  ) : null

  return (
    <div className="chat-composer sticky bottom-0 z-10 -mx-4 space-y-2 bg-background/90 px-4 pt-2 pb-4 backdrop-blur-md md:-mx-6 md:px-6">
      {chat.goal && (
        // A goal clears while it works: Codex's at once, Claude's with its next message.
        <GoalBar
          goal={chat.goal}
          disabled={inFlight}
          clearNote={
            session.provider === "claude" && chat.busy
              ? "It stops pursuing it once this turn ends."
              : null
          }
          onClear={() => run({ action: "goal-clear" })}
        />
      )}
      {(chat.requests?.length ?? 0) > 1 && (
        <p className="text-xs text-muted-foreground">
          {chat.requests?.length} requests waiting. Each remains here until answered.
        </p>
      )}
      {request}
      {(draft.failed ?? []).map((failed) => (
        <div key={failed.id} className="rounded-lg border p-2 text-xs">
          <span>Unconfirmed message: {failed.text || "Attachments"}</span>{" "}
          <button
            type="button"
            disabled={inFlight}
            onClick={() => void run(failed.payload, failed.id)}
          >
            Retry delivery
          </button>{" "}
          <button
            type="button"
            disabled={Boolean(text || refs.length || pictures.pictures.length)}
            onClick={() =>
              setDraft((was) => ({
                ...was,
                text: failed.text,
                refs: failed.refs ?? [],
                pictures: failed.pictures ?? [],
                failed: was.failed?.filter((f) => f.id !== failed.id),
              }))
            }
          >
            Recover draft and attachments
          </button>
        </div>
      ))}
      {chat.delivery_paused && (chat.outbox?.length ?? 0) > 0 && (
        <p className="text-xs text-muted-foreground">
          Pending messages are saved with delivery paused. Retry a message to resume.
        </p>
      )}
      <PendingMessages
        messages={chat.outbox ?? []}
        busy={inFlight}
        run={(payload) => void run(payload)}
      />
      {chat.busy && (
        <button
          type="button"
          className="text-xs text-muted-foreground"
          disabled={!ready || inFlight}
          onClick={() => send("queue")}
        >
          Queue next task (⌘/Ctrl+Shift+Enter)
        </button>
      )}
      {(mode === "take-over" || mode === "waiting") && (
        <div className="chat-elsewhere flex items-start justify-between gap-3 px-1 text-[12px] text-muted-foreground">
          <span className="flex min-w-0 items-start gap-1.5">
            {mode === "waiting" && <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin" />}
            <span>
              <Inline text={chat.note} />
            </span>
          </span>
          {mode === "waiting" && (
            <button
              type="button"
              aria-label="Cancel: keep it in the Claude app"
              className="shrink-0 underline-offset-2 hover:text-foreground hover:underline"
              onClick={() => run({ action: "release" })}
              disabled={inFlight}
            >
              Cancel
            </button>
          )}
        </div>
      )}
      {mode === "busy" && chat.mid_turn && chat.mid_turn.length > 0 && (
        // Claude reads it at its next step or as its next turn; Codex as its turn goes on.
        <div
          className="chat-mid-turn flex items-start gap-1.5 px-1 text-[12px] text-muted-foreground"
          role="status"
        >
          <CornerDownRight className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span className="line-clamp-2 min-w-0 [overflow-wrap:anywhere]">
            Sent while it works: {chat.mid_turn.map((t) => `“${t}”`).join(", ")}
          </span>
        </div>
      )}
      <ContextPicker text={text} setText={setText} cwd={session.cwd} add={add} />
      {slash.menu}
      {/* Under a request the box keeps one line, the room going to what waits. */}
      <div
        ref={frame}
        className={cn(
          "chat-box rounded-xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring/40",
          request && "chat-box-compact"
        )}
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
          onRemove={(i) => {
            if (refs[i]) excludedContext.current.add(referenceKey(refs[i]))
            setRefs((was) => was.filter((_, j) => j !== i))
          }}
        />
        <div className="flex items-end gap-2">
          {look ? (
            <PlusMenu
              box={frame}
              settings={chat.settings}
              disabled={inFlight}
              onFiles={editor ? addFiles : undefined}
              onSelection={editor ? addSelection : undefined}
              onPictures={(files) => void pictures.attach(files)}
              onChange={change}
              onGoal={startGoal}
              modesNote={modesElsewhere(chat.holder)}
              handBack={
                chat.holder === "ax"
                  ? {
                      note: chat.note.replaceAll("`", ""),
                      disabled: inFlight || chat.busy,
                      onSelect: () => run({ action: "release" }),
                    }
                  : undefined
              }
            />
          ) : (
            <AttachButton onFiles={(files) => void pictures.attach(files)} disabled={inFlight} />
          )}
          {look && <ModeChips settings={chat.settings} disabled={inFlight} onChange={change} />}
          <Textarea
            ref={box}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onPaste={pictures.onPaste}
            onFocus={() => {
              if (editor && preferences.autoContext)
                void askExtension<Reference[]>("currentContext").then(
                  (found) =>
                    add(found.filter((r) => !excludedContext.current.has(referenceKey(r)))),
                  (e: Error) => setError(e.message)
                )
            }}
            onKeyDown={onKey}
            placeholder={request && !goalMode ? "Or tell it something else…" : placeholder}
            aria-label="Message"
            rows={request ? 1 : 2}
            className={cn(
              "chat-input max-h-48 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0",
              request ? "min-h-7" : "min-h-10"
            )}
          />
          {look && (
            <ModelPicker
              chat={chat}
              provider={session.provider}
              disabled={inFlight}
              onChange={change}
            />
          )}
          {mode === "busy" && (
            <Button
              size="icon"
              aria-label="Stop"
              className="chat-send"
              title="Stop it"
              onClick={() => run({ action: "stop" })}
              disabled={inFlight}
            >
              <span className="chat-stop-mark block size-2.5 rounded-[2px] bg-current" />
            </Button>
          )}
          <Button
            size="icon"
            aria-label={chat.delivery?.includes("steer") === false ? "Queue" : "Send"}
            className="chat-send"
            title={mode === "busy" ? "Send now: it reads this as it works (Enter)" : "Send (Enter)"}
            onClick={() => send()}
            disabled={!ready || inFlight}
          >
            {inFlight ? <Loader2 className="animate-spin" /> : <SendIcon />}
          </Button>
        </div>
      </div>

      {draftError && <p className="text-xs text-critical">{draftError}</p>}
      {error && <p className="text-xs text-critical">{error}</p>}
      {handedBack && (
        <p className="text-xs text-muted-foreground" role="status">
          {handedBack}
        </p>
      )}
      {chat.pending_settings && Object.keys(chat.pending_settings).length > 0 && (
        <p className="text-xs text-muted-foreground" role="status">
          Settings pending:{" "}
          {Object.entries(chat.pending_settings)
            .map(([key, value]) => `${key}: ${value ?? "default"}`)
            .join(", ")}
        </p>
      )}
      {
        <p className="text-xs text-muted-foreground">
          Context: {chat.context?.last?.totalTokens?.toLocaleString() ?? "unknown"}
          {chat.context?.modelContextWindow
            ? ` / ${chat.context?.modelContextWindow.toLocaleString()} tokens`
            : " tokens; window size unknown"}
        </p>
      }
      {chat.error && !error && (
        <div className="text-xs text-critical">
          <p>{chat.error}</p>
          <button type="button" onClick={() => void run({ action: "retry" })}>
            Retry connection
          </button>
          {/auth|sign.?in|log.?in|credential|401|403/i.test(
            `${chat.error} ${chat.diagnostics ?? ""}`
          ) && (
            <details className="group my-2 text-muted-foreground">
              <summary className="cursor-pointer">Sign-in help</summary>
              <p>On the computer running ax, run this command, then retry the connection.</p>
              <div className="flex items-center gap-2">
                <code>{session.provider === "codex" ? "codex login" : "claude auth login"}</code>
                <CopyButton
                  text={session.provider === "codex" ? "codex login" : "claude auth login"}
                  label="Copy sign-in command"
                  className="!opacity-100"
                />
              </div>
            </details>
          )}
          {chat.diagnostics && (
            <details>
              <summary>Diagnostic log</summary>
              <pre className="max-h-60 overflow-auto whitespace-pre-wrap">{chat.diagnostics}</pre>
            </details>
          )}
        </div>
      )}
      {chat.ownership === "unknown" && (
        <p className="text-xs text-critical">
          {chat.note}{" "}
          <button type="button" onClick={() => hurry()}>
            Retry status
          </button>
        </p>
      )}
      {!look && mode !== "take-over" && mode !== "waiting" && chat.note && (
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
    </div>
  )
}

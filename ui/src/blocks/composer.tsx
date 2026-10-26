import { ImagePlus, Info, Loader2, SendHorizontal, ShieldQuestion, Square, X } from "lucide-react"
import { type ClipboardEvent, type KeyboardEvent, useRef, useState } from "react"

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
import { Textarea } from "@/components/ui/textarea"
import { chatAct, hurry } from "@/lib/ax"
import { type Pasted, prepare } from "@/lib/images"
import { type Approval, type ChatState, canSend, composerMode, type Session } from "@/lib/sessions"

type Payload = Record<string, unknown>

/** Text with `code` in backticks, as the server writes commands and paths. */
function Inline({ text }: { text: string }) {
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
    <div className="space-y-2.5 rounded-xl border border-warning/40 bg-warning/8 p-3.5">
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
          Allow
        </Button>
        <Button size="sm" variant="outline" onClick={() => onAnswer(false)} disabled={busy}>
          Refuse
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
  const [pictures, setPictures] = useState<Pasted[]>([])
  const picker = useRef<HTMLInputElement>(null)
  const mode = composerMode(chat)

  async function attach(files: File[]) {
    const images = files.filter((f) => f.type.startsWith("image/"))
    if (!images.length) return false
    try {
      const ready = await Promise.all(images.map(prepare))
      setPictures((was) => [...was, ...ready].slice(0, 10))
    } catch (e) {
      setError((e as Error).message)
    }
    return true
  }
  // Pasting a picture attaches it; pasting text stays text.
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files)
    if (files.some((f) => f.type.startsWith("image/"))) {
      e.preventDefault()
      void attach(files)
    }
  }
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
      if (payload.action === "send") {
        setText("")
        setPictures([])
      }
      hurry()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setInFlight(false)
    }
  }

  const send = () =>
    canSend(chat, text, pictures.length) &&
    !inFlight &&
    run({
      action: "send",
      text: text.trim(),
      images: pictures.map(({ media, data }) => ({ media, data })),
    })
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }
  const placeholder =
    chat.holder === "codex app" ? "Message it through the Codex app…" : `Message ${session.name}…`

  return (
    <div className="sticky bottom-0 z-10 -mx-4 space-y-2 bg-background/90 px-4 pt-2 pb-4 backdrop-blur-md md:-mx-6 md:px-6">
      {chat.approval && (
        <ApprovalCard
          approval={chat.approval}
          busy={inFlight}
          onAnswer={(allow) => run({ action: "answer", request: chat.approval?.id, allow })}
        />
      )}

      {mode === "take-over" || mode === "waiting" ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-3.5">
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
        <div className="rounded-xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring/40">
          {pictures.length > 0 && (
            <ul className="flex flex-wrap gap-2 px-1 pt-1 pb-2" aria-label="Pictures to send">
              {pictures.map((picture, i) => (
                <li key={picture.preview} className="relative">
                  <img
                    src={picture.preview}
                    alt=""
                    className="h-16 w-auto rounded-md border object-cover"
                  />
                  <button
                    type="button"
                    aria-label={`Remove picture ${i + 1}`}
                    onClick={() => setPictures((was) => was.filter((_, j) => j !== i))}
                    className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full border bg-card text-muted-foreground shadow-sm hover:text-foreground"
                  >
                    <X className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-end gap-2">
            <Button
              size="icon"
              variant="ghost"
              aria-label="Attach pictures"
              title="Attach pictures (or paste them)"
              onClick={() => picker.current?.click()}
              disabled={inFlight}
            >
              <ImagePlus />
            </Button>
            <input
              ref={picker}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => {
                void attach(Array.from(e.target.files ?? []))
                e.target.value = ""
              }}
            />
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onPaste={onPaste}
              onKeyDown={onKey}
              placeholder={placeholder}
              aria-label="Message"
              rows={2}
              className="max-h-48 min-h-10 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
            />
            {mode === "busy" ? (
              <Button
                size="icon"
                variant="outline"
                aria-label="Stop"
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
                title="Send (Enter)"
                onClick={send}
                disabled={!canSend(chat, text, pictures.length) || inFlight}
              >
                {inFlight ? <Loader2 className="animate-spin" /> : <SendHorizontal />}
              </Button>
            )}
          </div>
        </div>
      )}

      {error && <p className="text-xs text-critical">{error}</p>}
      {chat.error && !error && <p className="text-xs text-critical">{chat.error}</p>}
      {mode !== "take-over" && mode !== "waiting" && chat.note && (
        <div className="flex items-start justify-between gap-3 text-[11.5px] text-muted-foreground">
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

      <AlertDialog open={ask !== null} onOpenChange={(open) => !open && !inFlight && setAsk(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm from the shared link</AlertDialogTitle>
            <AlertDialogDescription className="whitespace-pre-wrap">
              {ask?.question}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={inFlight}>Cancel</AlertDialogCancel>
            <Button onClick={() => ask && run(ask.payload)} disabled={inFlight}>
              {inFlight && <Loader2 className="animate-spin" />}
              Yes, do it
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

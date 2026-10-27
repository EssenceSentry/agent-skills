import { ArrowLeft } from "lucide-react"
import { Fragment, useContext, useEffect, useRef, useState } from "react"

import { Composer } from "@/blocks/composer"
import { JobCard } from "@/blocks/job-card"
import { Markdown } from "@/blocks/markdown"
import { ConfirmDialog } from "@/blocks/message-input"
import { Lightbox, Pictures } from "@/blocks/pictures"
import { StatusBadge } from "@/blocks/primitives"
import { QuestionCard } from "@/blocks/question"
import { TaskList } from "@/blocks/tasks"
import { workingLine } from "@/lib/activity"
import { chatAct, hurry, useSession, useTick } from "@/lib/ax"
import { EditorHost } from "@/lib/host"
import {
  type Ask,
  type ChatState,
  PROVIDERS,
  type Session,
  type SessionView,
  shownCards,
  stateBadge,
  type TranscriptEvent,
} from "@/lib/sessions"
import { messageStamp, stampsBefore } from "@/lib/time"

/**
 * Your messages on the right, with the pictures you pasted; the agent's answers as text,
 * with the screenshots its tools took on the way below them.
 */
function Message({
  event,
  onOpen,
}: {
  event: TranscriptEvent
  onOpen: (urls: string[], index: number) => void
}) {
  const images = (event.images ?? []).map((p) => p.url)
  if (event.kind === "user")
    return (
      <div className="chat-user ml-auto flex max-w-[85%] flex-col items-end gap-2">
        <Pictures urls={images} onOpen={onOpen} label="Pictures you sent" className="justify-end" />
        {event.text && (
          <div className="chat-bubble rounded-xl bg-primary-soft px-3.5 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap break-words">
            {event.text}
          </div>
        )}
      </div>
    )
  return (
    <div className="chat-reply space-y-2.5">
      <Markdown className="chat-answer text-[14px] leading-relaxed">{event.text}</Markdown>
      <Pictures
        urls={(event.shots ?? []).map((p) => p.url)}
        onOpen={onOpen}
        label="Screenshots it took"
      />
    </div>
  )
}

function Header({ session, back }: { session: Session; back: boolean }) {
  const state = stateBadge(session)
  const tool = PROVIDERS.find((p) => p.provider === session.provider)?.label
  return (
    <header className="chat-header space-y-2">
      {back && (
        <a
          href="#/sessions"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden /> Sessions
        </a>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="chat-title min-w-0 text-[20px] leading-tight break-words">{session.name}</h1>
        {session.state && <StatusBadge status={state.status} label={state.label} />}
      </div>
      <div className="chat-meta label-mono text-[11px] break-all text-muted-foreground">
        {[tool, session.project, session.cwd].filter(Boolean).join(" · ")}
      </div>
    </header>
  )
}

const ELSEWHERE: Record<Ask["via"], string> = {
  claude: "Answer it where this session is open: the Claude app or its terminal.",
  codex: "Answer it in the Codex app.",
  "codex-async": "Answer it in the Codex app.",
}

/**
 * A question the agent asked, in the conversation. One ax waits on live shows by the
 * message box instead; Codex's async kind is answered here by a reply in Codex's own
 * form; any other still open says where to answer it.
 */
function QuestionEvent({ ask, session, chat }: { ask: Ask; session: Session; chat?: ChatState }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<{
    question: string
    payload: Record<string, unknown>
  } | null>(null)
  const live = chat?.question
  if (ask.status === "open" && live && (!live.call || live.call === ask.call)) return null
  const here = ask.status === "open" && ask.via === "codex-async" && chat?.holder !== "elsewhere"

  async function send(payload: Record<string, unknown>) {
    setBusy(true)
    setError(null)
    try {
      const said = await chatAct(payload)
      if (said.confirm) {
        setConfirm({
          question: said.question ?? "Confirm?",
          payload: { ...payload, confirm: said.confirm },
        })
        return
      }
      setConfirm(null)
      hurry()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-1.5">
      <QuestionCard
        ask={ask}
        busy={busy}
        note={ELSEWHERE[ask.via]}
        onAnswer={
          here
            ? (answers) =>
                send({
                  action: "answer-question",
                  provider: session.provider,
                  id: session.id,
                  cwd: session.cwd,
                  name: session.name,
                  via: "codex-async",
                  call: ask.call,
                  questions: ask.questions.map((q) => q.question),
                  answers,
                })
            : undefined
        }
      />
      {error && <p className="text-xs text-critical">{error}</p>}
      <ConfirmDialog
        question={confirm?.question ?? null}
        busy={busy}
        onCancel={() => setConfirm(null)}
        onYes={() => confirm && send(confirm.payload)}
      />
    </div>
  )
}

/**
 * What a working session is doing and for how long, as the desktop app shows it; it
 * ticks on its own, so the transcript above doesn't redraw every second.
 */
function WorkingLine({ session, view }: { session: Session; view: SessionView }) {
  useTick(1000)
  const line = workingLine(session, view)
  if (!line) return null
  return (
    <div
      className="chat-running flex min-w-0 items-center gap-2 pl-1 text-xs text-muted-foreground"
      role="status"
    >
      <span className="live-dot !size-1.5 shrink-0" />
      <span className="min-w-0 truncate">{line.text}</span>
      {line.elapsed && <span className="num shrink-0 opacity-75">{line.elapsed}</span>}
    </div>
  )
}

/**
 * One session's transcript as it grows, with the jobs it waits on below it. In a VS Code
 * tab the sidebar is the way back, so there is no back link.
 */
export function SessionScreen({
  provider,
  id,
  back = true,
}: {
  provider: string
  id: string
  back?: boolean
}) {
  const found = useSession(provider, id)
  const editor = useContext(EditorHost)
  const view = found.data
  const end = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState<{ urls: string[]; index: number } | null>(null)
  const show = (urls: string[], index: number) => setOpen({ urls, index })
  const seen = useRef(0)
  const count = view?.events.length ?? 0

  // Follow new events while the reader is at the bottom; start there.
  useEffect(() => {
    if (!count) return
    const atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 240
    if (seen.current === 0 || (count > seen.current && atBottom))
      end.current?.scrollIntoView({ block: "end" })
    seen.current = count
  }, [count])

  if (!view)
    return (
      <main className="mx-auto max-w-[860px] p-4 md:p-6">
        <div className="panel p-6 text-sm text-muted-foreground" role="status">
          {found.error ? `This session didn't load: ${found.error}` : "Reading the session…"}
        </div>
      </main>
    )

  const chat = view.chat
  // A session ax holds says itself whether it works; the listing lags a few seconds.
  const session =
    chat?.holder === "ax"
      ? {
          ...view.session,
          state: chat.approval
            ? ("waiting" as const)
            : chat.busy
              ? ("working" as const)
              : ("idle" as const),
        }
      : view.session
  const cards = shownCards(session, view.cards)
  const working = session.state === "working"
  const streaming = chat?.busy && chat.partial ? chat.partial : null
  return (
    // The folder relative paths in its answers start from, for an editor opening them.
    <main
      className="chat-thread mx-auto max-w-[860px] space-y-5 p-4 md:p-6"
      data-cwd={session.cwd ?? undefined}
    >
      <Header session={session} back={back} />
      {view.earlier > 0 && (
        <p className="chat-note text-center text-xs text-muted-foreground">
          {view.earlier === 1 ? "1 earlier message" : `${view.earlier} earlier messages`} not shown
        </p>
      )}
      <div className="space-y-4">
        {view.events.map((event, n) => (
          <Fragment key={event.i}>
            {event.kind === "question" && event.ask && (
              <QuestionEvent ask={event.ask} session={session} chat={chat} />
            )}
            {/* In the editor, as in Codex: a date over your message after a pause. */}
            {editor &&
              event.kind === "user" &&
              event.ts &&
              stampsBefore(view.events[n - 1]?.ts ?? null, event.ts) && (
                <p className="chat-time">{messageStamp(event.ts)}</p>
              )}
            {event.kind !== "question" && <Message event={event} onOpen={show} />}
          </Fragment>
        ))}
        <Pictures
          urls={(view.shots ?? []).map((p) => p.url)}
          onOpen={show}
          label="Screenshots it took since its last answer"
        />
      </div>
      {streaming && (
        <div className="chat-reply space-y-1">
          <Markdown className="chat-answer text-[14px] leading-relaxed">{streaming}</Markdown>
        </div>
      )}
      {working && !streaming && <WorkingLine session={session} view={view} />}
      {view.tasks && view.tasks.items.length > 0 && <TaskList tasks={view.tasks} />}
      {cards.length > 0 && (
        <section className="chat-cards space-y-2" aria-label="Jobs it waits on">
          <h2 className="chat-cards-title text-[13px] font-medium text-muted-foreground">
            Waiting on
          </h2>
          {cards.map((card) => (
            <JobCard key={card.key} card={card} />
          ))}
        </section>
      )}
      {chat && <Composer session={session} chat={chat} />}
      <Lightbox urls={open?.urls ?? []} index={open?.index ?? 0} onClose={() => setOpen(null)} />
      {/* After the composer, so following the newest message never leaves it under the box. */}
      <div ref={end} />
    </main>
  )
}

import { ArrowLeft, HeartPulse } from "lucide-react"
import { Fragment, useContext, useEffect, useRef, useState } from "react"
import { ChangeReview } from "@/blocks/change-review"
import { Composer } from "@/blocks/composer"
import { CopyButton } from "@/blocks/copy-button"
import { HistorySearch, ToolEvent } from "@/blocks/history-tools"
import { JobCard } from "@/blocks/job-card"
import { Markdown } from "@/blocks/markdown"
import { Lightbox, Pictures } from "@/blocks/pictures"
import { ChatPreferences } from "@/blocks/preferences"
import { StatusBadge } from "@/blocks/primitives"
import { AskedRow } from "@/blocks/question"
import { SessionActions } from "@/blocks/session-actions"
import { StaleNote } from "@/blocks/stale-note"
import { TaskList } from "@/blocks/tasks"
import { workingLine } from "@/lib/activity"
import { askNote, foldAsks } from "@/lib/asks"
import { useSession, useTick } from "@/lib/ax"
import { EditorLook } from "@/lib/host"
import { heartbeat, responseEnds } from "@/lib/responses"
import {
  type Ask,
  type ChatState,
  heldState,
  metaLine,
  type Session,
  type SessionView,
  shownCards,
  stateBadge,
  type TranscriptEvent,
} from "@/lib/sessions"
import { messageStamp, stampsBefore } from "@/lib/time"
import { cn } from "@/lib/utils"
import { useViewState } from "@/lib/view-state"

/**
 * Your messages on the right, with the pictures you pasted; the agent's answers as text,
 * with the screenshots its tools took on the way below them. The answer that ends a
 * response carries a button that copies the whole response (`copy`), as written, in
 * Markdown. A Codex automation's heartbeat is a short note with its message.
 */
export function Message({
  event,
  copy,
  onOpen,
}: {
  event: TranscriptEvent
  copy?: string
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
  const beat = event.kind === "assistant" ? heartbeat(event.text) : null
  if (beat)
    return (
      <div
        className={cn(
          "chat-heartbeat flex items-start gap-2 text-[12px] leading-snug",
          beat.notified ? "text-ink-2" : "text-muted-foreground"
        )}
        title={beat.automation ? `Codex automation ${beat.automation}` : undefined}
      >
        <HeartPulse className="mt-px size-3.5 shrink-0" aria-hidden />
        <p className="m-0 min-w-0">
          <span className="font-medium">
            {beat.notified ? "Heartbeat, notified you" : "Heartbeat"}
          </span>
          {beat.message && <> · {beat.message}</>}
        </p>
      </div>
    )
  return (
    <div className="chat-reply group space-y-2.5">
      <Markdown className="chat-answer text-[14px] leading-relaxed">{event.text}</Markdown>
      <Pictures
        urls={(event.shots ?? []).map((p) => p.url)}
        onOpen={onOpen}
        label="Screenshots it took"
      />
      {copy && (
        <div className="chat-reply-actions -mt-1 flex">
          <CopyButton text={copy} label="Copy the response" className="-ml-1" />
        </div>
      )}
    </div>
  )
}

function Header({ session, back }: { session: Session; back: boolean }) {
  const state = stateBadge(session)
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
      {/* One line, its end cut in a narrow column; the whole of it on hover. */}
      <div
        className="chat-meta label-mono min-w-0 truncate text-[11px] text-muted-foreground"
        title={session.cwd ?? undefined}
      >
        {metaLine(session.provider, session.project, session.cwd)}
      </div>
    </header>
  )
}

/**
 * A question the agent asked, in the conversation, as a quiet row. One waiting to be
 * answered here shows in the message box's place instead, and its row says it is asking;
 * one waiting anywhere else also says where to answer it.
 */
function QuestionEvent({ ask, chat }: { ask: Ask; chat?: ChatState }) {
  return <AskedRow ask={ask} note={askNote(ask, chat)} />
}

/** Codex's newest async question still open, which the message box answers here. */
function openAsync(events: TranscriptEvent[], chat?: ChatState) {
  if (!chat || chat.holder === "elsewhere") return null
  const ask = events.findLast((e) => e.ask?.via === "codex-async" && e.ask.status === "open")?.ask
  return ask?.status === "open" && ask.call ? { call: ask.call, questions: ask.questions } : null
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
  onState,
}: {
  provider: string
  id: string
  back?: boolean
  /** Told the session's state as it changes, as an editor's tab shows it. */
  onState?: (state: Session["state"], name?: string) => void
}) {
  const container = useRef<HTMLElement>(null)
  const found = useSession(provider, id)
  useViewState(container, `${provider}:${id}`, Boolean(found.data))
  const look = useContext(EditorLook)
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

  // A session ax holds says itself whether it works; the listing lags a few seconds. The
  // tab's icon in an editor follows what this page knows.
  const state =
    view?.chat?.holder === "ax" ? heldState(view.chat) : (view?.session.state ?? undefined)
  // biome-ignore lint/correctness/useExhaustiveDependencies: told once per change of state
  useEffect(() => {
    if (state !== undefined) onState?.(state, view?.session.name)
  }, [state, view?.session.name])

  if (!view)
    return (
      <main className="mx-auto max-w-[860px] p-4 md:p-6">
        <div className="panel p-6 text-sm text-muted-foreground" role="status">
          {found.error ? `This session didn't load: ${found.error}` : "Reading the session…"}
        </div>
      </main>
    )

  const chat = view.chat
  const session = { ...view.session, state: state ?? view.session.state }
  const cards = shownCards(session, view.cards)
  // Questions asked back to back read as one row.
  const shown = foldAsks(view.events)
  const working = session.state === "working"
  const streaming = chat?.busy && chat.partial ? chat.partial : null
  const ends = responseEnds(shown, !working)
  return (
    // The folder relative paths in its answers start from, for an editor opening them.
    <main
      ref={container}
      className="chat-thread mx-auto max-w-[860px] space-y-5 p-4 md:p-6"
      data-cwd={session.cwd ?? undefined}
    >
      <Header session={session} back={back} />
      <details data-view-key="conversation-tools" className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">Conversation tools</summary>
        <div className="mt-3 space-y-3">
          <SessionActions session={session} />
          <HistorySearch session={session} />
          <ChatPreferences />
          <ChangeReview session={session} />
        </div>
      </details>
      <StaleNote error={found.error} at={found.at} />
      {view.earlier > 0 && (
        <p className="chat-note text-center text-xs text-muted-foreground">
          <button type="button" onClick={() => void found.loadEarlier()}>
            Load {view.earlier === 1 ? "1 earlier event" : `${view.earlier} earlier events`}
          </button>
        </p>
      )}
      <div className="space-y-4">
        {shown.map((event, n) => (
          <Fragment key={event.i}>
            {event.kind === "question" && event.ask && (
              <QuestionEvent ask={event.ask} chat={chat} />
            )}
            {/* In the editor's manner, as in Codex: a date over your message after a pause. */}
            {look &&
              event.kind === "user" &&
              event.ts &&
              stampsBefore(shown[n - 1]?.ts ?? null, event.ts) && (
                <p className="chat-time">{messageStamp(event.ts)}</p>
              )}
            {event.kind === "tool" && (
              <ToolEvent
                key={event.call_id ?? event.native_id ?? event.i}
                event={event}
                session={session}
              />
            )}
            {event.kind === "user" && <SessionActions session={session} point={event} />}
            {event.kind !== "question" && event.kind !== "tool" && (
              <Message event={event} copy={ends.get(event.i)} onOpen={show} />
            )}
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
      {view.tasks && view.tasks.items.length > 0 && (
        <TaskList tasks={view.tasks} stopped={!working} />
      )}
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
      {chat && (
        <Composer
          key={`${session.provider}:${session.id}`}
          session={session}
          chat={chat}
          asked={openAsync(view.events, chat)}
        />
      )}
      <Lightbox urls={open?.urls ?? []} index={open?.index ?? 0} onClose={() => setOpen(null)} />
      {/* After the composer, so following the newest message never leaves it under the box. */}
      <div ref={end} />
    </main>
  )
}

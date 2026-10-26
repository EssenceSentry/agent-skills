import { ArrowLeft } from "lucide-react"
import { useEffect, useRef } from "react"

import { Composer } from "@/blocks/composer"
import { JobCard } from "@/blocks/job-card"
import { Markdown } from "@/blocks/markdown"
import { StatusBadge } from "@/blocks/primitives"
import { useSession } from "@/lib/ax"
import {
  PROVIDERS,
  runningNow,
  type Session,
  shownCards,
  stateBadge,
  type TranscriptEvent,
} from "@/lib/sessions"

/** Your messages on the right, the agent's answers as text: the conversation alone. */
function Message({ event }: { event: TranscriptEvent }) {
  if (event.kind === "user")
    return (
      <div className="ml-auto max-w-[85%] rounded-xl bg-primary-soft px-3.5 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap break-words">
        {event.text}
      </div>
    )
  return <Markdown className="text-[14px] leading-relaxed">{event.text}</Markdown>
}

function Header({ session }: { session: Session }) {
  const state = stateBadge(session)
  const tool = PROVIDERS.find((p) => p.provider === session.provider)?.label
  return (
    <header className="space-y-2">
      <a
        href="#/sessions"
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" aria-hidden /> Sessions
      </a>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="min-w-0 text-[20px] leading-tight break-words">{session.name}</h1>
        {session.state && <StatusBadge status={state.status} label={state.label} />}
      </div>
      <div className="label-mono text-[11px] break-all text-muted-foreground">
        {[tool, session.project, session.cwd].filter(Boolean).join(" · ")}
      </div>
    </header>
  )
}

/** One session's transcript as it grows, with the jobs it waits on below it. */
export function SessionScreen({ provider, id }: { provider: string; id: string }) {
  const found = useSession(provider, id)
  const view = found.data
  const end = useRef<HTMLDivElement>(null)
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
  const running = runningNow(session, view)
  const streaming = chat?.busy && chat.partial ? chat.partial : null
  return (
    <main className="mx-auto max-w-[860px] space-y-5 p-4 md:p-6">
      <Header session={session} />
      {view.earlier > 0 && (
        <p className="text-center text-xs text-muted-foreground">
          {view.earlier === 1 ? "1 earlier message" : `${view.earlier} earlier messages`} not shown
        </p>
      )}
      <div className="space-y-4">
        {view.events.map((event) => (
          <Message key={event.i} event={event} />
        ))}
      </div>
      {streaming && (
        <div className="space-y-1">
          <Markdown className="text-[14px] leading-relaxed">{streaming}</Markdown>
        </div>
      )}
      {working && !streaming && (
        <div
          className="flex min-w-0 items-center gap-2 pl-1 text-xs text-muted-foreground"
          role="status"
        >
          <span className="live-dot !size-1.5 shrink-0" />
          {running ? (
            <span className="label-mono min-w-0 truncate">{running.text}</span>
          ) : (
            "Working"
          )}
        </div>
      )}
      {cards.length > 0 && (
        <section className="space-y-2" aria-label="Jobs it waits on">
          <h2 className="text-[13px] font-medium text-muted-foreground">Waiting on</h2>
          {cards.map((card) => (
            <JobCard key={card.key} card={card} />
          ))}
        </section>
      )}
      {chat && <Composer session={session} chat={chat} />}
      {/* After the composer, so following the newest message never leaves it under the box. */}
      <div ref={end} />
    </main>
  )
}

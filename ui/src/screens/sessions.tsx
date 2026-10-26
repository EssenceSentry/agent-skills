import { Activity, TriangleAlert } from "lucide-react"

import { Eyebrow, StatusBadge } from "@/blocks/primitives"
import { useSessions } from "@/lib/ax"
import { sessionHref } from "@/lib/routes"
import { groupSessions, type Session, stateBadge } from "@/lib/sessions"
import { ago } from "@/lib/time"

function SessionRow({ session }: { session: Session }) {
  const state = stateBadge(session)
  const meta = [
    session.project,
    session.kind,
    session.updated && `last said ${ago(session.updated)}`,
  ]
    .filter(Boolean)
    .join(" · ")
  return (
    <li>
      <a
        href={sessionHref(session.provider, session.id)}
        className="flex items-start justify-between gap-3 px-5 py-3.5 hover:bg-muted"
      >
        <div className="min-w-0 space-y-1">
          <div className="text-[14px] leading-snug font-medium break-words">{session.name}</div>
          <div className="label-mono text-[11px] text-muted-foreground">{meta}</div>
          {session.last && (
            <p className="line-clamp-2 text-[13px] leading-snug text-ink-2">{session.last}</p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <StatusBadge status={state.status} label={state.label} />
          {session.jobs > 0 && (
            <span className="label-mono inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              <Activity className="size-3.5" aria-hidden />
              {session.jobs === 1 ? "1 job" : `${session.jobs} jobs`}
            </span>
          )}
        </div>
      </a>
    </li>
  )
}

/** Every live session of Claude Code and Codex, those waiting for you first. */
export function SessionsScreen() {
  const found = useSessions()
  const sessions = found.data?.sessions ?? []
  const count = (state: Session["state"]) => sessions.filter((s) => s.state === state).length
  const summary = [
    [count("waiting"), "waiting for you"],
    [count("working"), "working"],
    [count("idle"), "idle"],
  ]
    .filter(([n]) => n)
    .map(([n, what]) => `${n} ${what}`)
    .join(" · ")
  return (
    <main className="mx-auto max-w-[960px] space-y-5 p-4 md:p-6">
      <header className="space-y-1">
        <Eyebrow>Sessions</Eyebrow>
        <h1 className="text-[22px] leading-tight">Every conversation, live</h1>
        {summary && <p className="text-sm text-muted-foreground">{summary}</p>}
      </header>
      {found.error && !found.data && (
        <div className="panel p-5 text-sm text-muted-foreground">
          The sessions didn't load: {found.error}
        </div>
      )}
      {found.data?.errors.map((error) => (
        <div key={error} className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <TriangleAlert className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
          {error}
        </div>
      ))}
      {!found.data && !found.error && (
        <p className="text-sm text-muted-foreground" role="status">
          Asking Claude Code and Codex…
        </p>
      )}
      {found.data && !sessions.length && (
        <p className="text-sm text-muted-foreground">No session of either tool is open.</p>
      )}
      {groupSessions(sessions).map((group) => (
        <section key={group.provider} className="space-y-2" aria-label={group.label}>
          <h2 className="text-[13px] font-medium text-muted-foreground">{group.label}</h2>
          <ul className="panel divide-y overflow-hidden">
            {group.sessions.map((s) => (
              <SessionRow key={s.id} session={s} />
            ))}
          </ul>
        </section>
      ))}
    </main>
  )
}

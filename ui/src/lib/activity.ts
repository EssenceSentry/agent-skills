import { runningNow, type Session, type SessionView, type Tasks } from "@/lib/sessions"

/** How long since `since`, as the desktop app counts it: "12s", "1m 16s", "1h 2m". */
export function elapsed(since: string | null | undefined, now = Date.now()): string {
  if (!since) return ""
  const seconds = Math.max(0, Math.floor((now - Date.parse(since)) / 1000))
  if (Number.isNaN(seconds)) return ""
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

/**
 * The line under a working session: what it is doing and for how long, else the command
 * running, else just that it works. Nothing while it isn't working.
 */
export function workingLine(session: Session | null, view: SessionView, now = Date.now()) {
  if (session?.state !== "working") return null
  if (view.activity) return { text: view.activity.text, elapsed: elapsed(view.activity.since, now) }
  const running = runningNow(session, view)
  if (running) return { text: running.text, elapsed: elapsed(running.ts, now) }
  return { text: "Working", elapsed: "" }
}

export function taskCount(tasks: Tasks): string {
  const done = tasks.items.filter((t) => t.status === "completed").length
  return `${done} of ${tasks.items.length} done`
}

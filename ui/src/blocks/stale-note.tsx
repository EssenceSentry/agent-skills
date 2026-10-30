import { CloudOff } from "lucide-react"

import { ago } from "@/lib/time"

/**
 * A line over what ax last said, once it stops answering: the states, usage and sessions
 * shown are its last reading, which may be out of date, and how old it is. Nothing while
 * ax answers.
 */
export function StaleNote({
  error,
  at,
  now,
}: {
  error?: string
  /** When ax last answered. */
  at?: string
  now?: number
}) {
  if (!error) return null
  return (
    <p
      role="status"
      title={error}
      className="chat-stale m-0 flex items-start gap-1.5 rounded-lg px-2 py-1.5 text-[12px] text-muted-foreground"
    >
      <CloudOff className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
      <span>
        ax isn't answering, so this may be out of date
        {at ? ` (last read ${ago(at, now)})` : ""}.
      </span>
    </p>
  )
}

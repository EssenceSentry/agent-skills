import { useState } from "react"
import type { PendingMessage } from "@/lib/sessions"

export function PendingMessages({
  messages,
  busy,
  run,
}: {
  messages: PendingMessage[]
  busy: boolean
  run: (payload: Record<string, unknown>) => void
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const [text, setText] = useState("")
  return (
    <div className="space-y-2">
      {messages.map((message) => (
        <section
          key={message.id}
          className="rounded-lg border bg-card p-2 text-xs"
          aria-label="Pending message"
        >
          <p>
            {message.delivery} · {message.status}: {message.text || "Attachments"}
            {message.attachments ? ` · ${message.attachments} picture(s)` : ""}
          </p>
          {message.error && <p className="text-critical">{message.error}</p>}
          {editing === message.id ? (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                run({ action: "pending-edit", message_id: message.id, text })
                setEditing(null)
              }}
            >
              <textarea
                aria-label="Edit pending message"
                className="my-2 w-full rounded border bg-background p-2"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
              <button type="submit" disabled={busy}>
                Save pending message
              </button>
              <button type="button" onClick={() => setEditing(null)}>
                Keep original
              </button>
            </form>
          ) : (
            message.status !== "dispatching" && (
              <div className="mt-1 flex flex-wrap gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setEditing(message.id)
                    setText(message.text)
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run({ action: "pending-cancel", message_id: message.id })}
                >
                  {message.status === "uncertain"
                    ? "Dismiss unconfirmed record"
                    : "Cancel pending delivery"}
                </button>
                {message.status !== "queued" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => run({ action: "pending-retry", message_id: message.id })}
                  >
                    {message.status === "uncertain"
                      ? "Send again (may duplicate delivery)"
                      : "Retry"}
                  </button>
                )}
              </div>
            )
          )}
        </section>
      ))}
    </div>
  )
}

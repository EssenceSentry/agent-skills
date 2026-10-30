import { useState } from "react"
import { chatAct, hurry } from "@/lib/ax"
import { usePreferences } from "@/lib/preferences"
import type { Session } from "@/lib/sessions"
import { askExtension, inExtension, request } from "@/lib/transport"

type FileDiff = { path: string; diff: string; revision: string }
type Changes = { files: FileDiff[]; skipped: { path: string; reason: string }[]; coverage: string }

export function ChangeReview({ session }: { session: Session }) {
  const [base, setBase] = useState("turn")
  const [changes, setChanges] = useState<Changes | null>(null)
  const [comments, setComments] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const preferences = usePreferences()
  const load = async () => {
    setBusy(true)
    setError(null)
    try {
      if (preferences.reviewMode === "detached" && inExtension())
        await askExtension("showChanges", { ...session, base })
      else {
        const query = new URLSearchParams({
          provider: session.provider,
          id: session.id,
          cwd: session.cwd ?? "",
          base,
        })
        setChanges(await request("GET", `/api/session/diff?${query}`))
        setComments({})
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const send = async () => {
    const review_comments = (changes?.files ?? []).flatMap((file) =>
      Object.entries(comments)
        .filter(([key, text]) => key.startsWith(`${file.path}:`) && text.trim())
        .map(([key, text]) => ({
          path: file.path,
          revision: file.revision,
          text,
          hunk: key.slice(file.path.length + 1),
        }))
    )
    setBusy(true)
    try {
      await chatAct({
        action: "review-feedback",
        provider: session.provider,
        id: session.id,
        cwd: session.cwd,
        name: session.name,
        review_comments,
        client_message_id: crypto.randomUUID(),
      })
      setComments({})
      hurry()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <details className="text-xs">
      <summary className="cursor-pointer">Review file changes</summary>
      <div className="my-2 flex flex-wrap items-center gap-2">
        <select value={base} onChange={(e) => setBase(e.target.value)}>
          <option value="turn">This turn · provider history</option>
          <option value="session">This session · provider history</option>
          <option value="commit">Workspace since commit</option>
        </select>
        <button type="button" disabled={busy} onClick={() => void load()}>
          Show diff
        </button>
      </div>
      {changes && (
        <section>
          <p className="my-2 text-muted-foreground">{changes.coverage}</p>
          {!changes.files.length && <p>No differing text files found.</p>}
          {changes.files.map((file) => (
            <details key={file.path} className="my-2 rounded border p-2">
              <summary className="cursor-pointer break-all">{file.path}</summary>
              {file.diff.split(/(?=^@@)/m).map((hunk, index) => {
                const key = `${file.path}:${index === 0 ? "file" : hunk.split("\n")[0]}`
                return (
                  <div key={key} className="my-2">
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap">{hunk}</pre>
                    <textarea
                      aria-label={`Review comment for ${file.path}, ${index === 0 ? "file" : `hunk ${index}`}`}
                      placeholder={index === 0 ? "Comment on this file…" : "Comment on this hunk…"}
                      className="my-1 w-full rounded border bg-card p-2"
                      value={comments[key] ?? ""}
                      onChange={(e) => setComments({ ...comments, [key]: e.target.value })}
                    />
                  </div>
                )
              })}
            </details>
          ))}
          {changes.skipped.map((file) => (
            <p key={file.path}>
              {file.path}: {file.reason}
            </p>
          ))}
          <button
            type="button"
            disabled={busy || !Object.values(comments).some((text) => text.trim())}
            onClick={() => void send()}
          >
            Send review feedback
          </button>
        </section>
      )}
      {error && (
        <p role="alert" className="text-critical">
          {error}
        </p>
      )}
    </details>
  )
}

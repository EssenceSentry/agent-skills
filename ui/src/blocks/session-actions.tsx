import { useState } from "react"
import { chatAct, hurry } from "@/lib/ax"
import type { Session, TranscriptEvent } from "@/lib/sessions"
import { askExtension, inExtension, request } from "@/lib/transport"

type Restore = {
  token: string
  files: { path: string; diff: string }[]
  skipped: { path: string; reason: string }[]
  coverage: string
}

export function SessionActions({ session, point }: { session: Session; point?: TranscriptEvent }) {
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState(session.name)
  const [group, setGroup] = useState(session.group ?? "")
  const [restore, setRestore] = useState<Restore | null>(null)
  const [paths, setPaths] = useState<string[]>([])
  const [authUrl, setAuthUrl] = useState<string | null>(null)
  const [catalog, setCatalog] = useState<Record<string, unknown> | null>(null)
  const base = { provider: session.provider, id: session.id, cwd: session.cwd, name: session.name }
  const run = async (action: string, extra: Record<string, unknown> = {}) => {
    setBusy(true)
    setError(null)
    try {
      const result = (await chatAct({ ...base, action, ...extra })) as unknown as {
        message?: string
        id?: string
        provider?: string
      } & Restore
      if ("authorizationUrl" in result && typeof result.authorizationUrl === "string")
        setAuthUrl(result.authorizationUrl)
      if (action === "restore-preview") {
        setRestore(result)
        setPaths(result.files.map((f) => f.path))
      }
      if (action === "fork" && result.id && extra.open !== false) {
        if (inExtension())
          await askExtension("openSession", {
            provider: session.provider,
            id: result.id,
            name: `${session.name} (fork)`,
          })
        else location.hash = `#/sessions/${session.provider}/${result.id}`
      }
      setNote(result.message ?? null)
      hurry()
      return result
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const target = point
    ? session.provider === "claude"
      ? point.native_id
      : point.turn_id
    : undefined
  const forkArgs = point ? { message_id: point.native_id, turn_id: point.turn_id } : {}
  const loadCatalog = async () => {
    setBusy(true)
    try {
      setCatalog(
        await request(
          "GET",
          `/api/session/catalog?${new URLSearchParams({ ...base, cwd: session.cwd ?? "" })}`
        )
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <details className="text-xs" data-session-actions={!point ? true : undefined}>
      <summary className="cursor-pointer text-muted-foreground">
        {point ? "Fork or restore from here" : "Session actions"}
      </summary>
      <div className="my-2 space-y-3 rounded-lg border bg-card p-3">
        {!point && (
          <>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                void run("rename", { name })
              }}
            >
              <input
                className="min-w-0 flex-1 rounded border bg-background p-1"
                aria-label="Session name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <button disabled={busy} type="submit">
                Rename
              </button>
            </form>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                void run("group", { group })
              }}
            >
              <input
                className="min-w-0 flex-1 rounded border bg-background p-1"
                aria-label="Session group"
                value={group}
                onChange={(e) => setGroup(e.target.value)}
              />
              <button disabled={busy} type="submit">
                Set group
              </button>
            </form>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => void run("order", { order: (session.order ?? 0) - 1 })}
              >
                Move earlier in list
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void run("order", { order: (session.order ?? 0) + 1 })}
              >
                Move later in list
              </button>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => void run("pin", { pinned: !session.pinned })}
              >
                {session.pinned ? "Unpin" : "Pin"}
              </button>
              <button
                type="button"
                disabled={busy || session.state === "working"}
                onClick={() => void run(session.archived ? "unarchive" : "archive")}
              >
                {session.archived ? "Unarchive" : "Archive"}
              </button>
              <button
                type="button"
                disabled={busy || session.state === "working"}
                onClick={() => void run("compact")}
              >
                Compact context
              </button>
              <button
                type="button"
                disabled={busy || session.state === "working"}
                onClick={() => void run("review")}
              >
                Review workspace changes
              </button>
              <button type="button" disabled={busy} onClick={() => void loadCatalog()}>
                Skills, MCP, apps and plugins
              </button>
            </div>
          </>
        )}
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            disabled={busy || Boolean(point && !target)}
            onClick={() => void run("fork", forkArgs)}
          >
            Fork {point ? "from here" : "conversation"}
          </button>
          <button
            type="button"
            disabled={busy || Boolean(point && !target)}
            onClick={() => void run("restore-preview", { target })}
          >
            Preview file restore
          </button>
        </div>
        {point && !target && <p>This record has no provider checkpoint identifier.</p>}
        {restore && (
          <section className="space-y-2">
            <p>{restore.coverage}</p>
            {restore.files.map((file) => (
              <details key={file.path}>
                <summary>
                  <label>
                    <input
                      type="checkbox"
                      checked={paths.includes(file.path)}
                      onChange={(e) =>
                        setPaths((was) =>
                          e.target.checked
                            ? [...was, file.path]
                            : was.filter((p) => p !== file.path)
                        )
                      }
                    />{" "}
                    {file.path}
                  </label>
                </summary>
                <pre className="max-h-60 overflow-auto whitespace-pre-wrap">{file.diff}</pre>
              </details>
            ))}
            {restore.skipped.map((file) => (
              <p key={file.path}>
                {file.path}: {file.reason}
              </p>
            ))}
            <button
              type="button"
              disabled={busy || !paths.length}
              onClick={() => void run("restore-apply", { token: restore.token, paths })}
            >
              Restore selected files
            </button>
            <button
              type="button"
              disabled={busy || !paths.length}
              onClick={async () => {
                const fork = await run("fork", { ...forkArgs, open: false })
                if (fork?.id) {
                  const applied = await run("restore-apply", { token: restore.token, paths })
                  if (applied) {
                    if (inExtension())
                      await askExtension("openSession", { provider: session.provider, id: fork.id })
                    else location.hash = `#/sessions/${session.provider}/${fork.id}`
                  }
                }
              }}
            >
              Fork and restore selected files
            </button>
          </section>
        )}
        {catalog && (
          <section className="space-y-2">
            <h3 className="font-medium">Installed capabilities</h3>
            {session.provider === "codex" && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void run("capability", { operation: "refresh-mcp" })}
              >
                Reload MCP configuration
              </button>
            )}
            {Array.isArray(catalog.plugins) &&
              catalog.plugins.map((entry) => {
                const plugin =
                  typeof entry === "string"
                    ? { name: entry, enabled: undefined }
                    : (entry as { name: string; enabled?: boolean })
                return (
                  <div key={plugin.name} className="flex flex-wrap items-center gap-2">
                    <span>Plugin · {plugin.name}</span>
                    {session.provider === "claude" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void run("capability", {
                            operation: "plugin-enabled",
                            plugin: plugin.name,
                            enabled: !plugin.enabled,
                          })
                        }
                      >
                        {plugin.enabled ? "Disable for new sessions" : "Enable for new sessions"}
                      </button>
                    )}
                  </div>
                )
              })}
            {(() => {
              const skills = catalog.skills as
                | { skills?: { name: string; path?: string; enabled?: boolean }[] }
                | undefined
              return skills?.skills?.map((skill) => (
                <div key={skill.name}>
                  {skill.name}
                  {skill.path && session.provider === "codex" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void run("capability", {
                          operation: "skill-enabled",
                          path: skill.path,
                          enabled: skill.enabled === false,
                        })
                      }
                    >
                      {skill.enabled === false ? "Enable skill" : "Disable skill"}
                    </button>
                  )}
                </div>
              ))
            })()}
            {(() => {
              const servers = catalog.mcp as
                | { data?: { name: string; authStatus?: string }[] }
                | undefined
              return servers?.data?.map((item) => (
                <div key={item.name} className="flex flex-wrap gap-2">
                  <span>
                    MCP · {item.name} · {item.authStatus ?? "status unknown"}
                  </span>
                  {session.provider === "codex" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void run("capability", { operation: "mcp-login", server_name: item.name })
                      }
                    >
                      Sign in
                    </button>
                  )}
                </div>
              ))
            })()}

            {Object.entries(catalog).map(([key, value]) => (
              <details key={key}>
                <summary>{key}</summary>
                <pre className="max-h-60 overflow-auto whitespace-pre-wrap">
                  {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
                </pre>
              </details>
            ))}
            <button type="button" onClick={() => void loadCatalog()}>
              Refresh status
            </button>
          </section>
        )}
        {authUrl && (
          <a href={authUrl} target="_blank" rel="noreferrer" className="underline">
            Authorize the MCP connection
          </a>
        )}
        {note && <p role="status">{note}</p>}
        {error && (
          <p className="text-critical" role="alert">
            {error}
          </p>
        )}
      </div>
    </details>
  )
}

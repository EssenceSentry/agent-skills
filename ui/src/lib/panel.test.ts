import { describe, expect, it } from "vitest"

import { folderChoices, keptOrder, panelRows, since, unanswered } from "@/lib/panel"
import type { Session } from "@/lib/sessions"

const NOW = Date.parse("2026-10-27T12:00:00Z")
const at = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString()

const session = (over: Partial<Session>): Session => ({
  provider: "claude",
  id: "s",
  name: "A session",
  cwd: "/Users/me/Repos/app",
  project: "app",
  state: "idle",
  waiting_for: null,
  kind: null,
  started: null,
  updated: at(5),
  last: null,
  jobs: 0,
  ...over,
})

describe("the sessions on the right, as Codex lists its chats", () => {
  it("says how long ago in the fewest letters", () => {
    expect(since(at(0), NOW)).toBe("now")
    expect(since(at(5), NOW)).toBe("5m")
    expect(since(at(90), NOW)).toBe("1h")
    expect(since(at(60 * 24 * 5), NOW)).toBe("5d")
    expect(since(null, NOW)).toBe("")
  })

  it("puts what waits for you first, then what works, newest first within each", () => {
    const rows = panelRows(
      [
        session({ id: "old", updated: at(600) }),
        session({ id: "busy", state: "working", updated: at(30) }),
        session({ id: "asks", state: "waiting", waiting_for: "approval", updated: at(60) }),
        session({ id: "new", updated: at(1) }),
      ],
      NOW
    )
    expect(rows.map((r) => r.id)).toEqual(["asks", "busy", "new", "old"])
    expect(rows[0]).toMatchObject({ status: "Needs approval", when: "1h", tool: "Claude Code" })
    expect(rows[1].status).toBe("Working")
  })

  it("offers the workspace's folders, then the folders of recent sessions, each once", () => {
    const found = folderChoices(
      ["/Users/me/Repos/app", "/Users/me/Repos/lib"],
      [
        session({ cwd: "/Users/me/Repos/app" }),
        session({ cwd: "/Users/me/Repos/notes", updated: at(1) }),
        session({ cwd: "/Users/me/Repos/old", updated: at(300) }),
        session({ cwd: null }),
      ],
      ""
    )
    expect(found.workspace.map((f) => f.label)).toEqual(["app", "lib"])
    expect(found.recent.map((f) => f.path)).toEqual([
      "/Users/me/Repos/notes",
      "/Users/me/Repos/old",
    ])
  })

  it("narrows the folders to the words searched", () => {
    const found = folderChoices(["/Users/me/Repos/app"], [session({ cwd: "/x/notes" })], "NOT")
    expect(found.workspace).toEqual([])
    expect(found.recent.map((f) => f.label)).toEqual(["notes"])
  })
})

describe("the list while you point at it", () => {
  const row = (id: string) =>
    ({ provider: "claude" as const, id }) as Parameters<typeof keptOrder>[0][number]

  it("keeps the order it had, so a row doesn't move under the pointer", () => {
    const now = [row("b"), row("a"), row("c")] // b started waiting, so it moved up
    expect(keptOrder(now, ["claude:a", "claude:b", "claude:c"]).map((r) => r.id)).toEqual([
      "a",
      "b",
      "c",
    ])
  })

  it("adds a new session at the end and drops one that ended", () => {
    const now = [row("d"), row("a")]
    expect(keptOrder(now, ["claude:a", "claude:b"]).map((r) => r.id)).toEqual(["a", "d"])
  })
})

describe("the list when ax doesn't answer", () => {
  it("says so once, whether or not the error already does", () => {
    const bridge = "ax isn't answering at http://127.0.0.1:8799: start it with `ax app start`"
    expect(unanswered(bridge)).toBe(bridge)
    expect(unanswered("Failed to fetch")).toBe("ax isn't answering: Failed to fetch")
  })
})

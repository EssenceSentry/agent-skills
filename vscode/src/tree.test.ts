import { describe, expect, it } from "vitest"

import { type Session, sessionTree, type TreeNode, waitingCount } from "./tree"

const NOW = Date.parse("2026-10-27T12:00:00Z")

function session(over: Partial<Session>): Session {
  return {
    provider: "claude",
    id: "s1",
    name: "A session",
    cwd: "/Users/me/Repos/demo",
    project: "demo",
    state: "idle",
    waiting_for: null,
    updated: "2026-10-27T11:00:00Z",
    last: null,
    ...over,
  }
}

const labels = (nodes: TreeNode[]): unknown[] =>
  nodes.map((n) => (n.kind === "group" ? [n.label, labels(n.children)] : n.label))

describe("the sessions tree", () => {
  it("groups sessions by tool, then project, waiting ones first", () => {
    const tree = sessionTree(
      {
        sessions: [
          session({ id: "a", name: "Idle demo", updated: "2026-10-27T11:59:00Z" }),
          session({ id: "b", name: "Working demo", state: "working" }),
          session({ id: "c", name: "Waiting demo", state: "waiting", waiting_for: "input" }),
          session({ id: "d", name: "Other project", project: "web", cwd: "/Users/me/web" }),
          session({ id: "e", name: "Codex thread", provider: "codex", project: "web" }),
        ],
        errors: [],
      },
      NOW
    )
    expect(labels(tree)).toEqual([
      [
        "Claude Code",
        [
          ["demo", ["Waiting demo", "Working demo", "Idle demo"]],
          ["web", ["Other project"]],
        ],
      ],
      ["Codex", [["web", ["Codex thread"]]]],
    ])
  })

  it("puts a project with a session waiting above the others", () => {
    const tree = sessionTree(
      {
        sessions: [
          session({ id: "a", project: "fresh", updated: "2026-10-27T11:59:00Z" }),
          session({
            id: "b",
            project: "needs-you",
            state: "waiting",
            updated: "2026-10-26T10:00:00Z",
          }),
        ],
        errors: [],
      },
      NOW
    )
    const claude = tree[0]
    expect(claude?.kind === "group" && claude.children.map((p) => p.label)).toEqual([
      "needs-you",
      "fresh",
    ])
  })

  it("names a project by its folder when the listing has no project", () => {
    const tree = sessionTree(
      { sessions: [session({ project: null, cwd: "/a/b/scratch" })], errors: [] },
      NOW
    )
    expect(labels(tree)).toEqual([["Claude Code", [["scratch", ["A session"]]]]])
  })

  it("says what a waiting session needs, and how long ago an idle one spoke", () => {
    const [claude] = sessionTree(
      {
        sessions: [
          session({ id: "a", state: "waiting", waiting_for: "approval" }),
          session({ id: "b", state: "waiting", waiting_for: "input needed" }),
          session({ id: "c", state: "working" }),
          session({ id: "d", updated: "2026-10-27T11:48:00Z" }),
          session({ id: "e", updated: "2026-10-27T09:00:00Z" }),
          session({ id: "f", updated: "2026-10-24T12:00:00Z" }),
          session({ id: "g", updated: "2026-10-27T11:59:40Z" }),
        ],
        errors: [],
      },
      NOW
    )
    const shown = claude?.kind === "group" ? claude.children[0] : undefined
    const described =
      shown?.kind === "group"
        ? shown.children.map((s) => s.kind === "session" && s.description)
        : []
    expect(described).toEqual([
      "Needs approval",
      "Waiting for you",
      "Working",
      "just now",
      "12 min ago",
      "3 h ago",
      "3 d ago",
    ])
  })

  it("gives working, waiting and idle sessions their own icons", () => {
    const tree = sessionTree(
      {
        sessions: [
          session({ id: "a", state: "waiting" }),
          session({ id: "b", state: "working" }),
          session({ id: "c", state: null }),
        ],
        errors: [],
      },
      NOW
    )
    const project = tree[0]?.kind === "group" ? tree[0].children[0] : undefined
    const icons =
      project?.kind === "group" ? project.children.map((s) => s.kind === "session" && s.icon) : []
    expect(icons).toEqual([
      { id: "bell-dot", color: "list.warningForeground" },
      { id: "sync~spin" },
      { id: "circle-outline" },
    ])
  })

  it("keeps what opens a session, and its last words for the tooltip", () => {
    const tree = sessionTree(
      {
        sessions: [
          session({ provider: "codex", id: "t-9", name: "Fix it", last: "Done: the axis fits." }),
        ],
        errors: [],
      },
      NOW
    )
    const project = tree[0]?.kind === "group" ? tree[0].children[0] : undefined
    const item = project?.kind === "group" ? project.children[0] : undefined
    expect(item).toMatchObject({
      kind: "session",
      key: "codex:t-9",
      provider: "codex",
      id: "t-9",
      tooltip: "Fix it\nDone: the axis fits.\n/Users/me/Repos/demo",
    })
  })

  it("counts the sessions waiting for you, per tool and for the badge", () => {
    const listing = {
      sessions: [
        session({ id: "a", state: "waiting" }),
        session({ id: "b", state: "waiting", provider: "codex" }),
        session({ id: "c", state: "working" }),
      ],
      errors: [],
    }
    expect(waitingCount(listing)).toBe(2)
    expect(sessionTree(listing, NOW).map((g) => g.kind === "group" && g.description)).toEqual([
      "1 waiting",
      "1 waiting",
    ])
  })

  it("says when there are no sessions, and passes on what the listing couldn't read", () => {
    expect(sessionTree({ sessions: [], errors: [] }, NOW)).toEqual([
      { kind: "message", key: "empty", label: "No live sessions", icon: { id: "info" } },
    ])
    const tree = sessionTree(
      { sessions: [session({})], errors: ["codex: the app-server didn't answer"] },
      NOW
    )
    expect(tree.at(-1)).toEqual({
      kind: "message",
      key: "error:0",
      label: "codex: the app-server didn't answer",
      icon: { id: "warning", color: "list.warningForeground" },
    })
  })

  it("says when the ax server isn't answering, and how to start it", () => {
    expect(sessionTree({ error: "fetch failed" }, NOW)).toEqual([
      {
        kind: "message",
        key: "offline",
        label: "ax isn't answering: start it with `ax app start`",
        tooltip: "fetch failed",
        icon: { id: "warning", color: "list.warningForeground" },
      },
    ])
  })
})

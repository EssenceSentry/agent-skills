import { describe, expect, it } from "vitest"

import { offScreen, revealIn, type Session, tabIcon, tabState, waitingCount } from "./listing"

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

describe("the listing", () => {
  it("counts the sessions waiting for you, of both tools, for the badge", () => {
    const sessions = [
      session({ id: "a", state: "waiting" }),
      session({ id: "b", state: "waiting", provider: "codex" }),
      session({ id: "c", state: "working" }),
    ]
    expect(waitingCount({ sessions, errors: [] })).toBe(2)
  })
})

describe("a session's tab", () => {
  it("shows what the session is doing: waiting for you, working, or neither", () => {
    expect(tabIcon("waiting")).toBe("tab-waiting.svg")
    expect(tabIcon("working")).toBe("tab-working.svg")
    expect(tabIcon("idle")).toBe("tab.svg")
    expect(tabIcon(null)).toBe("tab.svg")
  })
})

describe("a session that already has a tab", () => {
  const BESIDE = -2 // VS Code's ViewColumn.Beside
  it("moves beside the one in front when asked to open to the side", () => {
    expect(revealIn(1, BESIDE)).toBe(BESIDE)
  })

  it("comes forward where it is otherwise", () => {
    expect(revealIn(3, -1)).toBe(3) // ViewColumn.Active: wherever the tab already is
    expect(revealIn(undefined, -1)).toBe(-1)
  })
})

describe("session tabs you aren't watching", () => {
  it("are the ones behind another tab in their column; the one in front of each stays", () => {
    const tabs = [
      { name: "a", visible: true },
      { name: "b", visible: false },
      { name: "c", visible: true },
      { name: "d", visible: false },
    ]
    expect(offScreen(tabs).map((t) => t.name)).toEqual(["b", "d"])
    expect(offScreen([{ name: "a", visible: true }])).toEqual([])
  })
})

describe("the state a tab's icon shows", () => {
  const NOW = 100_000

  it("is what the tab's own page reported, the moment you act there", () => {
    expect(tabState("waiting", { state: "working", at: NOW - 2_000 }, NOW)).toBe("working")
  })

  it("is the listing's once the page's report is a few seconds old, or without one", () => {
    expect(tabState("idle", { state: "working", at: NOW - 30_000 }, NOW)).toBe("idle")
    expect(tabState("waiting", undefined, NOW)).toBe("waiting")
  })
})

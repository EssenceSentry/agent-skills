import { describe, expect, it } from "vitest"

import { newlyWaiting, notice } from "./notify"
import type { Listing, Session } from "./tree"

function session(over: Partial<Session>): Session {
  return {
    provider: "claude",
    id: "s1",
    name: "Fix the axis",
    cwd: "/Users/me/Repos/demo",
    project: "demo",
    state: "working",
    waiting_for: null,
    updated: null,
    last: null,
    ...over,
  }
}

const listing = (...sessions: Session[]): Listing => ({ sessions, errors: [] })

describe("which sessions to announce", () => {
  it("announces nothing on the first reading: the badge counts those already waiting", () => {
    expect(newlyWaiting(null, listing(session({ state: "waiting" })))).toEqual([])
  })

  it("announces a session that starts waiting, once", () => {
    const working = listing(session({ id: "a" }), session({ id: "b", state: "idle" }))
    const waits = listing(
      session({ id: "a", state: "waiting" }),
      session({ id: "b", state: "idle" })
    )
    expect(newlyWaiting(working, waits).map((s) => s.id)).toEqual(["a"])
    expect(newlyWaiting(waits, waits)).toEqual([])
  })

  it("announces a new session that is already waiting, and one that waits again", () => {
    const before = listing(session({ id: "a", state: "working" }))
    const after = listing(
      session({ id: "a", state: "waiting" }),
      session({ id: "new", provider: "codex", state: "waiting" })
    )
    expect(newlyWaiting(before, after).map((s) => s.id)).toEqual(["a", "new"])
  })

  it("tells a Claude session from a Codex one with the same id", () => {
    const before = listing(session({ id: "x", provider: "claude", state: "waiting" }))
    const after = listing(
      session({ id: "x", provider: "claude", state: "waiting" }),
      session({ id: "x", provider: "codex", state: "waiting" })
    )
    expect(newlyWaiting(before, after).map((s) => s.provider)).toEqual(["codex"])
  })
})

describe("what the notice says", () => {
  it("names the session and what it needs, with its last words", () => {
    expect(
      notice(session({ state: "waiting", waiting_for: "approval", last: "Run the migration?" }))
    ).toBe("Fix the axis needs your approval: Run the migration?")
    expect(notice(session({ state: "waiting", waiting_for: "input needed" }))).toBe(
      "Fix the axis is waiting for you"
    )
  })

  it("keeps long last words short", () => {
    const said = notice(session({ state: "waiting", last: "x".repeat(300) }))
    expect(said.length).toBeLessThanOrEqual(160)
    expect(said.endsWith("…")).toBe(true)
  })
})

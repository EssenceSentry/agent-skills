import { describe, expect, it } from "vitest"

import { elapsed, taskCount, workingLine } from "@/lib/activity"
import type { Session, SessionView } from "@/lib/sessions"

const NOW = Date.parse("2026-10-27T12:01:16Z")

const session = (state: Session["state"]): Session => ({
  provider: "claude",
  id: "s",
  name: "s",
  cwd: null,
  project: null,
  state,
  waiting_for: null,
  kind: null,
  started: null,
  updated: null,
  last: null,
  jobs: 0,
})

function view(over: Partial<SessionView>): SessionView {
  return {
    session: session("working"),
    events: [],
    next: 0,
    first: 0,
    running: [],
    earlier: 0,
    cards: [],
    ...over,
  }
}

describe("how long it has been at it", () => {
  it("counts seconds, then minutes and seconds, then hours and minutes", () => {
    expect(elapsed("2026-10-27T12:01:04Z", NOW)).toBe("12s")
    expect(elapsed("2026-10-27T12:00:00Z", NOW)).toBe("1m 16s")
    expect(elapsed("2026-10-27T10:59:00Z", NOW)).toBe("1h 2m")
    expect(elapsed("2026-10-27T12:02:00Z", NOW)).toBe("0s")
    expect(elapsed(null, NOW)).toBe("")
  })
})

describe("the working line", () => {
  it("says what it is doing and for how long, while it works", () => {
    const line = workingLine(
      session("working"),
      view({ activity: { text: "Listing the uncommitted work", since: "2026-10-27T12:00:00Z" } }),
      NOW
    )
    expect(line).toEqual({ text: "Listing the uncommitted work", elapsed: "1m 16s" })
  })

  it("falls back to the command running, then to working", () => {
    const running = view({
      running: [
        {
          i: 3,
          kind: "tool",
          text: "ran `pytest`",
          tool: "Bash",
          ok: null,
          output: "",
          ts: "2026-10-27T12:01:00Z",
        },
      ],
    })
    expect(workingLine(session("working"), running, NOW)).toEqual({
      text: "ran `pytest`",
      elapsed: "16s",
    })
    expect(workingLine(session("working"), view({}), NOW)).toEqual({ text: "Working", elapsed: "" })
  })

  it("is nothing while it isn't working", () => {
    const busy = view({ activity: { text: "Reading a.py", since: "2026-10-27T12:00:00Z" } })
    expect(workingLine(session("idle"), busy, NOW)).toBeNull()
    expect(workingLine(session("waiting"), busy, NOW)).toBeNull()
  })
})

describe("the task list", () => {
  it("counts the steps done", () => {
    expect(
      taskCount({
        items: [
          { text: "a", status: "completed" },
          { text: "b", status: "in_progress" },
          { text: "c", status: "pending" },
        ],
        explanation: null,
      })
    ).toBe("1 of 3 done")
  })
})

import { describe, expect, it } from "vitest"

import type { Session } from "./listing"
import { focusTaken, hitItem, liveItems, narrowing, searchUrl } from "./searchPick"

const NOW = new Date(2026, 9, 27, 12).getTime()

describe("ax's search at the top centre", () => {
  it("shows a conversation by its title, the tool, project and when, and what was said", () => {
    const item = hitItem(
      {
        source: "conversation",
        path: "/vault/Sessions/2026-08-22 codex auto-classifier - Review (01a0298f).md",
        title: "Review Tk gallery UI UX",
        snippet: "You: Review the live Tk gallery as an operational workflow",
        session: "01a0298f-ddc0-7451-8a3b-8596e8eca071",
        provider: "codex",
        project: "auto-classifier",
        date: "2026-08-22",
        started: new Date(2026, 7, 22, 10, 1).toISOString(),
      },
      NOW
    )
    expect(item.label).toBe("$(comment-discussion) Review Tk gallery UI UX")
    expect(item.description).toBe("Codex · auto-classifier · Aug 22, 10:01")
    expect(item.detail).toBe("You: Review the live Tk gallery as an operational workflow")
    expect(item.alwaysShow).toBe(true) // found by meaning too: never hidden by the typed words
    expect(item.open).toEqual({
      session: {
        provider: "codex",
        id: "01a0298f-ddc0-7451-8a3b-8596e8eca071",
        name: "Review Tk gallery UI UX",
      },
    })
  })

  it("says when a conversation was as a person would", () => {
    const on = (date: string) =>
      hitItem(
        {
          source: "conversation",
          path: "/n.md",
          title: "t",
          snippet: "",
          provider: "claude",
          date,
        },
        NOW
      ).description
    expect(on("2026-10-27")).toBe("Claude · today")
    expect(on("2026-10-26")).toBe("Claude · yesterday")
    expect(on("2026-10-24")).toBe("Claude · 3 days ago")
    expect(on("2025-12-30")).toBe("Claude · Dec 30, 2025")
    const began = (started: Date) =>
      hitItem(
        {
          source: "conversation",
          path: "/n.md",
          title: "t",
          snippet: "",
          provider: "claude",
          started: started.toISOString(),
        },
        NOW
      ).description
    expect(began(new Date(2026, 9, 27, 9, 5))).toBe("Claude · today 09:05")
    expect(began(new Date(2026, 9, 24, 18, 30))).toBe("Claude · Sat 18:30")
  })

  it("shows a memory by its name and project", () => {
    const memory = hitItem(
      {
        source: "memory",
        path: "/m/agent-tooling.md",
        title: "agent-tooling",
        snippet: "The agent layer",
        project: "ds-models",
      },
      NOW
    )
    expect([memory.label, memory.description, memory.detail]).toEqual([
      "$(lightbulb) agent-tooling",
      "Memory · ds-models",
      "The agent layer",
    ])
    expect(memory.open).toEqual({ file: "/m/agent-tooling.md" })
  })

  it("lists the live sessions before anything is typed, those waiting first", () => {
    const session = (name: string, state: Session["state"]): Session => ({
      provider: "claude",
      id: name,
      name,
      cwd: "/repo",
      project: "repo",
      state,
      waiting_for: state === "waiting" ? "approval" : null,
      updated: null,
      last: null,
    })
    const items = liveItems([session("Idle one", "idle"), session("Asks you", "waiting")])
    expect(items.map((i) => i.label)).toEqual([
      "$(bell-dot) Asks you",
      "$(comment-discussion) Idle one",
    ])
    expect(items[0]?.description).toBe("Claude Code · repo · waiting for you")
    // Typing narrows them to what matches while the search runs, so Enter can't open a
    // session that has nothing to do with the words.
    expect(items.every((i) => !i.alwaysShow)).toBe(true)
  })

  it("narrows the rows already shown to what is typed while a new search runs", () => {
    const shown = [
      hitItem({ source: "memory", path: "/m/a.md", title: "usage", snippet: "" }, NOW),
      { label: "$(search) Nothing found for “usage”", alwaysShow: true as const },
    ]
    const waiting = narrowing(shown)
    expect(waiting.map((r) => r.label)).toEqual(shown.map((r) => r.label))
    expect(waiting.every((r) => !r.alwaysShow)).toBe(true) // Enter can't open an old answer
  })

  it("comes back once when a page's menu takes the focus back as it opens", () => {
    expect(focusTaken({ openFor: 151, accepted: false, reopened: false })).toBe(true)
    expect(focusTaken({ openFor: 151, accepted: false, reopened: true })).toBe(false) // once
    expect(focusTaken({ openFor: 151, accepted: true, reopened: false })).toBe(false)
    expect(focusTaken({ openFor: 2000, accepted: false, reopened: false })).toBe(false) // Escape
  })

  it("asks for the keyword stage and the whole search", () => {
    expect(searchUrl("status bar", true)).toBe("/api/find?q=status%20bar&fast=1")
    expect(searchUrl("status bar", false)).toBe("/api/find?q=status%20bar")
  })
})

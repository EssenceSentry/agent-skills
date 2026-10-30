import { describe, expect, it } from "vitest"

import { offlineStatus, usageStatus } from "./usage"

const NOW = Date.parse("2026-10-27T12:00:00Z")
const at = (day: number, hour: number, minute = 0) =>
  new Date(2026, 9, day, hour, minute).toISOString()
const light = (text: string) =>
  `<span style="color:var(--vscode-descriptionForeground);"><small>${text}</small></span>`

describe("usage in the status bar", () => {
  it("shows each tool's weekly window by its icon", () => {
    const shown = usageStatus(
      [
        {
          provider: "claude",
          window: "session",
          used: 45,
          status: "fresh",
          resets_at: "2026-10-27T14:00:00Z",
        },
        {
          provider: "codex",
          window: "weekly",
          used: 96,
          status: "fresh",
          resets_at: "2026-10-30T12:00:00Z",
        },
      ],
      [],
      NOW
    )
    expect(shown.text).toBe("$(ax-claude) –  $(ax-codex) 96%") // Claude's week isn't read
  })

  it("stays plain, however close a window runs to its limit", () => {
    const shown = usageStatus(
      [
        {
          provider: "claude",
          window: "weekly",
          used: 80,
          status: "fresh",
          resets_at: "2026-10-31T12:00:00Z",
        },
        {
          provider: "codex",
          window: "weekly",
          used: 96,
          status: "fresh",
          resets_at: "2026-10-30T12:00:00Z",
        },
      ],
      [],
      NOW
    )
    expect(shown).not.toHaveProperty("background")
  })

  it("lists each tool's windows on hover under its name, with when each resets, lighter", () => {
    const now = Date.parse(at(27, 12))
    const shown = usageStatus(
      [
        { provider: "claude", window: "session", used: 45, status: "fresh", resets_at: at(27, 14) },
        {
          provider: "claude",
          window: "weekly_fable",
          used: 0,
          status: "fresh",
          resets_at: at(30, 0),
        },
        {
          provider: "codex",
          window: "weekly",
          used: 3.4,
          status: "stale",
          resets_at: at(30, 9, 5),
        },
      ],
      [{ provider: "codex", balance: 62430.8, unlimited: false }],
      now
    )
    expect(shown.tooltip).toBe(
      [
        "$(ax-claude) **Claude**  ",
        `Session: 45% used ${light("resets today at 2:00 PM")}  `,
        `Fable weekly: 0% used ${light("resets Fri, Oct 30 at 12:00 AM")}`,
        "",
        "$(ax-codex) **Codex**  ",
        `Weekly: 3% used ${light("resets Fri, Oct 30 at 9:05 AM")}  `,
        "Credits: 62,431",
      ].join("\n")
    )
  })

  it("says what it can't read", () => {
    const shown = usageStatus(
      [{ provider: "claude", window: "weekly", used: null, status: "stale", resets_at: null }],
      [],
      NOW
    )
    expect(shown.text).toBe("$(ax-claude) –  $(ax-codex) –")
    expect(shown.tooltip).toBe(
      [
        "$(ax-claude) **Claude**  ",
        "Weekly: not reported",
        "",
        "$(ax-codex) **Codex**  ",
        "not reported",
      ].join("\n")
    )
  })
})

describe("the status bar when ax isn't answering", () => {
  it("says so, and how to bring it back, instead of going blank", () => {
    const shown = offlineStatus("http://127.0.0.1:8765")
    expect(shown.text).toBe("$(debug-disconnect) ax")
    expect(shown.tooltip).toContain("ax isn't answering at http://127.0.0.1:8765")
    expect(shown.tooltip).toContain("ax app start")
  })
})

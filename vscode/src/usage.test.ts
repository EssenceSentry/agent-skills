import { describe, expect, it } from "vitest"

import { usageStatus } from "./usage"

const NOW = Date.parse("2026-10-27T12:00:00Z")

describe("usage in the status bar", () => {
  it("shows the most used window, coloured by the most urgent one", () => {
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
    expect(shown.text).toBe("$(dashboard) 96%")
    expect(shown.background).toBe("statusBarItem.errorBackground")
    expect(shown.tooltip).toEqual([
      "**Codex weekly 96% used**",
      "",
      "Claude session: 45% used · resets in 2 h 0 min",
      "Codex weekly: 96% used · 1.3% a day for 3 days",
    ])
  })

  it("warns without alarm when a window runs tight", () => {
    const shown = usageStatus(
      [
        {
          provider: "claude",
          window: "weekly",
          used: 80,
          status: "fresh",
          resets_at: "2026-10-31T12:00:00Z",
        },
      ],
      [],
      NOW
    )
    expect(shown.background).toBe("statusBarItem.warningBackground")
  })

  it("stays plain while there is room", () => {
    const shown = usageStatus(
      [
        {
          provider: "claude",
          window: "session",
          used: 10,
          status: "fresh",
          resets_at: "2026-10-27T14:00:00Z",
        },
      ],
      [],
      NOW
    )
    expect(shown.background).toBeUndefined()
  })

  it("marks a figure that comes from an old reading, as the app's gauge does", () => {
    const shown = usageStatus(
      [
        {
          provider: "codex",
          window: "weekly",
          used: 40,
          status: "stale",
          resets_at: "2026-10-30T12:00:00Z",
        },
      ],
      [],
      NOW
    )
    expect(shown.tooltip.at(-1)).toBe(
      "Codex weekly: 40% used · 20% a day for 3 days · stale reading"
    )
  })

  it("says what it can't read, and lists Codex's credits", () => {
    const shown = usageStatus(
      [{ provider: "claude", window: "weekly", used: null, status: "stale", resets_at: null }],
      [{ provider: "codex", balance: 1234.4, unlimited: false }],
      NOW
    )
    expect(shown.text).toBe("$(dashboard) –")
    expect(shown.tooltip).toEqual([
      "**Usage not reported**",
      "",
      "Claude weekly: stale reading",
      "Codex credits: 1,234",
    ])
  })
})

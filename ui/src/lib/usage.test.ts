import { describe, expect, it } from "vitest"

import { usageFoot, usagePace } from "@/lib/usage"

const NOW = Date.parse("2026-10-25T18:00:00Z")
const inHours = (hours: number) => new Date(NOW + hours * 3_600_000).toISOString()
const row = (window: string, used: number, hours: number) => ({
  window,
  used,
  resets_at: inHours(hours),
})

describe("usageFoot", () => {
  it("spreads what is left of a weekly window over the days until it resets", () => {
    expect(usageFoot(row("weekly", 5, 156), NOW)).toBe("15% a day for 6.5 days")
    expect(usageFoot(row("weekly", 54, 72), NOW)).toBe("15% a day for 3 days")
    expect(usageFoot(row("weekly_fable", 90, 96), NOW)).toBe("2.5% a day for 4 days")
    expect(usageFoot(row("weekly", 70, 24), NOW)).toBe("30% a day for 1 day")
  })

  it("says what is left when the window resets within a day", () => {
    expect(usageFoot(row("weekly", 54, 8), NOW)).toBe("46% left, resets in 8 h 0 min")
  })

  it("gives a session window its reset time, and a spent one says so", () => {
    expect(usageFoot(row("session", 44, 2), NOW)).toBe("resets in 2 h 0 min")
    expect(usageFoot(row("weekly", 100, 50), NOW)).toBe("none left, resets in 2 d 2 h")
  })

  it("says nothing it can't know", () => {
    expect(usageFoot({ window: "weekly", used: 30, resets_at: null }, NOW)).toBe("")
  })
})

describe("usagePace", () => {
  it("compares what is left per day with an even seventh of the week", () => {
    expect(usagePace(row("weekly", 5, 156), NOW)).toBe("even") // 14.6% a day
    expect(usagePace(row("weekly", 54, 72), NOW)).toBe("even") // 15.3% a day
    expect(usagePace(row("weekly_fable", 90, 96), NOW)).toBe("tight") // 2.5% a day
    expect(usagePace(row("weekly", 20, 48), NOW)).toBe("spare") // 40% a day
    expect(usagePace(row("weekly", 100, 50), NOW)).toBe("tight")
  })

  it("counts what is left near the reset as spare, at the same daily rate", () => {
    expect(usagePace(row("weekly", 54, 8), NOW)).toBe("spare") // 46% in a third of a day
  })

  it("has no pace for a session window or an unknown reading", () => {
    expect(usagePace(row("session", 44, 2), NOW)).toBeNull()
    expect(usagePace({ window: "weekly", used: null, resets_at: null }, NOW)).toBeNull()
  })
})

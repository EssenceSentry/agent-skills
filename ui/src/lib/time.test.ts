import { describe, expect, it } from "vitest"

import { every, messageStamp, resetStamp, stampsBefore } from "@/lib/time"

describe("every", () => {
  it("writes an interval the way you would say it", () => {
    expect(every(45)).toBe("45 s")
    expect(every(600)).toBe("10 min")
    expect(every(5400)).toBe("90 min")
    expect(every(7200)).toBe("2 h")
    expect(every(86400)).toBe("1 d")
  })
})

describe("dating a message", () => {
  it("writes the day and time as Codex does", () => {
    expect(messageStamp(new Date(2026, 9, 6, 13, 21).toISOString())).toBe("Tue, Oct 6 at 1:21 PM")
    expect(messageStamp(new Date(2026, 9, 27, 9, 5).toISOString())).toBe("Tue, Oct 27 at 9:05 AM")
  })

  it("dates the first message, and one after a pause of half an hour or more", () => {
    expect(stampsBefore(null, "2026-10-27T12:00:00Z")).toBe(true)
    expect(stampsBefore("2026-10-27T12:00:00Z", "2026-10-27T12:20:00Z")).toBe(false)
    expect(stampsBefore("2026-10-27T12:00:00Z", "2026-10-27T12:30:00Z")).toBe(true)
    expect(stampsBefore("2026-10-27T12:00:00Z", null)).toBe(false)
  })
})

describe("when a usage window resets", () => {
  const now = new Date(2026, 9, 27, 12, 0)
  it("says the day and the time, as a message's date does", () => {
    expect(resetStamp(new Date(2026, 9, 27, 14, 0).toISOString(), now)).toBe("today at 2:00 PM")
    expect(resetStamp(new Date(2026, 9, 28, 9, 5).toISOString(), now)).toBe("tomorrow at 9:05 AM")
    expect(resetStamp(new Date(2026, 9, 30, 0, 0).toISOString(), now)).toBe(
      "Fri, Oct 30 at 12:00 AM"
    )
  })
})

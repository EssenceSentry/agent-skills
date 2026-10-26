import { describe, expect, it } from "vitest"

import { every } from "@/lib/time"

describe("every", () => {
  it("writes an interval the way you would say it", () => {
    expect(every(45)).toBe("45 s")
    expect(every(600)).toBe("10 min")
    expect(every(5400)).toBe("90 min")
    expect(every(7200)).toBe("2 h")
    expect(every(86400)).toBe("1 d")
  })
})

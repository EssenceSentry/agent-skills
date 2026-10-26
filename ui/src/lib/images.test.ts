import { describe, expect, it } from "vitest"

import { fitWithin, needsShrinking } from "@/lib/images"

describe("pasted images", () => {
  it("shrinks a large picture to fit, keeping its shape", () => {
    expect(fitWithin(4000, 3000, 2000)).toEqual({ width: 2000, height: 1500 })
    expect(fitWithin(1200, 5000, 2000)).toEqual({ width: 480, height: 2000 })
    expect(fitWithin(800, 600, 2000)).toEqual({ width: 800, height: 600 })
  })

  it("shrinks only what is too big to send as it is", () => {
    expect(needsShrinking({ width: 1440, height: 900, bytes: 400_000 })).toBe(false)
    expect(needsShrinking({ width: 4032, height: 3024, bytes: 2_000_000 })).toBe(true)
    expect(needsShrinking({ width: 1000, height: 1000, bytes: 6_000_000 })).toBe(true)
  })
})

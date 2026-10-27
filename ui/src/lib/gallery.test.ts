import { describe, expect, it } from "vitest"

import { MAX_ZOOM, step, zoomAround } from "@/lib/gallery"

describe("moving through the pictures", () => {
  it("goes on to the next and back, round the ends", () => {
    expect(step(1, 3, 1)).toBe(2)
    expect(step(2, 3, 1)).toBe(0)
    expect(step(0, 3, -1)).toBe(2)
    expect(step(0, 1, 1)).toBe(0)
  })
})

describe("zooming", () => {
  it("keeps the point under the pointer where it is", () => {
    expect(zoomAround({ scale: 1, x: 0, y: 0 }, 2, { x: 100, y: 50 })).toEqual({
      scale: 2,
      x: -100,
      y: -50,
    })
  })

  it("stops at the largest zoom and comes back to the whole picture", () => {
    expect(zoomAround({ scale: MAX_ZOOM, x: -10, y: -10 }, 2, { x: 0, y: 0 }).scale).toBe(MAX_ZOOM)
    expect(zoomAround({ scale: 1.5, x: -40, y: -20 }, 0.5, { x: 10, y: 10 })).toEqual({
      scale: 1,
      x: 0,
      y: 0,
    })
  })
})

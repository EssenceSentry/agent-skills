import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { StaleNote } from "@/blocks/stale-note"

const NOW = Date.parse("2026-10-28T12:00:00Z")

describe("what shows when ax stops answering", () => {
  it("says the states shown are its last reading, and how old it is", () => {
    const out = renderToStaticMarkup(
      <StaleNote error="connection refused" at="2026-10-28T11:58:00Z" now={NOW} />
    )
    expect(out).toContain("ax isn&#x27;t answering")
    expect(out).toContain("last read 2 min ago")
    expect(out).toContain('role="status"')
  })

  it("is nothing while ax answers", () => {
    expect(renderToStaticMarkup(<StaleNote at="2026-10-28T11:59:00Z" now={NOW} />)).toBe("")
  })
})

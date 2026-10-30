import { describe, expect, it } from "vitest"

import { foundStage } from "@/lib/ax"

const fast = { query: "q", hits: [{ source: "code", path: "/a", title: "a", snippet: "" }] }
const full = { query: "q", hits: [] }

describe("a search in two stages", () => {
  it("is searching until either stage answers", () => {
    expect(foundStage({ key: "q" })).toEqual({ loading: true, refining: false })
  })

  it("shows the keyword stage while the search by meaning goes on", () => {
    expect(foundStage({ key: "q", fast })).toEqual({ data: fast, loading: false, refining: true })
  })

  it("shows the whole search once it answers, whatever the keyword stage did", () => {
    expect(foundStage({ key: "q", fast, full })).toEqual({
      data: full,
      loading: false,
      refining: false,
    })
    expect(foundStage({ key: "q", full })).toEqual({ data: full, loading: false, refining: false })
  })

  it("keeps the keyword stage when the search by meaning fails, and says so", () => {
    expect(foundStage({ key: "q", fast, fullError: "qmd took over 600 s" })).toEqual({
      data: fast,
      loading: false,
      refining: false,
      partial: "qmd took over 600 s",
    })
  })

  it("fails when neither stage answers", () => {
    expect(foundStage({ key: "q", fastError: "down", fullError: "down" })).toEqual({
      loading: false,
      refining: false,
      error: "down",
    })
  })
})

import { describe, expect, it } from "vitest"

import { beforeQuery, changed, changesTitle, readBeforeQuery } from "./changes"

describe("the left side of a session's diff", () => {
  it("carries the session and the base in its address, and reads them back", () => {
    const query = beforeQuery({ provider: "codex", id: "t 1&x", base: "turn" })
    expect(readBeforeQuery(query)).toEqual({ provider: "codex", id: "t 1&x", base: "turn" })
  })

  it("reads nothing it doesn't recognise", () => {
    expect(readBeforeQuery("provider=gemini&id=x&base=turn")).toBeNull()
    expect(readBeforeQuery("provider=claude&id=x&base=yesterday")).toBeNull()
    expect(readBeforeQuery("provider=claude&base=turn")).toBeNull()
  })
})

describe("which files the diff shows", () => {
  it("keeps a file whose text differs, or that was added or removed", () => {
    expect(changed({ exists: true, text: "a\n" }, "b\n")).toBe(true)
    expect(changed({ exists: false, text: "" }, "new\n")).toBe(true)
    expect(changed({ exists: true, text: "gone\n" }, null)).toBe(true)
  })

  it("drops one that is back as it was", () => {
    expect(changed({ exists: true, text: "same\n" }, "same\n")).toBe(false)
    expect(changed({ exists: false, text: "" }, null)).toBe(false)
  })
})

describe("the diff's title", () => {
  it("names the session, the base and the number of files", () => {
    expect(changesTitle("Fix the axis", "turn", 3)).toBe("Fix the axis: 3 files changed this turn")
    expect(changesTitle("Fix the axis", "commit", 1)).toBe(
      "Fix the axis: 1 file changed since the last commit"
    )
  })
})

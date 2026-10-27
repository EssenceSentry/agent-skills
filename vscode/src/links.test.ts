import { describe, expect, it } from "vitest"

import { fileTarget } from "./links"

const HOME = "/Users/me"
const CWD = "/Users/me/Repos/demo"

describe("a file an answer links to", () => {
  it("opens an absolute path, at the line and column it names", () => {
    expect(fileTarget("/Users/me/x.ts", CWD, HOME)).toEqual({ path: "/Users/me/x.ts" })
    expect(fileTarget("/Users/me/x.ts:42", CWD, HOME)).toEqual({ path: "/Users/me/x.ts", line: 42 })
    expect(fileTarget("/Users/me/x.ts:42:7", CWD, HOME)).toEqual({
      path: "/Users/me/x.ts",
      line: 42,
      column: 7,
    })
    expect(fileTarget("/Users/me/x.ts#L42", CWD, HOME)).toEqual({
      path: "/Users/me/x.ts",
      line: 42,
    })
    expect(fileTarget("/Users/me/x.ts#L42-L50", CWD, HOME)).toEqual({
      path: "/Users/me/x.ts",
      line: 42,
    })
  })

  it("reads a relative path from the session's folder", () => {
    expect(fileTarget("src/lib/ax.ts:12", CWD, HOME)).toEqual({
      path: "/Users/me/Repos/demo/src/lib/ax.ts",
      line: 12,
    })
    expect(fileTarget("./README.md", CWD, HOME)).toEqual({ path: "/Users/me/Repos/demo/README.md" })
    expect(fileTarget("../other/a.md", CWD, HOME)).toEqual({ path: "/Users/me/Repos/other/a.md" })
    expect(fileTarget("~/notes/today.md", CWD, HOME)).toEqual({ path: "/Users/me/notes/today.md" })
  })

  it("decodes what Markdown encoded, and file URLs", () => {
    expect(fileTarget("/Users/me/a%20b.ts", CWD, HOME)).toEqual({ path: "/Users/me/a b.ts" })
    expect(fileTarget("file:///Users/me/a%20b.ts", CWD, HOME)).toEqual({ path: "/Users/me/a b.ts" })
    expect(fileTarget("file:///Users/me/a.ts#L3", CWD, HOME)).toEqual({
      path: "/Users/me/a.ts",
      line: 3,
    })
  })

  it("leaves web links, the app's pages and anything else alone", () => {
    for (const href of [
      "https://example.com/a.ts",
      "http://127.0.0.1:8765/jobs/x/",
      "/jobs/build-42/",
      "#/sessions",
      "mailto:me@example.com",
      "javascript:alert(1)",
      "",
    ])
      expect(fileTarget(href, CWD, HOME), href).toBeNull()
  })

  it("can't place a relative path without the session's folder", () => {
    expect(fileTarget("src/a.ts", null, HOME)).toBeNull()
    expect(fileTarget("/abs/a.ts", null, HOME)).toEqual({ path: "/abs/a.ts" })
  })
})

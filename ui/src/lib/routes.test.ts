import { describe, expect, it } from "vitest"

import { folderHref, parseRoute, readHref } from "@/lib/routes"

describe("routes", () => {
  it("reads every screen from the hash", () => {
    expect(parseRoute("")).toEqual({ screen: "now" })
    expect(parseRoute("#/")).toEqual({ screen: "now" })
    expect(parseRoute("#/notes")).toEqual({ screen: "notes", dir: "" })
    expect(parseRoute("#/notes/Profile/rules")).toEqual({ screen: "notes", dir: "Profile/rules" })
    expect(parseRoute("#/read/Sessions/2026/10/Other%20note.md")).toEqual({
      screen: "read",
      path: "Sessions/2026/10/Other note.md",
    })
    expect(parseRoute("#/elsewhere")).toEqual({ screen: "now" })
  })

  it("writes links the way the server writes them", () => {
    expect(readHref("Sessions/2026/10/Other note.md")).toBe(
      "#/read/Sessions/2026/10/Other%20note.md"
    )
    expect(readHref("Todos/T1 Approve #1?.md")).toBe("#/read/Todos/T1%20Approve%20%231%3F.md")
    expect(folderHref("")).toBe("#/notes")
    expect(folderHref("Profile/rules")).toBe("#/notes/Profile/rules")
  })

  it("survives a malformed escape", () => {
    expect(parseRoute("#/read/100%.md")).toEqual({ screen: "read", path: "100%.md" })
  })
})

import { describe, expect, it } from "vitest"

import { rankSlash, slashQuery } from "@/lib/slash"

const item = (title: string, name = title.toLowerCase().replaceAll(" ", "-")) => ({ title, name })

describe("the / menu", () => {
  it("opens on a slash and the word after it, until a space", () => {
    expect(slashQuery("/")).toBe("")
    expect(slashQuery("/at")).toBe("at")
    expect(slashQuery("/compact now")).toBeNull()
    expect(slashQuery("say /at")).toBeNull()
    expect(slashQuery("")).toBeNull()
  })

  it("lists everything, in order, before a letter is typed", () => {
    const ranked = rankSlash([item("Status"), item("Atelier")], "")
    expect(ranked.map((r) => [r.item.title, r.marks])).toEqual([
      ["Status", []],
      ["Atelier", []],
    ])
  })

  it("puts a name that starts with what is typed first, then a word, then a part, then letters in order", () => {
    const items = [
      item("Template Creator"),
      item("Status"),
      item("Tools MCP"),
      item("Atelier"),
      item("Go at it"),
    ]
    const ranked = rankSlash(items, "at")
    expect(ranked.map((r) => r.item.title)).toEqual([
      "Atelier",
      "Go at it",
      "Status",
      "Template Creator",
    ])
    expect(ranked[0]?.marks).toEqual([0, 1])
    expect(ranked[2]?.marks).toEqual([2, 3])
    expect(rankSlash([item("Template Creator")], "tc")[0]?.marks).toEqual([0, 9])
  })

  it("finds a skill by its name when its title doesn't match", () => {
    const ranked = rankSlash([item("Classification Workflow", "classification-workflow")], "cw")
    expect(ranked).toHaveLength(1)
    expect(rankSlash([item("Atelier")], "zz")).toEqual([])
  })
})

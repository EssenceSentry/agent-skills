import { describe, expect, it } from "vitest"

import { KINDS, kindCounts, ofKind } from "@/lib/search"

const hit = (source: string) => ({ source, path: `/x/${source}`, title: source, snippet: "" })
const hits = [hit("conversation"), hit("code"), hit("conversation"), hit("doc"), hit("memory")]

describe("search kinds", () => {
  it("counts the hits of each kind, in the order the chips show them", () => {
    expect(kindCounts(hits)).toEqual([
      { kind: "conversation", label: "Conversations", count: 2 },
      { kind: "memory", label: "Memories", count: 1 },
      { kind: "doc", label: "Docs", count: 1 },
      { kind: "code", label: "Code", count: 1 },
    ])
  })

  it("keeps every hit for all kinds, or only the chosen kind's", () => {
    expect(ofKind(hits, null)).toHaveLength(5)
    expect(ofKind(hits, "conversation").map((h) => h.source)).toEqual([
      "conversation",
      "conversation",
    ])
  })

  it("names every kind ax find returns", () => {
    expect(KINDS.map((k) => k.kind)).toEqual([
      "conversation",
      "note",
      "memory",
      "doc",
      "code",
      "subagent",
    ])
  })
})

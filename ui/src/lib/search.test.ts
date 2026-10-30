import { describe, expect, it } from "vitest"

import { KINDS, kindCounts, ofKind } from "@/lib/search"

const hit = (source: string) => ({ source, path: `/x/${source}`, title: source, snippet: "" })
const hits = [hit("conversation"), hit("subagent"), hit("conversation"), hit("memory")]

describe("search kinds", () => {
  it("counts the hits of each kind, in the order the chips show them", () => {
    expect(kindCounts(hits)).toEqual([
      { kind: "conversation", label: "Conversations", count: 2 },
      { kind: "memory", label: "Memories", count: 1 },
      { kind: "subagent", label: "Subagents", count: 1 },
    ])
  })

  it("keeps every hit for all kinds, or only the chosen kind's", () => {
    expect(ofKind(hits, null)).toHaveLength(4)
    expect(ofKind(hits, "conversation").map((h) => h.source)).toEqual([
      "conversation",
      "conversation",
    ])
  })

  it("names every kind ax find returns", () => {
    expect(KINDS.map((k) => k.kind)).toEqual(["conversation", "memory", "subagent"])
  })
})

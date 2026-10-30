import { describe, expect, it } from "vitest"

import {
  effortLabel,
  goalLine,
  mergeReferences,
  modesElsewhere,
  type Reference,
  referenceLabel,
  withReferences,
} from "@/lib/plus"

const file: Reference = { kind: "file", path: "/repo/src/a.ts" }
const folder: Reference = { kind: "folder", path: "/repo/docs" }
const picked: Reference = {
  kind: "selection",
  path: "/repo/src/b.py",
  start: 12,
  end: 14,
  text: "def f():\n    return 1\n",
  language: "python",
}

describe("references sent with a message", () => {
  it("lists files and folders after the words", () => {
    expect(withReferences("Look at these", [file, folder])).toBe(
      "Look at these\n\nFiles:\n- `/repo/src/a.ts`\n- `/repo/docs/`"
    )
  })

  it("sends a selection as a fenced block with where it comes from", () => {
    expect(withReferences("Why is this slow?", [picked])).toBe(
      "Why is this slow?\n\nSelected in `/repo/src/b.py`, lines 12–14:\n```python\ndef f():\n    return 1\n```"
    )
  })

  it("sends the references alone when there are no words, and the words alone without them", () => {
    expect(withReferences("  ", [file])).toBe("Files:\n- `/repo/src/a.ts`")
    expect(withReferences("Just words", [])).toBe("Just words")
  })

  it("refreshes a reattached unsaved selection without duplicating or reordering chips", () => {
    const otherRange: Reference = { ...picked, start: 20, end: 22 }
    const updated: Reference = { ...picked, path: "/repo/src/./b.py", text: "return 2\n" }
    const refs = mergeReferences([file, picked, otherRange], [updated, folder, folder])
    expect(refs).toEqual([file, updated, otherRange, folder])
    expect(withReferences("Review", refs)).toContain("return 2")
  })

  it("labels each one briefly", () => {
    expect([file, folder, picked].map(referenceLabel)).toEqual([
      "src/a.ts",
      "repo/docs/",
      "src/b.py:12–14",
    ])
    expect(referenceLabel({ ...picked, start: 3, end: 3 })).toBe("src/b.py:3")
  })
})

describe("efforts by name", () => {
  it("names each effort as people say it", () => {
    expect(["minimal", "low", "medium", "high", "xhigh", "max", "ultra"].map(effortLabel)).toEqual([
      "Minimal",
      "Low",
      "Medium",
      "High",
      "Extra high",
      "Max",
      "Ultra",
    ])
    expect(effortLabel("turbo")).toBe("turbo")
  })
})

describe("the goal line", () => {
  it("says the status, the time and the tokens", () => {
    expect(
      goalLine({
        objective: "ship",
        status: "active",
        tokens_used: 1200,
        token_budget: 50000,
        seconds: 95,
      })
    ).toBe("Active · 1 min · 1.2k of 50k tokens")
    expect(
      goalLine({
        objective: "ship",
        status: "budgetLimited",
        tokens_used: 50000,
        token_budget: 50000,
        seconds: 4000,
      })
    ).toBe("Budget reached · 1 h 6 min · 50k of 50k tokens")
  })

  it("says only that it is set when the tool reports nothing more", () => {
    expect(
      goalLine({
        objective: "ship",
        status: "set",
        tokens_used: null,
        token_budget: null,
        seconds: null,
      })
    ).toBe("Set")
  })
})

describe("modes of a session ax doesn't hold", () => {
  it("are set where the session is open, and the + menu says where", () => {
    expect(modesElsewhere("codex app")).toBe("Set its modes in the Codex app")
    expect(modesElsewhere("elsewhere")).toBe("Take it over to set its modes")
  })

  it("are ax's to change when ax holds it or nothing does", () => {
    expect(modesElsewhere("ax")).toBeNull()
    expect(modesElsewhere(null)).toBeNull()
  })
})

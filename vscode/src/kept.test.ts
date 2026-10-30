import { describe, expect, it } from "vitest"

import { keptTab } from "./kept"

const ax = (label: string) => ({ viewType: "mainThreadWebview-ax.session", label })
const other = (label: string) => ({ viewType: "markdown.preview", label })
const text = (label: string) => ({ label })

describe("a session tab VS Code kept from before a reload", () => {
  it("is found by its session's name, among ax's tabs only, with its group and place", () => {
    const groups = [
      { viewColumn: 1, tabs: [text("README.md"), other("Plan: themed charts")] },
      { viewColumn: 2, tabs: [ax("Run the test suite"), text("a.ts"), ax("Plan: themed charts")] },
    ]
    expect(keptTab(groups, "Plan: themed charts")).toEqual({ viewColumn: 2, index: 2 })
    expect(keptTab(groups, "Run the test suite")).toEqual({ viewColumn: 2, index: 0 })
  })

  it("is nothing when no ax tab has that name", () => {
    expect(keptTab([{ viewColumn: 1, tabs: [other("Plan"), text("Plan")] }], "Plan")).toBeNull()
    expect(keptTab([], "Plan")).toBeNull()
  })
})

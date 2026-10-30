import { afterEach, describe, expect, it } from "vitest"

import { openPlanBeside, planFile, savePlan } from "@/lib/plan"
import { setExtension } from "@/lib/transport"

afterEach(() => setExtension(null))

describe("a plan as a file of its own", () => {
  it("is named by its heading", () => {
    expect(planFile("## Plan: themed charts\n\n1. Read the code")).toBe("plan-themed-charts.md")
    expect(planFile("# Rebuild the cache\n\nFirst…")).toBe("plan-rebuild-the-cache.md")
    expect(planFile("Intro\n\n### Steps: one, two\n")).toBe("plan-steps-one-two.md")
  })

  it("is plan.md when it has no heading to go by, and never a long name", () => {
    expect(planFile("1. Read the code\n2. Fix it")).toBe("plan.md")
    expect(planFile("# ¿Qué?")).toBe("plan-qué.md")
    const name = planFile(`# ${"a very long heading ".repeat(10)}`)
    expect(name.length).toBeLessThanOrEqual(60)
    expect(name).toMatch(/^plan-a-very-long-heading[a-z-]*[a-z]\.md$/)
  })

  it("opens beside the session and saves from the session's folder, through VS Code", async () => {
    const calls: unknown[] = []
    setExtension(async (name, args) => {
      calls.push([name, args])
      return name === "saveMarkdown" ? "/repo/plan-x.md" : undefined
    })
    await openPlanBeside("# X\n\nsteps", "/repo")
    expect(await savePlan("# X\n\nsteps", { editor: true, cwd: "/repo" })).toBe("/repo/plan-x.md")
    expect(calls).toEqual([
      ["openMarkdown", { text: "# X\n\nsteps", name: "plan-x.md", cwd: "/repo" }],
      ["saveMarkdown", { text: "# X\n\nsteps", name: "plan-x.md", cwd: "/repo" }],
    ])
  })
})

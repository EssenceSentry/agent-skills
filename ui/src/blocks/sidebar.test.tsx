import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { FolderMenu } from "@/blocks/folder-picker"
import { Sidebar } from "@/blocks/sidebar"
import type { LiveStatus } from "@/lib/ax"
import type { Route } from "@/lib/routes"

const render = (route: Route, status: LiveStatus = "live") =>
  renderToStaticMarkup(<Sidebar route={route} status={status} />)

describe("the web page's sidebar, as ax's panel in VS Code", () => {
  it("lists the sessions as links, the one open marked, what waits first", () => {
    const out = render({ screen: "session", provider: "claude", id: "c41d9e02-pricing" })
    expect(out).toMatch(
      /<a[^>]*aria-current="page"[^>]*href="#\/sessions\/claude\/c41d9e02-pricing"/
    )
    expect(out.indexOf("Pricing study")).toBeLessThan(out.indexOf("Release the scoring image"))
  })

  it("offers nothing only VS Code can do", () => {
    const out = render({ screen: "now" })
    expect(out).not.toContain("to the side")
    expect(out).not.toContain("changed this turn")
  })

  it("keeps the usage above the sessions and the box that starts one at its foot", () => {
    const out = render({ screen: "now" })
    expect(out.indexOf('aria-label="Usage"')).toBeLessThan(out.indexOf('aria-label="Sessions"'))
    expect(out.indexOf('aria-label="Sessions"')).toBeLessThan(
      out.indexOf('aria-label="First message"')
    )
    expect(out).toContain('aria-label="Start the session"')
  })

  it("reaches the other screens from its head, marking the one shown", () => {
    const out = render({ screen: "notes", dir: "" })
    for (const href of ["#/search", "#/", "#/notes", "#/help"])
      expect(out).toContain(`href="${href}"`)
    expect(out).toMatch(/<a[^>]*aria-current="page"[^>]*href="#\/notes"/)
  })

  it("says so when ax isn't live, and nothing when it is", () => {
    expect(render({ screen: "now" }, "offline")).toContain("Offline")
    expect(render({ screen: "now" }, "live")).not.toContain(">Live<")
  })
})

describe("the folder a session starts in", () => {
  it("shows where each recent folder lives, from ~", () => {
    const codex = {
      provider: "codex" as const,
      id: "t",
      name: "n",
      project: "l",
      state: "idle" as const,
      waiting_for: null,
      kind: "interactive",
      started: null,
      updated: null,
      last: null,
      jobs: 0,
      cwd: "/Users/me/Documents/Codex/2026-10-27/l",
    }
    const out = renderToStaticMarkup(
      <FolderMenu folder="" workspace={[]} sessions={[codex]} onPick={() => undefined} />
    )
    expect(out).toContain(">l<")
    expect(out).toContain("~/Documents/Codex/2026-10-27")
  })
})

describe("the folder a session starts in, on the web", () => {
  it("has no system dialog to choose another from", () => {
    const out = renderToStaticMarkup(
      <FolderMenu folder="" workspace={[]} sessions={[]} onPick={() => undefined} />
    )
    expect(out).not.toContain("Choose…")
  })
})

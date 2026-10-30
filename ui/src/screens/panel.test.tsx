import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { FolderMenu } from "@/blocks/folder-picker"
import { EditorHost } from "@/lib/host"
import { SessionsPanel, UsageSection } from "@/screens/panel"

const none = () => undefined

const panel = () =>
  renderToStaticMarkup(
    <EditorHost.Provider value={true}>
      <SessionsPanel
        folders={["/Users/me/Repos/app"]}
        onOpen={none}
        onStarted={none}
        onChanges={none}
      />
    </EditorHost.Provider>
  )

describe("the panel on VS Code's right, as Codex's", () => {
  it("lists the sessions, what waits for you first, each with a way to open it beside", () => {
    const out = panel()
    expect(out).toContain("Sessions")
    const order = ["Pricing study", "Retry for the fetch helper", "Release the scoring image"]
    const at = order.map((name) => out.indexOf(name))
    expect(at.every((i) => i > 0)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    expect(out).toContain('aria-label="Open Pricing study to the side"')
    expect(out).toContain('aria-label="Show what Pricing study changed this turn"')
  })

  it("names the project of a session from another repository than the workspace's", () => {
    const out = panel() // the workspace is /Users/me/Repos/app
    expect(out).toMatch(
      /Retry for the fetch helper<\/span>(?:<span[^>]*chat-panel-tool-name[^>]*>[^<]*<\/span>)?<span[^>]*chat-panel-project[^>]*>agent-skills</
    )
    const demo = renderToStaticMarkup(
      <EditorHost.Provider value={true}>
        <SessionsPanel folders={["/Users/me/Repos/demo"]} onOpen={none} onStarted={none} />
      </EditorHost.Provider>
    )
    expect(demo).not.toMatch(/chat-panel-project[^>]*>demo</) // its own project goes unsaid
    expect(demo).toMatch(/chat-panel-project[^>]*>agent-skills</)
  })

  it("marks each session with its tool, by its mark in VS Code and by name elsewhere", () => {
    const out = panel()
    expect(out).toMatch(/title="Claude Code"[^>]*>\uE001<\/span><span[^>]*>Pricing study/)
    expect(out).toMatch(/title="Codex"[^>]*>\uE002<\/span><span[^>]*>Review the model card/)
    expect(out).toMatch(/Pricing study<\/span><span[^>]*chat-panel-tool-name[^>]*>Claude</)
  })

  it("shows both tools' usage above the sessions", () => {
    const out = panel()
    const usage = out.indexOf('aria-label="Usage"')
    expect(usage).toBeGreaterThan(0)
    expect(usage).toBeLessThan(out.indexOf('aria-label="Sessions"'))
    expect(out).toMatch(/\uE001<\/span>Claude</)
    expect(out).toMatch(/\uE002<\/span>Codex</)
    expect(out).toContain("Fable weekly")
    expect(out).toContain("a day for")
  })

  it("starts a session from a box at the foot, in a folder, on a model of either tool", () => {
    const out = panel()
    expect(out).toContain('aria-label="First message"')
    expect(out).toContain('aria-label="Add and modes"')
    expect(out).toContain('aria-label="Model: Opus 5.5"')
    expect(out).toContain('aria-label="Start the session"')
    expect(out).toContain('aria-label="Folder: app"')
  })
})

describe("the folder a new session starts in", () => {
  it("offers the workspace's folders, recent ones, and any other", () => {
    const out = renderToStaticMarkup(
      <FolderMenu
        folder="/Users/me/Repos/app"
        workspace={["/Users/me/Repos/app"]}
        sessions={[]}
        onPick={none}
        onChoose={none}
      />
    )
    expect(out).toContain('placeholder="Search folders…"')
    expect(out).toContain("Workspace")
    expect(out).toMatch(/aria-checked="true"[^>]*>.*?app/s)
    expect(out).toContain("Choose…")
  })
})

describe("the panel's usage", () => {
  const rows = [
    {
      provider: "claude",
      window: "session",
      used: 9,
      status: "fresh",
      resets_at: null,
      lasts: null,
      projected_high: null,
      runs_out_at: null,
    },
    {
      provider: "claude",
      window: "weekly",
      used: 38,
      status: "fresh",
      resets_at: null,
      lasts: null,
      projected_high: null,
      runs_out_at: null,
    },
    {
      provider: "codex",
      window: "weekly",
      used: 4,
      status: "fresh",
      resets_at: null,
      lasts: null,
      projected_high: null,
      runs_out_at: null,
    },
  ]
  const usage = { usage: rows, credits: [] }

  it("folds to one line: each tool's most used window, the details a click away", () => {
    const out = renderToStaticMarkup(<UsageSection usage={usage} folded onToggle={none} />)
    expect(out).toContain('aria-expanded="false"')
    expect(out).toMatch(/Claude<\/span>\s*<span[^>]*>38%/)
    expect(out).toMatch(/Codex<\/span>\s*<span[^>]*>4%/)
    expect(out).not.toContain("Weekly")
  })

  it("opens to every window", () => {
    const out = renderToStaticMarkup(<UsageSection usage={usage} folded={false} onToggle={none} />)
    expect(out).toContain('aria-expanded="true"')
    expect(out).toContain("Weekly")
  })
})

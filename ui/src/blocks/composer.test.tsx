import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Composer } from "@/blocks/composer"
import { EditorHost } from "@/lib/host"
import type { ChatState, Session } from "@/lib/sessions"

const session: Session = {
  provider: "claude",
  id: "abc",
  name: "Fix the axis",
  cwd: "/Users/me/Repos/demo",
  project: "demo",
  state: "idle",
  waiting_for: null,
  kind: "interactive",
  started: null,
  updated: null,
  last: null,
  jobs: 0,
}

const NOTE =
  "Running in the background through ax, so the Claude app doesn't show it. Hand it back to continue it elsewhere, such as `claude --resume abc` in a terminal."

function chat(over: Partial<ChatState> = {}): ChatState {
  return {
    holder: "ax",
    can_send: true,
    take_over: false,
    pending: false,
    busy: false,
    partial: "",
    approval: null,
    error: null,
    note: NOTE,
    ...over,
  }
}

const render = (state: ChatState, editor: boolean) =>
  renderToStaticMarkup(
    <EditorHost.Provider value={editor}>
      <Composer session={session} chat={state} />
    </EditorHost.Provider>
  )

describe("handing a session back", () => {
  it("is an icon beside the plus in the editor, explained on hover, with no line below", () => {
    const html = render(chat(), true)
    expect(html).toContain('aria-label="Hand back"')
    expect(html).toContain(
      'title="Hand back. Running in the background through ax, so the Claude app doesn&#x27;t show it. Hand it back to continue it elsewhere, such as claude --resume abc in a terminal."'
    )
    expect(html).not.toContain("chat-hint")
  })

  it("is offered only for a session ax holds", () => {
    expect(render(chat({ holder: "codex app" }), true)).not.toContain('aria-label="Hand back"')
  })

  it("keeps its line under the box on the web page", () => {
    const html = render(chat(), false)
    expect(html).toContain("chat-hint")
    expect(html).not.toContain('aria-label="Hand back"')
  })
})

const astra = {
  id: "gpt-6-astra",
  label: "GPT-6-Astra",
  efforts: ["low", "xhigh"],
  default_effort: "low",
}

describe("modes in the editor", () => {
  it("shows the model and effort, and the modes that are on", () => {
    const html = render(
      chat({
        holder: "ax",
        settings: { plan: true, auto: true, model: "gpt-6-astra", effort: "xhigh" },
        models: [astra],
      }),
      true
    )
    expect(html).toContain('aria-label="Add and modes"')
    expect(html).toContain("GPT-6-Astra · Extra high")
    expect(html).toContain('aria-label="Plan mode is on: turn it off"')
    expect(html).toContain('aria-label="Approve for me is on: turn it off"')
  })

  it("shows the goal it pursues, with a way to clear it", () => {
    const html = render(
      chat({
        goal: {
          objective: "ship it",
          status: "active",
          tokens_used: 1200,
          token_budget: null,
          seconds: 30,
        },
      }),
      true
    )
    expect(html).toContain("ship it")
    expect(html).toContain("Active · 30 s · 1.2k tokens")
    expect(html).toContain('aria-label="Clear the goal"')
  })

  it("shows a plan waiting for approval as the plan itself", () => {
    const html = render(
      chat({
        approval: {
          id: "p1",
          tool: "ExitPlanMode",
          summary: "start on its plan",
          reason: null,
          detail: null,
          plan: "# Plan\n1. Do it",
        },
      }),
      true
    )
    expect(html).toContain("<h1>Plan</h1>")
    expect(html).toContain("Go ahead")
    expect(html).toContain("Keep planning")
  })
})

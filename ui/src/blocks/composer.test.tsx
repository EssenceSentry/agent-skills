import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Composer } from "@/blocks/composer"
import { EditorHost, EditorLook } from "@/lib/host"
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

// The web page draws the box in the editor's manner too, without VS Code behind it.
const render = (state: ChatState, editor: boolean, look = editor) =>
  renderToStaticMarkup(
    <EditorLook.Provider value={look}>
      <EditorHost.Provider value={editor}>
        <Composer session={session} chat={state} />
      </EditorHost.Provider>
    </EditorLook.Provider>
  )

describe("handing a session back", () => {
  it("is in the + menu in the editor, not an icon beside the plus, with no line below", () => {
    const html = render(chat(), true)
    expect(html).toContain('aria-label="Add and modes"')
    expect(html).not.toContain('aria-label="Hand back"')
    expect(html).not.toContain("chat-handback")
    expect(html).not.toContain("chat-hint")
  })

  it("is offered only for a session ax holds", () => {
    expect(render(chat({ holder: "codex app" }), true)).not.toContain('aria-label="Hand back"')
  })

  it("says a message for a thread open in the Codex app becomes its next turn there", () => {
    expect(render(chat({ holder: "codex app" }), true)).toContain(
      'placeholder="Queue its next turn in the Codex app…"'
    )
  })

  it("is in the + menu on the web page too, which draws the box as the editor does", () => {
    const settings = { plan: false, auto: false, model: "gpt-6-astra", effort: "low" }
    const html = render(chat({ settings, models: [astra] }), false, true)
    expect(html).toContain('aria-label="Add and modes"')
    expect(html).toContain('aria-label="Model: GPT-6 Astra, Low"')
    expect(html).not.toContain("chat-hint")
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
    expect(html).toContain('aria-label="Model: GPT-6 Astra, Extra high"')
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

  it("clears the goal while it works, Claude's once the turn it is in ends", () => {
    const goal = {
      objective: "ship it",
      status: "active",
      tokens_used: 0,
      token_budget: null,
      seconds: 1,
    }
    const html = render(chat({ goal, busy: true }), true)
    expect(html).toMatch(/<button[^>]*aria-label="Clear the goal"[^>]*>/)
    expect(html).not.toMatch(/<button[^>]*aria-label="Clear the goal"[^>]*disabled/)
    expect(html).toContain("It stops pursuing it once this turn ends")
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
    expect(html).toContain("Implement this plan?")
    expect(html).toContain("Yes, implement this plan")
    expect(html).toContain("No, and tell Claude what to do differently")
    // Above the box, which stays: the box is always there.
    expect(html.indexOf("Implement this plan?")).toBeLessThan(html.indexOf('aria-label="Message"'))
  })
})

describe("the message box under a request", () => {
  const approval = {
    id: "a1",
    tool: "Bash",
    summary: "run `rm -rf build`",
    reason: null,
    detail: null,
  }

  it("shrinks to one line beside its controls, leaving the room to the request", () => {
    const html = render(chat({ approval }), true)
    expect(html).toContain("chat-box-compact")
    expect(html).toMatch(/<textarea[^>]*rows="1"/)
    expect(html).toContain('placeholder="Or tell it something else…"')
  })

  it("is its full size with nothing waiting", () => {
    const html = render(chat(), true)
    expect(html).not.toContain("chat-box-compact")
    expect(html).toMatch(/<textarea[^>]*rows="2"/)
  })
})

describe("the message box", () => {
  const ELSEWHERE =
    "Open in the Claude app or a terminal. Send from here, then close it there: ax continues it with your message."

  it("stays for a session open elsewhere, a line above it saying what sending does", () => {
    const html = render(chat({ holder: "elsewhere", take_over: true, note: ELSEWHERE }), true)
    expect(html).toContain('aria-label="Message"')
    expect(html).toContain("Send from here, then close it there")
    expect(html).not.toContain("Take over")
  })

  it("stays while a message waits for the Claude app to let go, which can be cancelled", () => {
    const html = render(
      chat({
        holder: "elsewhere",
        take_over: true,
        pending: true,
        note: "Waiting for you to close it in the Claude app.",
      }),
      true
    )
    expect(html).toContain('aria-label="Message"')
    expect(html).toContain("Waiting for you to close it in the Claude app.")
    expect(html).toContain('aria-label="Cancel: keep it in the Claude app"')
  })

  it("stops a working session from a button drawn as the send button, with a small square", () => {
    const html = render(chat({ busy: true }), true)
    expect(html).toMatch(/aria-label="Stop"[^>]*class="[^"]*chat-send/)
    expect(html).toContain("chat-stop-mark")
    expect(html).not.toContain("lucide-square")
  })
})

describe("a message while it works", () => {
  it("can be sent beside the stop button, and says so in the box", () => {
    const html = render(chat({ busy: true }), true)
    expect(html).toContain('aria-label="Stop"')
    expect(html).toMatch(/aria-label="Send"[^>]*disabled/) // until there is something to send
    expect(html).toContain('placeholder="Message it while it works…"')
  })

  it("shows what was sent until the turn has read it", () => {
    const html = render(chat({ busy: true, mid_turn: ["also check the docs"] }), true)
    expect(html).toContain("Sent while it works")
    expect(html).toContain("also check the docs")
    expect(render(chat({ busy: true }), true)).not.toContain("Sent while it works")
  })
})

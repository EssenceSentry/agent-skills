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

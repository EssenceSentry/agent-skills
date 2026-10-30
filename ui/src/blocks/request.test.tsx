import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ApprovalPanel, PlanPanel } from "@/blocks/request"
import { EditorHost } from "@/lib/host"

describe("an approval waiting in the message box's place", () => {
  it("asks in Codex's words, shows the command, and offers deny or allow once", () => {
    const out = renderToStaticMarkup(
      <ApprovalPanel
        provider="claude"
        approval={{
          id: "a1",
          tool: "Bash",
          summary: "run `npm run build`",
          reason: "npm is outside the allowed commands",
          detail: JSON.stringify({ command: "npm run build" }),
        }}
        onAnswer={() => undefined}
      />
    )
    expect(out).toContain("Terminal")
    expect(out).toContain("Do you want Claude to run this command?")
    expect(out).toContain("npm run build")
    expect(out).toContain("Reason")
    expect(out).toContain("npm is outside the allowed commands")
    expect(out).toContain("Deny")
    expect(out).toContain("Allow once")
  })
})

describe("a plan waiting for the go-ahead", () => {
  it("asks whether to implement it, with room to say what to change", () => {
    const out = renderToStaticMarkup(
      <PlanPanel
        provider="claude"
        plan={"## Plan\n\n1. Read the code"}
        onAnswer={() => undefined}
      />
    )
    expect(out).toContain("Implement this plan?")
    expect(out).toContain("Read the code")
    expect(out).toContain("Yes, implement this plan")
    expect(out).toContain('placeholder="No, and tell Claude what to do differently"')
    expect(out).toContain("Submit")
    expect(out.match(/Expand/g)).toHaveLength(1) // one way to open the plan, where it fades
  })

  it("opens beside the session as a Markdown tab and saves, in VS Code", () => {
    const out = renderToStaticMarkup(
      <EditorHost.Provider value={true}>
        <PlanPanel provider="claude" plan="## Plan" cwd="/repo" onAnswer={() => undefined} />
      </EditorHost.Provider>
    )
    expect(out).toContain('aria-label="Open the plan to the side"')
    expect(out).toContain('aria-label="Save the plan"')
  })

  it("saves as a download on the web, which has no side to open it to", () => {
    const out = renderToStaticMarkup(
      <PlanPanel provider="claude" plan="## Plan" onAnswer={() => undefined} />
    )
    expect(out).toContain('aria-label="Save the plan"')
    expect(out).not.toContain("to the side")
  })
})

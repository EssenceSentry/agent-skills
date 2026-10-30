// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { afterEach, expect, it, vi } from "vitest"
import { exampleSession } from "@/lib/example"
import { setTransport } from "@/lib/transport"
import { ContextPicker } from "./context-picker"
import { PendingMessages } from "./pending-messages"
import { PendingRequests } from "./pending-requests"
import { useSlash } from "./slash-menu"

afterEach(() => {
  cleanup()
  setTransport(null)
})
it("attaches the selected same-named file with the keyboard without submitting", async () => {
  const user = userEvent.setup(),
    add = vi.fn(),
    submit = vi.fn()
  setTransport(async () => ({
    status: 200,
    body: [
      { kind: "file", path: "/repo/src/config.py" },
      { kind: "file", path: "/repo/tests/config.py" },
    ],
  }))
  function Form() {
    const [text, setText] = useState("")
    return (
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <textarea
          aria-label="Context draft"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <ContextPicker text={text} setText={setText} cwd="/repo" add={add} />
      </form>
    )
  }
  render(<Form />)
  await user.type(screen.getByRole("textbox"), "@config")
  await screen.findByText("tests/config.py")
  await user.keyboard("{ArrowDown}{Enter}")
  expect(add).toHaveBeenCalledWith([{ kind: "file", path: "/repo/tests/config.py" }])
  expect(submit).not.toHaveBeenCalled()
})
it("edits an unconfirmed message and requires explicit retry", async () => {
  const user = userEvent.setup(),
    run = vi.fn()
  render(
    <PendingMessages
      busy={false}
      run={run}
      messages={[
        { id: "one", text: "Lost acknowledgement", status: "uncertain", delivery: "steer" },
      ]}
    />
  )
  await user.click(screen.getByRole("button", { name: "Edit" }))
  await user.clear(screen.getByRole("textbox"))
  await user.type(screen.getByRole("textbox"), "Corrected")
  await user.click(screen.getByRole("button", { name: "Save pending message" }))
  expect(run).toHaveBeenLastCalledWith({
    action: "pending-edit",
    message_id: "one",
    text: "Corrected",
  })
  await user.click(screen.getByRole("button", { name: /Send again/ }))
  expect(run).toHaveBeenLastCalledWith({ action: "pending-retry", message_id: "one" })
})
it("sends a schema-typed MCP array by request ID", async () => {
  const user = userEvent.setup(),
    answer = vi.fn()
  render(
    <PendingRequests
      session={exampleSession("codex", "one").session}
      busy={false}
      answer={answer}
      requests={[
        {
          id: "mcp-2",
          kind: "elicitation",
          reason: null,
          detail: null,
          summary: "Choose",
          tool: "MCP",
          elicitation: {
            requestedSchema: {
              type: "object",
              properties: {
                colors: { type: "array", items: { type: "string", enum: ["red", "blue"] } },
              },
              required: ["colors"],
            },
          },
        },
      ]}
    />
  )
  await user.selectOptions(screen.getByRole("listbox"), ["red", "blue"])
  await user.click(screen.getByRole("button", { name: "Submit" }))
  expect(answer).toHaveBeenCalledWith({
    action: "answer",
    request: "mcp-2",
    allow: true,
    response: { action: "accept", content: { colors: ["red", "blue"] } },
  })
})

it("executes /compact exactly instead of choosing a fuzzy skill", async () => {
  const user = userEvent.setup(),
    execute = vi.fn()
  function Form() {
    const [text, setText] = useState("")
    const slash = useSlash({
      text,
      setText,
      provider: "codex",
      cwd: "/repo",
      actions: [],
      focus: () => {},
      execute,
    })
    return (
      <div>
        {slash.menu}
        <textarea
          aria-label="Command draft"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => slash.onKey(e)}
        />
      </div>
    )
  }
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  })
  render(<Form />)
  await user.type(screen.getByRole("textbox", { name: "Command draft" }), "/compact")
  await user.keyboard("{Enter}")
  expect(execute).toHaveBeenCalledWith("compact")
})

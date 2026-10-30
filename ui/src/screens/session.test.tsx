import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { TranscriptEvent } from "@/lib/sessions"
import { Message } from "@/screens/session"

const event = (over: Partial<TranscriptEvent>): TranscriptEvent => ({
  i: 1,
  kind: "assistant",
  text: "",
  tool: null,
  ok: null,
  output: "",
  ts: null,
  ...over,
})
const none = () => undefined

describe("an answer in the conversation", () => {
  it("ending a response can be copied, the whole response as Markdown", () => {
    const out = renderToStaticMarkup(
      <Message event={event({ text: "**Done.**" })} copy={"Mined.\n\n**Done.**"} onOpen={none} />
    )
    expect(out).toContain('aria-label="Copy the response"')
  })

  it("inside a response has no copy button, nor do your own messages", () => {
    expect(
      renderToStaticMarkup(<Message event={event({ text: "Mined." })} onOpen={none} />)
    ).not.toContain("Copy")
    const mine = event({ kind: "user", text: "Fix it" })
    expect(renderToStaticMarkup(<Message event={mine} onOpen={none} />)).not.toContain("Copy")
  })

  it("from a Codex automation's heartbeat is a short note with its message", () => {
    const beat =
      "<heartbeat>\n  <automation_id>news</automation_id>\n  <decision>DONT_NOTIFY</decision>\n  <message>Mining is progressing.</message>\n</heartbeat>"
    const out = renderToStaticMarkup(<Message event={event({ text: beat })} onOpen={none} />)
    expect(out).toContain("chat-heartbeat")
    expect(out).toContain("Mining is progressing.")
    expect(out).not.toContain("chat-answer")
  })
})

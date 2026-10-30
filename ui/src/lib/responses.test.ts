import { describe, expect, it } from "vitest"

import { heartbeat, responseEnds } from "@/lib/responses"
import type { TranscriptEvent } from "@/lib/sessions"

const BEAT = `<heartbeat>
  <automation_id>continue-news-discovery-enrichment</automation_id>
  <decision>NOTIFY</decision>
  <message>Mining finished: 96,506 pairs passed leakage checks &amp; are being annotated.</message>
</heartbeat>`

const said = (i: number, kind: string, text: string): TranscriptEvent => ({
  i,
  kind,
  text,
  tool: null,
  ok: null,
  output: "",
  ts: null,
})

describe("a Codex automation's heartbeat", () => {
  it("is read for its automation, whether it notified you, and its message", () => {
    expect(heartbeat(BEAT)).toEqual({
      automation: "continue-news-discovery-enrichment",
      notified: true,
      message: "Mining finished: 96,506 pairs passed leakage checks & are being annotated.",
    })
  })

  it("is nothing else", () => {
    expect(heartbeat("The <decision> was made.")).toBeNull()
    expect(heartbeat("**Done.**")).toBeNull()
  })
})

describe("where a response ends", () => {
  const events = [
    said(1, "user", "Go"),
    said(2, "assistant", "Mining."),
    said(3, "assistant", BEAT),
    said(4, "assistant", "Annotated."),
    said(5, "assistant", "Trained."),
    said(6, "user", "More"),
    said(7, "assistant", "Working on it."),
  ]

  it("is the last answer before your next message, a question or a heartbeat, with its whole text", () => {
    expect([...responseEnds(events, true)]).toEqual([
      [2, "Mining."],
      [5, "Annotated.\n\nTrained."],
      [7, "Working on it."],
    ])
  })

  it("is not yet the answer still being written", () => {
    expect([...responseEnds(events, false).keys()]).toEqual([2, 5])
  })
})

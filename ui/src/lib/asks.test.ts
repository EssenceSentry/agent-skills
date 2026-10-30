import { describe, expect, it } from "vitest"

import { askNote, foldAsks } from "@/lib/asks"
import type { Ask, ChatState, Question, TranscriptEvent } from "@/lib/sessions"

const q = (text: string): Question => ({
  id: null,
  header: null,
  question: text,
  options: [],
  multi: false,
  other: true,
  secret: false,
})

const asked = (i: number, ask: Partial<Ask> & { questions: Question[] }): TranscriptEvent => ({
  i,
  kind: "question",
  text: "",
  tool: "AskUserQuestion",
  ok: null,
  output: "",
  ts: null,
  ask: { via: "claude", call: `c${i}`, status: "answered", answers: null, ...ask },
})

const said = (i: number): TranscriptEvent => ({
  i,
  kind: "assistant",
  text: "ok",
  tool: null,
  ok: null,
  output: "",
  ts: null,
})

describe("questions asked one after another", () => {
  it("fold into one, their questions and answers in order", () => {
    const folded = foldAsks([
      said(1),
      asked(2, { questions: [q("A?"), q("B?")], answers: [["a"], ["b"]] }),
      asked(3, { questions: [q("C?")], status: "declined", answers: null }),
      asked(4, { questions: [q("D?")], answers: [["d"]] }),
      said(5),
    ])
    expect(folded.map((e) => e.i)).toEqual([1, 2, 5])
    const ask = folded[1].ask
    expect(ask?.questions.map((x) => x.question)).toEqual(["A?", "B?", "C?", "D?"])
    expect(ask?.answers).toEqual([["a"], ["b"], null, ["d"]])
    expect(ask?.status).toBe("answered")
  })

  it("keep one still waiting apart from those already answered", () => {
    const folded = foldAsks([
      asked(1, { questions: [q("A?")], answers: [["a"]] }),
      asked(2, { questions: [q("B?")], status: "open", answers: null }),
    ])
    expect(folded.map((e) => e.ask?.status)).toEqual(["answered", "open"])
    expect(folded[1].ask?.call).toBe("c2")
  })

  it("stay apart when anything was said between them", () => {
    const folded = foldAsks([
      asked(1, { questions: [q("A?")] }),
      said(2),
      asked(3, { questions: [q("B?")] }),
    ])
    expect(folded.map((e) => e.i)).toEqual([1, 2, 3])
  })

  it("all declined, stay declined", () => {
    const folded = foldAsks([
      asked(1, { questions: [q("A?")], status: "declined" }),
      asked(2, { questions: [q("B?")], status: "declined" }),
    ])
    expect(folded).toHaveLength(1)
    expect(folded[0].ask?.status).toBe("declined")
  })
})

describe("where a question's row says to answer it", () => {
  const ask: Ask = { via: "claude", call: "c1", status: "open", questions: [], answers: null }
  const chat = (over: Partial<ChatState>) => ({ question: null, ...over }) as ChatState

  it("says nothing once ax, which holds the session, has answered it here", () => {
    expect(askNote(ask, chat({ holder: "ax" }))).toBeUndefined()
  })

  it("says where to answer one waiting in another app", () => {
    expect(askNote(ask, chat({ holder: "elsewhere" }))).toBe(
      "Answer it where this session is open: the Claude app or its terminal."
    )
  })

  it("says nothing for one answered or still waiting here", () => {
    expect(askNote({ ...ask, status: "answered" }, chat({ holder: "elsewhere" }))).toBeUndefined()
    const live = { id: "q", via: "claude" as const, call: "c1", questions: [] }
    expect(askNote(ask, chat({ holder: "elsewhere", question: live }))).toBeUndefined()
  })
})

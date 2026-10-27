import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { QuestionCard } from "@/blocks/question"
import type { Ask } from "@/lib/sessions"

const ask: Ask = {
  via: "claude",
  call: "q1",
  status: "answered",
  questions: [
    {
      id: null,
      header: "Format",
      question: "Which format?",
      options: [
        { label: "Summary", description: "Brief" },
        { label: "Detailed", description: "Full" },
      ],
      multi: false,
      other: true,
      secret: false,
    },
    {
      id: null,
      header: "Sections",
      question: "Which sections?",
      options: [
        { label: "Intro", description: "" },
        { label: "End", description: "" },
      ],
      multi: true,
      other: true,
      secret: false,
    },
  ],
  answers: [["Summary"], ["Intro", "End"]],
}

const html = (props: Parameters<typeof QuestionCard>[0]) =>
  renderToStaticMarkup(<QuestionCard {...props} />)

describe("a question the agent asked", () => {
  it("shows each question, its options, and the ones chosen", () => {
    const out = html({ ask })
    expect(out).toContain("Format")
    expect(out).toContain("Which format?")
    expect(out).toContain("Brief")
    expect(out.match(/data-chosen="true"/g)).toHaveLength(3)
    expect(out).toContain('aria-label="Question: answered"')
  })

  it("shows words typed instead of an option as the answer", () => {
    const out = html({ ask: { ...ask, answers: [["Something else"], null] } })
    expect(out).toContain("Something else")
    expect(out).not.toContain('data-chosen="true"')
  })

  it("offers the options as choices while it waits, with room for other words", () => {
    const out = html({ ask: { ...ask, status: "open", answers: null }, onAnswer: () => undefined })
    expect(out).toContain('type="radio"')
    expect(out).toContain('type="checkbox"')
    expect(out).toContain('aria-label="Other answer to Which format?"')
    expect(out).toContain("Send answers")
  })

  it("says where to answer a question it can't take here", () => {
    const out = html({
      ask: { ...ask, status: "open", answers: null },
      note: "Answer it in the Claude app.",
    })
    expect(out).toContain("Answer it in the Claude app.")
    expect(out).not.toContain("Send answers")
  })

  it("keeps a secret answer's field hidden while typing", () => {
    const secret: Ask = {
      ...ask,
      status: "open",
      answers: null,
      questions: [{ ...ask.questions[0], options: [], secret: true }],
    }
    expect(html({ ask: secret, onAnswer: () => undefined })).toContain('type="password"')
  })

  it("marks a question that was declined", () => {
    expect(html({ ask: { ...ask, status: "declined", answers: null } })).toContain("Not answered")
  })
})

const opened = (out: string) => (out.match(/<details[^>]*\bopen=""/g) ?? []).length

describe("questions folded into an accordion", () => {
  it("keeps a past question folded, its answer on the folded row", () => {
    const out = html({ ask })
    expect(out.match(/<details/g)).toHaveLength(2)
    expect(opened(out)).toBe(0)
    expect(out).toMatch(/<summary[^>]*>.*Intro, End.*<\/summary>/s)
  })

  it("says on the folded row that a declined question went unanswered", () => {
    const out = html({ ask: { ...ask, status: "declined", answers: null } })
    expect(opened(out)).toBe(0)
    expect(out).toMatch(/<summary[^>]*>.*Not answered.*<\/summary>/s)
  })

  it("opens one question at a time while it waits, counting them", () => {
    const out = html({ ask: { ...ask, status: "open", answers: null }, onAnswer: () => undefined })
    expect(opened(out)).toBe(1)
    expect(out).toMatch(/<details[^>]*\bopen=""[^>]*>.*?Which format\?/s)
    expect(out).toContain("1 of 2")
    expect(out).toContain("2 of 2")
  })

  it("shows every question of one it can't take here, to be read", () => {
    const out = html({ ask: { ...ask, status: "open", answers: null }, note: "Answer it there." })
    expect(opened(out)).toBe(2)
  })
})

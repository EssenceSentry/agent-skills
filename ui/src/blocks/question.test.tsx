import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { AskedRow, QuestionPanel } from "@/blocks/question"
import type { Ask, Question } from "@/lib/sessions"

const format: Question = {
  id: null,
  header: "Format",
  question: "Which format?",
  options: [
    { label: "Summary (Recommended)", description: "Brief" },
    { label: "Detailed", description: "Full" },
  ],
  multi: false,
  other: true,
  secret: false,
}
const sections: Question = {
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
}
const ask: Ask = {
  via: "claude",
  call: "q1",
  status: "answered",
  questions: [format, sections],
  answers: [["Summary (Recommended)"], ["Intro", "End"]],
}

const html = (node: React.ReactElement) => renderToStaticMarkup(node)

describe("a question in the conversation, as Codex leaves it", () => {
  it("is one quiet row that opens to each question and its answer", () => {
    const out = html(<AskedRow ask={ask} />)
    expect(out).toContain("Asked")
    expect(out).toContain("2 questions")
    expect(out).not.toMatch(/<details[^>]*\bopen=""/)
    expect(out).toContain("Which sections?")
    expect(out).toContain("Intro, End")
  })

  it("says when a question got no answer", () => {
    const declined = html(<AskedRow ask={{ ...ask, status: "declined", answers: null }} />)
    expect(declined.match(/No answer provided/g)).toHaveLength(2)
    const typed = html(<AskedRow ask={{ ...ask, answers: [["Something else"], null] }} />)
    expect(typed).toContain("Something else")
    expect(typed.match(/No answer provided/g)).toHaveLength(1)
  })

  it("says it is asking, and where to answer, while it waits elsewhere", () => {
    const out = html(
      <AskedRow ask={{ ...ask, status: "open", answers: null }} note="Answer it in the app." />
    )
    expect(out).toMatch(/Asking<\/span>.*?>2 questions</s)
    expect(out).toContain("Answer it in the app.")
  })
})

describe("a question waiting for an answer here", () => {
  const open = (questions: Question[]) =>
    html(<QuestionPanel questions={questions} onAnswer={() => undefined} />)

  it("shows one question at a time, numbered, with a pager", () => {
    const out = open([format, sections])
    expect(out).toContain("Which format?")
    expect(out).not.toContain("Which sections?")
    expect(out).toContain("1 of 2")
    expect(out).toContain('aria-label="Next question"')
    expect(out).toMatch(/type="radio".*?>1</s)
    expect(out).toContain('placeholder="Type here"')
    expect(out).toContain("Skip")
    expect(out).toContain("Continue")
  })

  it("moves on with Continue only once this question has an answer; Skip leaves it", () => {
    expect(open([format, sections])).toMatch(/<button[^>]*disabled=""[^>]*>Continue/)
  })

  it("marks the recommended option with a badge instead of its words", () => {
    const out = open([format])
    expect(out).toContain("Recommended")
    expect(out).not.toContain("(Recommended)")
  })

  it("offers checkboxes for a multiple choice, and submits on the last question", () => {
    const out = open([sections])
    expect(out).toContain('type="checkbox"')
    expect(out).toContain("Submit")
    expect(out).not.toContain("1 of 1")
  })

  it("keeps a secret answer hidden while typing", () => {
    expect(open([{ ...format, options: [], secret: true }])).toContain('type="password"')
  })
})

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react"
import { type KeyboardEvent, useState } from "react"

import { Markdown } from "@/blocks/markdown"
import {
  ChoiceMark,
  ChoiceRow,
  Key,
  Pill,
  plainLabel,
  RequestCard,
  RequestFooter,
  RequestHeading,
} from "@/blocks/request"
import { Button } from "@/components/ui/button"
import type { Ask, Question } from "@/lib/sessions"

const count = (n: number) => `${n} question${n === 1 ? "" : "s"}`

/**
 * A question the agent asked, in the conversation, as Codex leaves one: a quiet row,
 * "Asked 2 questions", that opens to each question and its answer. While it waits
 * somewhere ax can't answer, it says it is asking, and where to answer.
 */
export function AskedRow({ ask, note }: { ask: Ask; note?: string }) {
  const open = ask.status === "open"
  return (
    <div className="space-y-1">
      <details className="chat-asked group text-[13px]">
        <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
          <span className="chat-asked-verb">{open ? "Asking" : "Asked"}</span>
          <span className="chat-asked-count opacity-70">{count(ask.questions.length)}</span>
          <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
        </summary>
        <div className="flex flex-col gap-3 pt-2 pb-0.5">
          {ask.questions.map((q, i) => {
            const given = ask.answers?.[i]
            return (
              // biome-ignore lint/suspicious/noArrayIndexKey: questions keep their order
              <div key={i} className="flex flex-col gap-1">
                <span className="chat-asked-question whitespace-pre-wrap text-foreground/60">
                  {q.question}
                </span>
                <span className="chat-asked-answer whitespace-pre-wrap text-foreground/35">
                  {given?.length
                    ? given.map((a) => plainLabel(a).text).join(", ")
                    : open
                      ? "Waiting for an answer"
                      : "No answer provided"}
                </span>
              </div>
            )
          })}
        </div>
      </details>
      {open && note && <p className="text-xs text-muted-foreground">{note}</p>}
    </div>
  )
}

/**
 * Questions waiting for an answer here, in the message box's place, as Codex asks them:
 * one at a time with a pager, the options numbered (boxes when several may be chosen),
 * room to type something else, and Skip or Continue at the foot; Continue waits for an
 * answer. Picking one of a single choice moves on; a lone single question answers with
 * that one pick. Keys 1–9 pick and Enter moves on.
 */
export function QuestionPanel({
  questions,
  onAnswer,
  onSkipAll,
  busy = false,
}: {
  questions: Question[]
  onAnswer: (answers: string[][]) => void
  /** Leaving every question unanswered: declining them, or setting them aside. */
  onSkipAll?: () => void
  busy?: boolean
}) {
  const [at, setAt] = useState(0)
  const [picked, setPicked] = useState<string[][]>(() => questions.map(() => []))
  const [other, setOther] = useState<string[]>(() => questions.map(() => ""))
  const q = questions[at]
  if (!q) return null
  const last = at === questions.length - 1
  const given = questions.map((_, i) =>
    [...(picked[i] ?? []), other[i]?.trim() ?? ""].filter(Boolean)
  )
  const anything = given.some((a) => a.length > 0)
  const quick = questions.length === 1 && !q.multi

  const finish = () => {
    if (busy) return
    if (anything) onAnswer(given)
    else onSkipAll?.()
  }
  // Continue moves on from an answered question; Skip is the way past an unanswered one.
  const answered = (given[at]?.length ?? 0) > 0
  const next = () => (last ? finish() : answered && setAt(at + 1))
  const choose = (label: string) => {
    if (busy) return
    if (quick && !other[0]?.trim()) return onAnswer([[label]])
    setPicked((was) =>
      was.map((chosen, i) => {
        if (i !== at) return chosen
        if (!q.multi) return [label]
        return chosen.includes(label) ? chosen.filter((l) => l !== label) : [...chosen, label]
      })
    )
    if (!q.multi && !last) setAt(at + 1)
  }
  const skip = () => {
    setPicked((was) => was.map((chosen, i) => (i === at ? [] : chosen)))
    setOther((was) => was.map((t, i) => (i === at ? "" : t)))
    if (!last) setAt(at + 1)
    else if (given.some((a, i) => i !== at && a.length > 0))
      onAnswer(given.map((a, i) => (i === at ? [] : a)))
    else onSkipAll?.()
  }
  const keys = (e: KeyboardEvent<HTMLFormElement>) => {
    if ((e.target as HTMLElement).closest("input[type=text], input[type=password], textarea"))
      return
    const n = Number(e.key)
    if (Number.isInteger(n) && n >= 1 && n <= q.options.length) {
      e.preventDefault()
      choose(q.options[n - 1].label)
    }
  }
  const typed = other[at] ?? ""
  const canSkip = !last || anything || onSkipAll

  return (
    <RequestCard label="Question" onSubmit={next} onKeyDown={keys}>
      <RequestHeading
        label={q.header}
        title={<Markdown className="chat-request-question">{q.question}</Markdown>}
        aside={
          questions.length > 1 && (
            <div className="chat-pager flex shrink-0 items-center gap-0.5 text-[12px] text-muted-foreground">
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="size-6"
                aria-label="Previous question"
                disabled={at === 0}
                onClick={() => setAt(at - 1)}
              >
                <ChevronLeft className="size-3.5" />
              </Button>
              <span className="tabular-nums">
                {at + 1} of {questions.length}
              </span>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="size-6"
                aria-label="Next question"
                disabled={last}
                onClick={() => setAt(at + 1)}
              >
                <ChevronRight className="size-3.5" />
              </Button>
            </div>
          )
        }
      />
      <div className="flex flex-col gap-1 px-2" role="presentation">
        {q.options.map((o, n) => (
          <ChoiceRow
            key={o.label}
            type={q.multi ? "checkbox" : "radio"}
            name={`question-${at}`}
            number={n + 1}
            checked={picked[at]?.includes(o.label) ?? false}
            disabled={busy}
            onChoose={() => choose(o.label)}
            label={o.label}
            description={o.description}
          />
        ))}
        {(q.other || q.options.length === 0) && (
          <label
            data-checked={typed.trim() ? true : undefined}
            className="chat-choice flex min-h-8 w-full items-center gap-2 rounded-xl px-2 py-1.5 text-[13px] focus-within:bg-muted hover:bg-muted"
          >
            {q.options.length > 0 && (
              <ChoiceMark
                type={q.multi ? "checkbox" : "text"}
                number={q.options.length + 1}
                checked={Boolean(typed.trim())}
              />
            )}
            <input
              type={q.secret ? "password" : "text"}
              value={typed}
              disabled={busy}
              onChange={(e) => {
                const text = e.target.value
                setOther((was) => was.map((t, i) => (i === at ? text : t)))
                if (!q.multi && text.trim())
                  setPicked((was) => was.map((chosen, i) => (i === at ? [] : chosen)))
              }}
              placeholder="Type here"
              aria-label={`Other answer to ${q.question}`}
              className="chat-freeform min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
            />
          </label>
        )}
      </div>
      <RequestFooter>
        {canSkip && (
          <Pill kind="ghost" type="button" disabled={busy} onClick={skip}>
            Skip
          </Pill>
        )}
        <Pill kind="primary" type="submit" disabled={busy || (last ? !anything : !answered)}>
          {busy && <Loader2 className="animate-spin" />}
          {last ? "Submit" : "Continue"} <Key>⏎</Key>
        </Pill>
      </RequestFooter>
    </RequestCard>
  )
}

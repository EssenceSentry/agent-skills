import { Check, ChevronRight, CircleHelp, Loader2 } from "lucide-react"
import { useState } from "react"

import { Markdown } from "@/blocks/markdown"
import { Button } from "@/components/ui/button"
import type { Ask } from "@/lib/sessions"
import { cn } from "@/lib/utils"

const CHOICE =
  "chat-option flex w-full cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-muted has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring/50"

/** What a folded row says was answered: the labels or words given, or that none were. */
function answerSaid(answers: string[] | null, status: Ask["status"]): string | null {
  if (answers?.length) return answers.join(", ")
  return status === "open" ? null : "Not answered"
}

/**
 * A question an agent asked, as the apps show one: each question with its header, the
 * options with what each means, and, once answered, the choice checked. Each question
 * folds; a past one stays folded with its answer on its row. While it waits and can be
 * answered here, one question is open at a time, a pick moving on to the next; the
 * options are choices, with room for other words, and a lone single-choice question
 * answers with one click.
 */
export function QuestionCard({
  ask,
  onAnswer,
  note,
  busy = false,
}: {
  ask: Ask
  onAnswer?: (answers: string[][]) => void
  note?: string
  busy?: boolean
}) {
  const open = ask.status === "open"
  const answering = open && Boolean(onAnswer)
  const [picked, setPicked] = useState<string[][]>(() => ask.questions.map(() => []))
  const [other, setOther] = useState<string[]>(() => ask.questions.map(() => ""))
  const quick = ask.questions.length === 1 && !ask.questions[0]?.multi
  const given = ask.questions.map((_, i) =>
    [...(picked[i] ?? []), other[i]?.trim() ?? ""].filter(Boolean)
  )
  const ready = given.some((a) => a.length > 0) && !busy
  const several = ask.questions.length > 1
  // Waiting here: the first question; waiting elsewhere: all of them, to be read; past: none.
  const folds = () => ask.questions.map((_, i) => (answering ? i === 0 : open))
  const [unfolded, setUnfolded] = useState<boolean[]>(folds)
  // Once answered or declined while on screen, it folds like any past question.
  const [status, setStatus] = useState(ask.status)
  if (status !== ask.status) {
    setStatus(ask.status)
    setUnfolded(folds())
  }
  const fold = (i: number, isOpen: boolean) =>
    setUnfolded((was) => (was[i] === isOpen ? was : was.map((o, j) => (j === i ? isOpen : o))))
  const moveOn = (i: number) => {
    if (i + 1 < ask.questions.length) setUnfolded(ask.questions.map((_, j) => j === i + 1))
    else if (ready) onAnswer?.(given)
  }

  const pick = (i: number, label: string, multi: boolean) => {
    if (quick && !other[0]?.trim()) return onAnswer?.([[label]])
    setPicked((was) =>
      was.map((chosen, j) => {
        if (j !== i) return chosen
        if (!multi) return [label]
        return chosen.includes(label) ? chosen.filter((l) => l !== label) : [...chosen, label]
      })
    )
    if (!multi && i + 1 < ask.questions.length) moveOn(i)
  }

  return (
    <section
      className="chat-question rounded-xl border bg-card"
      aria-label={`Question: ${ask.status}`}
    >
      {ask.questions.map((q, i) => {
        const answers = ask.answers?.[i] ?? null
        const labels = new Set(q.options.map((o) => o.label))
        const typed = answers?.filter((a) => !labels.has(a)) ?? []
        const isOpen = unfolded[i] ?? false
        const said = answering
          ? given[i]?.length
            ? given[i].join(", ")
            : null
          : answerSaid(answers, ask.status)
        return (
          <details
            // biome-ignore lint/suspicious/noArrayIndexKey: questions keep their order
            key={i}
            open={isOpen}
            onToggle={(e) => fold(i, e.currentTarget.open)}
            className="chat-question-item group border-t first:border-t-0"
          >
            <summary className="flex cursor-pointer list-none items-start gap-2 px-3.5 py-2.5 [&::-webkit-details-marker]:hidden">
              <CircleHelp className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <div className="min-w-0 flex-1 space-y-1">
                {(q.header || several) && (
                  <div className="chat-question-header flex gap-2 text-[11px] font-medium tracking-wide text-muted-foreground">
                    {q.header && <span className="uppercase">{q.header}</span>}
                    {several && (
                      <span className="ml-auto font-normal tabular-nums">
                        {i + 1} of {ask.questions.length}
                      </span>
                    )}
                  </div>
                )}
                <Markdown
                  className={cn("text-[13.5px] leading-relaxed", !isOpen && "line-clamp-2")}
                >
                  {q.question}
                </Markdown>
                {!isOpen && said && (
                  <p className="chat-question-said flex items-start gap-1.5 text-[13px] text-muted-foreground">
                    <Check className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                    <span className="min-w-0 truncate">{said}</span>
                  </p>
                )}
              </div>
              <ChevronRight
                className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
                aria-hidden
              />
            </summary>
            <div className="space-y-2 px-3.5 pb-3 pl-9">
              {q.options.length > 0 && (
                <ul
                  className="space-y-1"
                  role={answering ? (q.multi ? "group" : "radiogroup") : undefined}
                  aria-label={answering ? q.question : undefined}
                >
                  {q.options.map((o) => {
                    const chosen = answers?.includes(o.label) ?? false
                    const selected = picked[i]?.includes(o.label) ?? false
                    const body = (
                      <>
                        <span
                          className={cn(
                            "chat-option-mark mt-0.5 grid size-4 shrink-0 place-items-center border",
                            q.multi ? "rounded-[4px]" : "rounded-full",
                            (chosen || selected) &&
                              "border-primary bg-primary text-primary-foreground"
                          )}
                          aria-hidden
                        >
                          {(chosen || selected) && <Check className="size-3" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[13px] font-medium">{o.label}</span>
                          {o.description && (
                            <span className="block text-xs text-muted-foreground">
                              {o.description}
                            </span>
                          )}
                        </span>
                      </>
                    )
                    return (
                      <li key={o.label}>
                        {answering ? (
                          <label className={CHOICE}>
                            <input
                              type={q.multi ? "checkbox" : "radio"}
                              name={`${ask.call ?? "question"}-${i}`}
                              checked={selected}
                              disabled={busy}
                              onChange={() => pick(i, o.label, q.multi)}
                              className="sr-only"
                            />
                            {body}
                          </label>
                        ) : (
                          <div
                            data-chosen={chosen ? "true" : undefined}
                            className={cn(
                              "chat-option flex items-start gap-2.5 rounded-lg px-2.5 py-1.5",
                              ask.status === "answered" && !chosen && "opacity-55"
                            )}
                          >
                            {body}
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
              {typed.length > 0 && (
                <p className="px-2.5 text-[13px]">
                  <span className="text-muted-foreground">Your answer: </span>
                  {typed.join(", ")}
                </p>
              )}
              {answering && (q.other || q.options.length === 0) && (
                <input
                  type={q.secret ? "password" : "text"}
                  value={other[i] ?? ""}
                  onChange={(e) =>
                    setOther((was) => was.map((t, j) => (j === i ? e.target.value : t)))
                  }
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return
                    e.preventDefault()
                    moveOn(i)
                  }}
                  placeholder={q.options.length ? "Other…" : "Your answer…"}
                  aria-label={`Other answer to ${q.question}`}
                  className="chat-other w-full rounded-lg border bg-background px-2.5 py-1.5 text-[13px] outline-none focus:border-ring"
                />
              )}
              {answering && q.multi && i + 1 < ask.questions.length && (
                <div className="flex justify-end">
                  <Button size="xs" variant="ghost" onClick={() => moveOn(i)}>
                    Next
                  </Button>
                </div>
              )}
            </div>
          </details>
        )
      })}
      {answering && (!quick || other[0]?.trim()) && (
        <div className="flex justify-end border-t px-3.5 py-2.5">
          <Button size="sm" onClick={() => onAnswer?.(given)} disabled={!ready}>
            {busy && <Loader2 className="animate-spin" />}
            Send answers
          </Button>
        </div>
      )}
      {open && !answering && note && (
        <p className="border-t px-3.5 py-2.5 text-xs text-muted-foreground">{note}</p>
      )}
    </section>
  )
}

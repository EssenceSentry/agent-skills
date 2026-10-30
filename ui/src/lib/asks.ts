/** Questions an agent asked one after another, shown as one row. */

import type { Ask, ChatState, TranscriptEvent } from "@/lib/sessions"

const waiting = (ask: Ask) => ask.status === "open"

function joined(asks: Ask[]): Ask {
  const last = asks[asks.length - 1] as Ask
  const all = asks.every((a) => a.status === "declined")
  return {
    ...last,
    status: waiting(last) ? "open" : all ? "declined" : "answered",
    questions: asks.flatMap((a) => a.questions),
    answers: asks.flatMap((a) => a.answers ?? a.questions.map(() => null)),
  }
}

/**
 * The conversation with each run of questions asked back to back folded into the first
 * of them: their questions and answers in order. Questions still waiting stay apart from
 * those already answered, so one asked now never hides among the past.
 */
export function foldAsks(events: TranscriptEvent[]): TranscriptEvent[] {
  const folded: TranscriptEvent[] = []
  let run: TranscriptEvent[] = []
  const flush = () => {
    const first = run[0]
    if (first?.ask) folded.push({ ...first, ask: joined(run.map((e) => e.ask as Ask)) })
    run = []
  }
  for (const event of events) {
    const ask = event.kind === "question" ? event.ask : undefined
    const previous = run[run.length - 1]?.ask
    if (ask && previous && waiting(ask) === waiting(previous)) run.push(event)
    else {
      flush()
      if (ask) run = [event]
      else folded.push(event)
    }
  }
  flush()
  return folded
}

const ELSEWHERE: Record<Ask["via"], string> = {
  claude: "Answer it where this session is open: the Claude app or its terminal.",
  codex: "Answer it in the Codex app.",
  "codex-async": "Answer it in the Codex app.",
}

/**
 * Where a question's row says to answer it: nowhere once it is answered, or while it
 * waits in the message box's place; nowhere either when ax holds the session, where it
 * was answered here and the transcript hasn't caught up; else in the app that has it.
 */
export function askNote(ask: Ask, chat?: ChatState | null): string | undefined {
  if (ask.status !== "open" || chat?.holder === "ax") return undefined
  const live = chat?.question
  if (live && (!live.call || live.call === ask.call)) return undefined
  if (ask.via === "codex-async" && chat?.holder !== "elsewhere") return undefined
  return ELSEWHERE[ask.via]
}

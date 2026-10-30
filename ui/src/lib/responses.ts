/** What a conversation's answers add up to: whole responses, and Codex's heartbeats. */

import type { TranscriptEvent } from "@/lib/sessions"

export type Heartbeat = { automation: string | null; notified: boolean; message: string }

const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
}

function tag(text: string, name: string): string | null {
  const found = text.match(new RegExp(`<${name}>([\\s\\S]*?)</${name}>`))?.[1]
  return found === undefined
    ? null
    : found.trim().replace(/&(amp|lt|gt|quot|#39);/g, (e) => ENTITIES[e] ?? e)
}

/**
 * A Codex automation's report, `<heartbeat>` with its id, its decision to notify you or
 * not and its message, which Markdown would show as nothing; null for any other text.
 */
export function heartbeat(text: string): Heartbeat | null {
  const body = text.trim()
  if (!body.startsWith("<heartbeat>") || !body.endsWith("</heartbeat>")) return null
  return {
    automation: tag(body, "automation_id"),
    notified: tag(body, "decision") === "NOTIFY",
    message: tag(body, "message") ?? "",
  }
}

/**
 * Where each response ends: the last answer of a run that your next message, a question
 * or a heartbeat closes, with the run's whole text. The run still being written ends
 * nowhere yet.
 */
export function responseEnds(events: TranscriptEvent[], finished: boolean): Map<number, string> {
  const ends = new Map<number, string>()
  let run: TranscriptEvent[] = []
  const close = () => {
    const last = run[run.length - 1]
    if (last) ends.set(last.i, run.map((e) => e.text.trim()).join("\n\n"))
    run = []
  }
  for (const event of events) {
    if (event.kind === "assistant" && !heartbeat(event.text)) {
      if (event.text.trim()) run.push(event)
    } else close()
  }
  if (finished) close()
  return ends
}

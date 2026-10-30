import type { Goal } from "@/lib/sessions"

/** A file, a folder or the editor's selection, sent with a message for the agent to read. */
export type Reference =
  | { kind: "file" | "folder"; path: string }
  | {
      kind: "selection"
      path: string
      start: number
      end: number
      text: string
      language: string
    }

/** Where the modes and goal of a session are set when ax can't change them: in the Codex
 * app that has it open, or by taking it over from the Claude app or terminal that does;
 * null when ax holds it or nothing does. */
export function modesElsewhere(holder: string | null | undefined): string | null {
  if (holder === "codex app") return "Set its modes in the Codex app"
  if (holder === "elsewhere") return "Take it over to set its modes"
  return null
}

export function referenceKey(ref: Reference): string {
  const parts: string[] = []
  for (const part of ref.path.replace(/\\/g, "/").split("/")) {
    if (part === ".") continue
    if (part === ".." && parts.length > 1) parts.pop()
    else parts.push(part)
  }
  const path = parts.join("/")
  return `${ref.kind}:${path}:${ref.kind === "selection" ? `${ref.start}:${ref.end}` : ""}`
}

/** Keep chip order while refreshing reattached selections from the current editor buffer. */
export function mergeReferences(was: Reference[], incoming: Reference[]): Reference[] {
  const refs = new Map(was.map((ref) => [referenceKey(ref), ref]))
  for (const ref of incoming) refs.set(referenceKey(ref), ref)
  return [...refs.values()]
}

export function referenceLabel(ref: Reference): string {
  if (ref.kind !== "selection")
    return ref.kind === "folder"
      ? `${ref.path.split("/").slice(-2).join("/")}/`
      : ref.path.split("/").slice(-2).join("/")
  const lines = ref.start === ref.end ? `${ref.start}` : `${ref.start}–${ref.end}`
  return `${ref.path.split("/").slice(-2).join("/")}:${lines}`
}

/**
 * The message with its references after the words: files and folders by path, for the
 * agent to open, and a selection as the code itself with where it comes from. Either tool
 * reads them the same way.
 */
export function withReferences(text: string, refs: Reference[]): string {
  const parts = text.trim() ? [text.trim()] : []
  const paths = refs.filter((r) => r.kind !== "selection")
  if (paths.length)
    parts.push(
      `Files:\n${paths.map((r) => `- \`${r.path}${r.kind === "folder" ? "/" : ""}\``).join("\n")}`
    )
  for (const r of refs)
    if (r.kind === "selection") {
      const lines = r.start === r.end ? `line ${r.start}` : `lines ${r.start}–${r.end}`
      const code = r.text.replace(/\n+$/, "")
      parts.push(`Selected in \`${r.path}\`, ${lines}:\n\`\`\`${r.language}\n${code}\n\`\`\``)
    }
  return parts.join("\n\n")
}

const EFFORTS: Record<string, string> = {
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
  ultra: "Ultra",
}

/** An effort as people say it: "Extra high", not "xhigh". */
export const effortLabel = (effort: string): string => EFFORTS[effort] ?? effort

const STATUS: Record<string, string> = {
  active: "Active",
  paused: "Paused",
  blocked: "Blocked",
  usageLimited: "Usage limit reached",
  budgetLimited: "Budget reached",
  complete: "Complete",
  set: "Set",
}

function tokens(n: number): string {
  if (n < 1000) return `${n}`
  const k = n / 1000
  return `${Number.isInteger(k) || k >= 10 ? Math.round(k) : Number(k.toFixed(1))}k`
}

function spent(seconds: number): string {
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

/** A goal's progress in one line: its status, the time spent and the tokens. */
export function goalLine(goal: Goal): string {
  const parts = [STATUS[goal.status] ?? goal.status]
  if (goal.seconds !== null) parts.push(spent(goal.seconds))
  if (goal.tokens_used !== null)
    parts.push(
      goal.token_budget
        ? `${tokens(goal.tokens_used)} of ${tokens(goal.token_budget)} tokens`
        : `${tokens(goal.tokens_used)} tokens`
    )
  return parts.join(" · ")
}

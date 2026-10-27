import type { ChatState, Goal } from "@/lib/sessions"

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

const base = (path: string) => path.split("/").filter(Boolean).at(-1) ?? path

export function referenceLabel(ref: Reference): string {
  if (ref.kind !== "selection") return ref.kind === "folder" ? `${base(ref.path)}/` : base(ref.path)
  const lines = ref.start === ref.end ? `${ref.start}` : `${ref.start}–${ref.end}`
  return `${base(ref.path)}:${lines}`
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
}

/** An effort as people say it: "Extra high", not "xhigh". */
export const effortLabel = (effort: string): string => EFFORTS[effort] ?? effort

/** The model picker's reading: the model the session runs and its effort, and the choices. */
export function modelChoice(chat: ChatState) {
  const models = chat.models ?? []
  const settings = chat.settings
  if (!settings || !models.length) return null
  const model = models.find((m) => m.id === (settings.model ?? "default")) ?? models[0]
  if (!model) return null
  const effort = settings.effort ?? (settings.model ? model.default_effort : null)
  return {
    label: effort ? `${model.label} · ${effortLabel(effort)}` : model.label,
    model: model.id,
    effort,
    efforts: model.efforts,
  }
}

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

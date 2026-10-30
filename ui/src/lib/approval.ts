/** What an approval asks, worded as Codex words its approval cards. */

import type { Approval } from "@/lib/sessions"

export type ApprovalAsked = {
  /** The identity line above the question: the terminal, file edits, or the tool. */
  label: string
  title: string
  /** The command it would run. */
  command: string | null
  /** The files it would edit, when the request names them. */
  files: string[]
  /** What it would be given, for any other tool. */
  detail: string | null
}

const COMMANDS = new Set(["Bash", "commandExecution"])
const EDITS = new Set(["Edit", "Write", "MultiEdit", "NotebookEdit", "fileChange"])

function given(detail: string | null): Record<string, unknown> {
  try {
    const found = JSON.parse(detail ?? "")
    return found && typeof found === "object" ? found : {}
  } catch {
    return {}
  }
}

/** The text between the first pair of backticks: how the server quotes a command. */
const quoted = (summary: string) => summary.match(/`([^`]+)`/)?.[1] ?? null

export function describeApproval(approval: Approval, provider: string): ApprovalAsked {
  const actor = provider === "codex" ? "Codex" : "Claude"
  const input = given(approval.detail)
  if (COMMANDS.has(approval.tool)) {
    const command = typeof input.command === "string" ? input.command : quoted(approval.summary)
    return {
      label: "Terminal",
      title: `Do you want ${actor} to run this command?`,
      command,
      files: [],
      detail: null,
    }
  }
  if (EDITS.has(approval.tool)) {
    const path = input.file_path ?? input.notebook_path
    const changes = Array.isArray(input.changes)
      ? (input.changes as { path?: string; diff?: string }[])
      : []
    const files =
      typeof path === "string"
        ? [path]
        : changes.flatMap((change) => (change.path ? [change.path] : []))
    const patch =
      typeof input._patch === "string"
        ? input._patch
        : changes
            .map((change) => change.diff ?? "")
            .filter(Boolean)
            .join("\n\n")
    const where = approval.summary.match(/ under (.+)$/)?.[1]
    const what = files.length ? "this file" : where ? `files under ${where}` : "files"
    return {
      label: "Edit files",
      title: `Do you want ${actor} to edit ${what}?`,
      command: null,
      files,
      detail:
        patch ||
        `Proposed patch unavailable from this provider.\n${approval.detail ?? "No edit payload was supplied."}`,
    }
  }
  return {
    label: approval.tool,
    title: `Do you want ${actor} to ${approval.summary.replaceAll("`", "")}?`,
    command: null,
    files: [],
    detail: approval.detail,
  }
}

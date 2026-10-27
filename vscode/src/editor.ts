import * as vscode from "vscode"

import { call } from "./bridge"
import {
  type Base,
  type Before,
  type BeforeSide,
  beforeQuery,
  changed,
  changesTitle,
  readBeforeQuery,
} from "./changes"
import type { FileTarget } from "./links"

/** A file an answer names, beside the session and at its line; a folder in the explorer. */
export async function openFile({ path, line, column }: FileTarget) {
  const uri = vscode.Uri.file(path)
  let stat: vscode.FileStat
  try {
    stat = await vscode.workspace.fs.stat(uri)
  } catch {
    return void vscode.window.showWarningMessage(`No file at ${path}`)
  }
  if (stat.type & vscode.FileType.Directory) {
    const inside = vscode.workspace.getWorkspaceFolder(uri)
    return void vscode.commands.executeCommand(inside ? "revealInExplorer" : "revealFileInOS", uri)
  }
  const at = line ? new vscode.Position(line - 1, Math.max((column ?? 1) - 1, 0)) : undefined
  await vscode.commands.executeCommand("vscode.open", uri, {
    viewColumn: vscode.ViewColumn.Beside,
    preview: true,
    ...(at ? { selection: new vscode.Range(at, at) } : {}),
  })
}

export const BEFORE_SCHEME = "ax-before"

/**
 * The left side of a session's diff: each file as the ax server says it was, kept from
 * the read that decided to show it, or read again after a restart.
 */
export class BeforeFiles implements vscode.TextDocumentContentProvider {
  private readonly known = new Map<string, Before>()

  constructor(private readonly server: () => string) {}

  uri(path: string, side: BeforeSide): vscode.Uri {
    return vscode.Uri.from({ scheme: BEFORE_SCHEME, path, query: beforeQuery(side) })
  }

  /** An empty right side, for a file the session removed. */
  gone(path: string): vscode.Uri {
    return vscode.Uri.from({ scheme: BEFORE_SCHEME, path, query: "gone" })
  }

  /** The file as it was, or why the server can't say. */
  async read(path: string, side: BeforeSide): Promise<Before | string> {
    const query = new URLSearchParams({ ...side, path })
    const answer = await call(this.server(), "GET", `/api/session/before?${query}`)
    if (answer.status !== 200)
      return (answer.body as { error?: string } | null)?.error ?? `ax answered ${answer.status}`
    const before = answer.body as Before
    this.known.set(this.uri(path, side).toString(), before)
    return before
  }

  async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    const kept = this.known.get(uri.toString())
    if (kept) return kept.text
    const side = readBeforeQuery(uri.query)
    if (!side) return ""
    const found = await this.read(uri.path, side)
    return typeof found === "string" ? "" : found.text
  }
}

async function textNow(path: string): Promise<string | null> {
  try {
    return new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.file(path)))
  } catch {
    return null
  }
}

export type Shown = { provider: "claude" | "codex"; id: string; name: string }

/**
 * What a session changed with its edit tools, in VS Code's multi-file diff: since its
 * latest turn began, or since the last commit. Files back as they were are left out.
 */
export async function showChanges(files: BeforeFiles, server: string, session: Shown, base: Base) {
  const query = new URLSearchParams({ provider: session.provider, id: session.id })
  const answer = await call(server, "GET", `/api/session/changes?${query}`)
  if (answer.status !== 200) {
    const error = (answer.body as { error?: string } | null)?.error
    return void vscode.window.showWarningMessage(error ?? `ax answered ${answer.status}`)
  }
  const listed = answer.body as { turn: string[]; session: string[] }
  const side: BeforeSide = { provider: session.provider, id: session.id, base }
  const read = await Promise.all(
    (base === "turn" ? listed.turn : listed.session).map(async (path) => ({
      path,
      before: await files.read(path, side),
      now: await textNow(path),
    }))
  )
  const skipped = read.flatMap((f) => (typeof f.before === "string" ? [f.before] : []))
  const shown = read.flatMap(({ path, before, now }) =>
    typeof before !== "string" && changed(before, now)
      ? [
          [
            vscode.Uri.file(path),
            files.uri(path, side),
            now === null ? files.gone(path) : vscode.Uri.file(path),
          ],
        ]
      : []
  )
  if (skipped.length)
    void vscode.window.showWarningMessage(
      `${skipped.length === 1 ? "1 file" : `${skipped.length} files`} not shown: ${skipped[0]}`
    )
  if (!shown.length) {
    const when = base === "turn" ? "this turn" : "since the last commit"
    return void vscode.window.showInformationMessage(
      `${session.name}: nothing its edit tools changed differs ${when}. Edits made through shell commands aren't recorded.`
    )
  }
  await vscode.commands.executeCommand(
    "vscode.changes",
    changesTitle(session.name, base, shown.length),
    shown
  )
}

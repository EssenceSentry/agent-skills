import { basename, dirname } from "node:path"
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
import { fileReference, type Reference, selectionReference } from "./selection"

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

let lastEditor: vscode.TextEditor | undefined

/** Remembers the editor last used, since a click in a session's tab takes the focus. */
export function followEditors(): vscode.Disposable {
  lastEditor = vscode.window.activeTextEditor
  return vscode.window.onDidChangeActiveTextEditor((editor) => {
    if (editor) lastEditor = editor
  })
}

/** The code selected in the editor last used, or nothing. */
export function currentSelection(): Reference | null {
  const editor =
    lastEditor && !lastEditor.document.isClosed
      ? lastEditor
      : vscode.window.visibleTextEditors.find((e) => !e.selection.isEmpty)
  if (!editor) return null
  const { selection, document } = editor
  return selectionReference({
    path: document.uri.fsPath,
    startLine: selection.start.line,
    endLine: selection.end.line,
    endCharacter: selection.end.character,
    text: document.getText(selection),
    languageId: document.languageId,
  })
}

const SKIP = "{**/node_modules/**,**/.git/**,**/.venv/**,**/dist/**,**/__pycache__/**}"

async function browse(): Promise<Reference[]> {
  const uris = await vscode.window.showOpenDialog({
    canSelectFiles: true,
    canSelectFolders: true,
    canSelectMany: true,
    openLabel: "Send with the message",
  })
  return Promise.all(
    (uris ?? []).map(async (uri) => {
      const { type } = await vscode.workspace.fs.stat(uri)
      return fileReference(uri.fsPath, (type & vscode.FileType.Directory) !== 0)
    })
  )
}

type FileItem = vscode.QuickPickItem & { uri?: vscode.Uri }

/** Files of the workspace to send with a message, or any file or folder to browse for. */
export async function pickFiles(): Promise<Reference[]> {
  const found = vscode.workspace.workspaceFolders?.length
    ? await vscode.workspace.findFiles("**/*", SKIP, 5000)
    : []
  if (!found.length) return browse()
  const other: FileItem = { label: "$(folder-opened) Browse files and folders…", alwaysShow: true }
  const files: FileItem[] = found
    .map((uri) => ({ uri, relative: vscode.workspace.asRelativePath(uri) }))
    .sort((a, b) => a.relative.localeCompare(b.relative))
    .map(({ uri, relative }) => ({
      label: basename(uri.fsPath),
      description: dirname(relative) === "." ? "" : dirname(relative),
      uri,
    }))
  const chosen = await vscode.window.showQuickPick([other, ...files], {
    canPickMany: true,
    matchOnDescription: true,
    placeHolder: "Files to send with the message",
  })
  if (!chosen?.length) return []
  const picked = chosen.flatMap((c) => (c.uri ? [fileReference(c.uri.fsPath, false)] : []))
  return chosen.includes(other) ? [...picked, ...(await browse())] : picked
}

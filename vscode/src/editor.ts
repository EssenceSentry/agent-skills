import { execFile } from "node:child_process"
import { open } from "node:fs/promises"
import { basename, dirname } from "node:path"
import { promisify } from "node:util"
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
import { openWith } from "./opening"
import { fileReference, type Reference, selectionReference } from "./selection"

let editors: string[] | undefined

/** The file patterns installed editors claim: pictures and media built in, PDFs by extension. */
function editorPatterns(): string[] {
  editors ??= vscode.extensions.all.flatMap((extension) =>
    ((extension.packageJSON?.contributes?.customEditors ?? []) as { selector?: unknown[] }[])
      .flatMap((editor) => editor.selector ?? [])
      .map((selector) => (selector as { filenamePattern?: string }).filenamePattern)
      .filter((pattern): pattern is string => typeof pattern === "string")
  )
  return editors
}

/** Forget the patterns when extensions come or go. */
export function followExtensions(): vscode.Disposable {
  return vscode.extensions.onDidChange(() => {
    editors = undefined
  })
}

/** Whether a file reads as text: no NUL byte in its first 8 KB. */
async function looksText(path: string): Promise<boolean> {
  const file = await open(path, "r")
  try {
    const head = Buffer.alloc(8192)
    const { bytesRead } = await file.read(head, 0, head.length, 0)
    return !head.subarray(0, bytesRead).includes(0)
  } finally {
    await file.close()
  }
}

/**
 * A file an answer names: in VS Code beside the session, at its line, when VS Code can
 * show it (text, pictures, PDFs with a viewer), else in its own app; a folder in Finder.
 */
export async function openFile({ path, line, column }: FileTarget) {
  const uri = vscode.Uri.file(path)
  let stat: vscode.FileStat
  try {
    stat = await vscode.workspace.fs.stat(uri)
  } catch {
    return void vscode.window.showWarningMessage(`No file at ${path}`)
  }
  if (stat.type & vscode.FileType.Directory) return void vscode.env.openExternal(uri)
  const text = await looksText(path).catch(() => false)
  // A web page goes to the system's browser, as a file the system opens with it.
  if (openWith(path, { editors: editorPatterns(), text, line }) !== "editor")
    return void vscode.env.openExternal(uri)
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
    const answer = await call(side.server ?? this.server(), "GET", `/api/session/before?${query}`)
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

export type Shown = {
  provider: "claude" | "codex"
  id: string
  name: string
  cwd?: string | null
  server?: string
}

/**
 * What a session changed with its edit tools, in VS Code's multi-file diff: since its
 * latest turn began, or since the last commit. Files back as they were are left out.
 */
export async function showChanges(files: BeforeFiles, server: string, session: Shown, base: Base) {
  const query = new URLSearchParams({ provider: session.provider, id: session.id })
  const answer = await call(
    server,
    "GET",
    base === "commit" && session.cwd
      ? `/api/session/workspace?cwd=${encodeURIComponent(session.cwd)}`
      : `/api/session/changes?${query}`
  )
  if (answer.status !== 200) {
    const error = (answer.body as { error?: string } | null)?.error
    return void vscode.window.showWarningMessage(error ?? `ax answered ${answer.status}`)
  }
  const listed = answer.body as {
    turn: string[]
    session: string[]
    paths?: string[]
    coverage?: string
  }
  if (listed.coverage) void vscode.window.showInformationMessage(listed.coverage)
  const side: BeforeSide = { provider: session.provider, id: session.id, base, server }
  const read = await Promise.all(
    (base === "turn" ? listed.turn : (listed.paths ?? listed.session)).map(async (path) => ({
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

export async function completeFiles(query: string): Promise<Reference[]> {
  const match = /^(.*?)(?::(\d+)(?:[-–](\d+))?)?$/.exec(query)
  const needle = (match?.[1] ?? query).toLowerCase()
  const files = await vscode.workspace.findFiles("**/*", SKIP, 5000)
  const chosen = files.filter((uri) => uri.fsPath.toLowerCase().includes(needle)).slice(0, 30)
  const rows: Reference[] = []
  for (const uri of chosen) {
    if (match?.[2]) {
      const document = await vscode.workspace.openTextDocument(uri)
      const start = Math.max(1, Math.min(document.lineCount, Number(match[2])))
      const end = Math.max(start, Math.min(document.lineCount, Number(match[3] ?? start)))
      rows.push({
        kind: "selection",
        path: uri.fsPath,
        start,
        end,
        text: document.getText(
          new vscode.Range(start - 1, 0, end - 1, document.lineAt(end - 1).text.length)
        ),
        language: document.languageId,
      })
    } else rows.push(fileReference(uri.fsPath, false))
  }
  if (!match?.[2]) {
    const folders = [...new Set(files.map((uri) => dirname(uri.fsPath)))]
      .filter((path) => path.toLowerCase().includes(needle))
      .slice(0, 10)
    rows.push(...folders.map((path) => fileReference(path, true)))
  }
  return rows
}

export async function currentContext(): Promise<Reference[]> {
  const editor =
    lastEditor && !lastEditor.document.isClosed ? lastEditor : vscode.window.activeTextEditor
  if (!editor) return []
  if (editor.document.uri.scheme === "file") {
    const path = editor.document.uri.fsPath
    try {
      await promisify(execFile)(
        "git",
        ["-C", dirname(path), "check-ignore", "--quiet", "--", path],
        { timeout: 2000 }
      )
      return []
    } catch (error) {
      // Exit 1 means explicitly not ignored. Missing git/non-repositories do not
      // attach an automatic file; users can attach them explicitly.
      if ((error as { code?: number }).code !== 1) return []
    }
  }
  const selection = currentSelection()
  return [
    ...(editor.document.uri.scheme === "file"
      ? [fileReference(editor.document.uri.fsPath, false)]
      : []),
    ...(selection ? [selection] : []),
  ]
}

export function problemsContext(): Reference[] {
  const lines = vscode.languages
    .getDiagnostics()
    .flatMap(([uri, diagnostics]) =>
      diagnostics.map(
        (item) =>
          `${uri.fsPath}:${item.range.start.line + 1}: ${vscode.DiagnosticSeverity[item.severity]}: ${item.message}`
      )
    )
    .slice(0, 300)
  if (!lines.length) throw new Error("There are no Problems to attach")
  return [
    {
      kind: "selection",
      path: "VS Code Problems",
      start: 1,
      end: lines.length,
      text: lines.join("\n"),
      language: "text",
    },
  ]
}

export async function terminalContext(): Promise<Reference[]> {
  const terminal = vscode.window.activeTerminal
  if (!terminal) throw new Error("Select output in a terminal first")
  const previous = await vscode.env.clipboard.readText()
  try {
    await vscode.commands.executeCommand("workbench.action.terminal.copySelection")
    const text = await vscode.env.clipboard.readText()
    if (!text || text === previous)
      throw new Error(
        "Select terminal output before attaching it, or paste copied output into the message"
      )
    return [
      {
        kind: "selection",
        path: `Terminal: ${terminal.name}`,
        start: 1,
        end: text.split("\n").length,
        text: text.slice(-60000),
        language: "text",
      },
    ]
  } finally {
    await vscode.env.clipboard.writeText(previous)
  }
}

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

/** A folder for a new session to start in, from the system's dialog; null when none is. */
export async function pickFolder(): Promise<string | null> {
  const [chosen] =
    (await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: "Start here",
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
    })) ?? []
  return chosen?.fsPath ?? null
}

/** The workspace's folders, the active file's first: where a new session usually starts. */
export function workspaceFolders(): string[] {
  const active = vscode.window.activeTextEditor?.document.uri
  const here = active && vscode.workspace.getWorkspaceFolder(active)
  const folders = [here, ...(vscode.workspace.workspaceFolders ?? [])]
    .filter((f): f is vscode.WorkspaceFolder => Boolean(f))
    .map((f) => f.uri.fsPath)
  return [...new Set(folders)]
}

/** A notebook beside the session, scrolled to a cell (counted from 0) with it selected. */
export async function openNotebook(path: string, cell: number | null): Promise<void> {
  const document = await vscode.workspace.openNotebookDocument(vscode.Uri.file(path))
  const at =
    cell !== null && cell >= 0 && cell < document.cellCount
      ? new vscode.NotebookRange(cell, cell + 1)
      : undefined
  const editor = await vscode.window.showNotebookDocument(document, {
    viewColumn: vscode.ViewColumn.Beside,
    preview: false,
    ...(at ? { selections: [at] } : {}),
  })
  if (at) editor.revealRange(at, vscode.NotebookEditorRevealType.InCenter)
}

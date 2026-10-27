/** What a message can carry from the editor: a file, a folder, or the selected code. */

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

export type Selected = {
  path: string
  /** Lines and the end's character as VS Code counts them, from zero. */
  startLine: number
  endLine: number
  endCharacter: number
  text: string
  languageId: string
}

/**
 * The selection with its lines counted from one; a selection ending at the start of a
 * line doesn't take that line.
 */
export function selectionReference(s: Selected): Reference | null {
  if (!s.text) return null
  const last = s.endCharacter === 0 && s.endLine > s.startLine ? s.endLine - 1 : s.endLine
  return {
    kind: "selection",
    path: s.path,
    start: s.startLine + 1,
    end: last + 1,
    text: s.text,
    language: s.languageId,
  }
}

export function fileReference(path: string, isDirectory: boolean): Reference {
  return { kind: isDirectory ? "folder" : "file", path }
}

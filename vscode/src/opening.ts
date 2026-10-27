/** Where a file an answer names opens: in VS Code when it can show it, else in its app. */

import { posix } from "node:path"

import { fileTarget } from "./links"

/** Whether a file name fits an editor's pattern, such as `*.{png,jpg}` or `**\/*.ipynb`. */
export function globMatches(pattern: string, name: string): boolean {
  const glob = pattern.replace(/^(\*\*\/)+/, "")
  let source = ""
  for (const ch of glob) {
    if (ch === "*") source += "[^/]*"
    else if (ch === "?") source += "[^/]"
    else if (ch === "{") source += "(?:"
    else if (ch === "}") source += ")"
    else if (ch === ",") source += "|"
    else source += ch.replace(/[.+^$()|[\]\\]/g, "\\$&")
  }
  return new RegExp(`^${source}$`, "i").test(name)
}

/**
 * VS Code takes text, and whatever an installed editor claims (its built-in pictures and
 * media, a PDF viewer extension); the rest opens in the app the system gives it.
 */
export function openWith(
  path: string,
  how: { editors: string[]; text: boolean }
): "editor" | "app" {
  const name = posix.basename(path)
  if (how.editors.some((pattern) => globMatches(pattern, name))) return "editor"
  return how.text ? "editor" : "app"
}

/** Why a relative path can't be opened: the session's folder isn't known. */
export function unplaced(href: string, cwd: string | null): string | null {
  if (cwd) return null
  const placed = fileTarget(href, "/", "/")
  if (!placed || fileTarget(href, null, "/")) return null
  return `This session's folder isn't known, so ${placed.path.slice(1)} can't be found.`
}

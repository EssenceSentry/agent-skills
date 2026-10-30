/** Where a file an answer names opens: in VS Code when it can show it, a web page in the
 * browser, else in its app. */

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
 * A web page opens in the browser, drawn, unless the link names a line in it, which is
 * about its code. VS Code takes text, and whatever an installed editor claims (its
 * built-in pictures and media, a PDF viewer extension); the rest opens in the app the
 * system gives it.
 */
export function openWith(
  path: string,
  how: { editors: string[]; text: boolean; line?: number | null }
): "editor" | "browser" | "app" {
  const name = posix.basename(path)
  if (/\.html?$/i.test(name) && !how.line) return "browser"
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

/** Where saving a page's Markdown, such as a plan, starts: the session's folder (home
 * without one), under the name the page gave, kept to a file name. */
export function saveStart(cwd: unknown, name: unknown, home: string): string {
  const file = typeof name === "string" ? posix.basename(name) : ""
  const folder = typeof cwd === "string" && cwd ? cwd : home
  return posix.join(folder, file.endsWith(".md") ? file : "plan.md")
}

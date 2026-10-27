import { posix } from "node:path"

/** A file to open, and where in it. */
export type FileTarget = { path: string; line?: number; column?: number }

function decoded(text: string): string {
  try {
    return decodeURIComponent(text)
  } catch {
    return text
  }
}

/**
 * The file an answer's link or path names: absolute, relative to the session's folder, or
 * under home, with `:line`, `:line:col` or `#L12` at the end. Web links and the app's own
 * pages (`/jobs/…`) aren't files.
 */
export function fileTarget(href: string, cwd: string | null, home: string): FileTarget | null {
  let text = href.trim()
  if (text.startsWith("file://")) text = text.slice("file://".length)
  else if (/^[a-z][a-z0-9+.-]*:/i.test(text) || text.startsWith("#") || text.startsWith("/jobs/"))
    return null
  if (!text) return null
  let line: number | undefined
  let column: number | undefined
  const anchor = text.match(/#L(\d+)(?:-L?\d+)?$/)
  if (anchor) {
    line = Number(anchor[1])
    text = text.slice(0, anchor.index)
  }
  const place = text.match(/:(\d+)(?::(\d+))?$/)
  if (place && line === undefined) {
    line = Number(place[1])
    column = place[2] ? Number(place[2]) : undefined
    text = text.slice(0, place.index)
  }
  text = decoded(text)
  let path: string
  if (text.startsWith("/")) path = text
  else if (text === "~" || text.startsWith("~/")) path = home + text.slice(1)
  else if (cwd) path = posix.join(cwd, text)
  else return null
  return {
    path: posix.normalize(path),
    ...(line ? { line } : {}),
    ...(column ? { column } : {}),
  }
}

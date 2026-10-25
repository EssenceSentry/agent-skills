import { useEffect, useState } from "react"

export type Route =
  | { screen: "now" }
  | { screen: "help" }
  | { screen: "notes"; dir: string }
  | { screen: "read"; path: string }

function decode(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

// The same escaping as the server's `quote(path, safe="/")`, so links it writes into
// notes and links the app writes agree.
function encodePath(path: string): string {
  return path
    .split("/")
    .map((part) =>
      encodeURIComponent(part).replace(
        /[!'()*]/g,
        (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`
      )
    )
    .join("/")
}

export function parseRoute(hash: string): Route {
  const h = hash.replace(/^#/, "")
  if (h === "/notes" || h.startsWith("/notes/")) {
    return { screen: "notes", dir: decode(h.slice("/notes/".length)) }
  }
  if (h.startsWith("/read/")) return { screen: "read", path: decode(h.slice("/read/".length)) }
  if (h === "/help") return { screen: "help" }
  return { screen: "now" }
}

export const readHref = (path: string) => `#/read/${encodePath(path)}`
export const folderHref = (dir: string) => (dir ? `#/notes/${encodePath(dir)}` : "#/notes")

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    const update = () => {
      setRoute(parseRoute(window.location.hash))
      window.scrollTo({ top: 0 })
    }
    window.addEventListener("hashchange", update)
    return () => window.removeEventListener("hashchange", update)
  }, [])
  return route
}

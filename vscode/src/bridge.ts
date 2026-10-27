/**
 * The page's way to ax. A webview may not call the ax server itself (its origin isn't the
 * app's, so actions would be refused), so it asks the extension, which forwards the few
 * requests a conversation needs from this Mac.
 */

export type BridgeRequest = {
  type: "request"
  id: number
  method: "GET" | "POST"
  path: string
  body?: unknown
}

export type BridgeReply = { type: "reply"; id: number; status: number; body: unknown }

const ROUTES: Record<string, "GET" | "POST"> = {
  "/api/sessions": "GET",
  "/api/session": "GET",
  "/api/chat": "POST",
}

const BASE = "http://ax.invalid"

/** Listing sessions, reading one and acting on a chat; nothing else, however it's spelt. */
export function allowed(method: string, path: string): boolean {
  if (!path.startsWith("/") || path.startsWith("//")) return false
  const url = new URL(path, BASE)
  if (url.origin !== BASE) return false
  const route = ROUTES[url.pathname]
  return route === method && path.split("?")[0] === url.pathname
}

const offline = (server: string) =>
  `ax isn't answering at ${server}: start it with \`ax app start\``

export async function forward(
  server: string,
  request: BridgeRequest,
  fetchFn: typeof fetch = fetch
): Promise<BridgeReply> {
  const reply = (status: number, body: unknown): BridgeReply => ({
    type: "reply",
    id: request.id,
    status,
    body,
  })
  if (!allowed(request.method, request.path))
    return reply(403, { error: `the page may not ask ax for ${request.method} ${request.path}` })
  const base = server.replace(/\/+$/, "")
  const post = request.method === "POST"
  let response: Response
  try {
    response = await fetchFn(base + request.path, {
      method: request.method,
      headers: post
        ? { Accept: "application/json", "Content-Type": "application/json" }
        : { Accept: "application/json" },
      body: post ? JSON.stringify(request.body ?? {}) : undefined,
      // Starting a session waits for the tool to come up.
      signal: AbortSignal.timeout(90_000),
    })
  } catch {
    return reply(502, { error: offline(base) })
  }
  const text = await response.text()
  try {
    return reply(response.status, JSON.parse(text))
  } catch {
    return reply(response.status, { error: `${response.status} ${response.statusText}` })
  }
}

/**
 * Where a link clicked in the page opens: web links in the browser, the app's own pages
 * (a job's dashboard) on the ax server; nothing else. Agents also link files by their
 * absolute path, which the server doesn't serve; those are the editor's to open.
 */
export function linkTarget(href: string, server: string): string | null {
  if (href.startsWith("/jobs/")) return server.replace(/\/+$/, "") + href
  try {
    const url = new URL(href)
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null
  } catch {
    return null
  }
}

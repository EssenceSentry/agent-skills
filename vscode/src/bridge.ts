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
  "/api/models": "GET",
  "/api/usage": "GET",
  "/api/find": "GET",
  "/api/commands": "GET",
  "/api/session": "GET",
  "/api/session/search": "GET",
  "/api/session/tool": "GET",
  "/api/session/files": "GET",
  "/api/session/catalog": "GET",
  "/api/session/diff": "GET",
  "/api/session/workspace": "GET",
  "/api/chat": "POST",
}

const BASE = "http://ax.invalid"

/** A job's details, as its page reads them: one key, no deeper path. */
const JOB = /^\/jobs\/[^/]+\/api\/job$/

/** Listing sessions and models, reading usage, a session or a job's details, searching
 * with `ax find`, a session's / menu and acting on a chat; nothing else, however it's
 * spelt. Sharing is the extension's own, never the page's. */
export function allowed(method: string, path: string): boolean {
  if (!path.startsWith("/") || path.startsWith("//")) return false
  const url = new URL(path, BASE)
  if (url.origin !== BASE || path.split("?")[0] !== url.pathname) return false
  if (JOB.test(url.pathname)) return method === "GET"
  return ROUTES[url.pathname] === method
}

const DEFAULT_SERVER = "http://127.0.0.1:8765"

/** Why nothing answers: ax isn't running, or this window's settings point elsewhere, as the
 * demo's project does, where `ax app start` wouldn't help. */
const offline = (server: string) =>
  server === DEFAULT_SERVER
    ? `ax isn't answering at ${server}: start it with \`ax app start\``
    : `ax isn't answering at ${server}, where this window's ax.server setting points: start ` +
      "what serves it (the demo is `ax demo`), or remove the setting to use your ax at " +
      DEFAULT_SERVER

export type Answer = { status: number; body: unknown }

/** One request to the ax server, from the extension itself: its status and JSON. */
export async function call(
  server: string,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  fetchFn: typeof fetch = fetch
): Promise<Answer> {
  const base = server.replace(/\/+$/, "")
  const post = method === "POST"
  let response: Response
  try {
    response = await fetchFn(base + path, {
      method,
      headers: post
        ? { Accept: "application/json", "Content-Type": "application/json" }
        : { Accept: "application/json" },
      body: post ? JSON.stringify(body ?? {}) : undefined,
      // Starting a session waits for the tool to come up.
      signal: AbortSignal.timeout(90_000),
    })
  } catch {
    return { status: 502, body: { error: offline(base) } }
  }
  const text = await response.text()
  try {
    return { status: response.status, body: JSON.parse(text) }
  } catch {
    return { status: response.status, body: { error: `${response.status} ${response.statusText}` } }
  }
}

/** A page's request, if the page may make it. */
export async function forward(
  server: string,
  request: BridgeRequest,
  fetchFn: typeof fetch = fetch
): Promise<BridgeReply> {
  const answer = allowed(request.method, request.path)
    ? await call(server, request.method, request.path, request.body, fetchFn)
    : {
        status: 403,
        body: { error: `the page may not ask ax for ${request.method} ${request.path}` },
      }
  return { type: "reply", id: request.id, ...answer }
}

/** Where a web link in the page opens: the browser. Never the ax app, which VS Code
 * replaces: a job's page is its card. */
export function linkTarget(href: string): string | null {
  try {
    const url = new URL(href)
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null
  } catch {
    return null
  }
}

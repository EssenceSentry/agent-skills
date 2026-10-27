/**
 * How the page reaches ax: `fetch` on the ax server's own page, and in a VS Code tab
 * through the extension, since a webview's origin isn't the app's and the server
 * refuses actions from any other.
 */

export type Method = "GET" | "POST"
export type Reply = { status: number; body: unknown }
export type Transport = (method: Method, path: string, body?: unknown) => Promise<Reply>

const viaFetch: Transport = async (method, path, body) => {
  const response = await fetch(
    path,
    method === "POST"
      ? {
          method,
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(body),
        }
      : { headers: { Accept: "application/json" } }
  )
  const parsed = await response.json().catch(() => null)
  const reason =
    response.ok || parsed?.error ? parsed : { error: `${response.status} ${response.statusText}` }
  return { status: response.status, body: reason }
}

let current: Transport = viaFetch
let assetBase = ""

/** Send requests another way, and load pictures from `base`; null goes back to fetch. */
export function setTransport(transport: Transport | null, base = "") {
  current = transport ?? viaFetch
  assetBase = base.replace(/\/+$/, "")
}

/** One request to ax; it fails with the server's own words when it says why. */
export async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const reply = await current(method, path, body)
  if (reply.status >= 200 && reply.status < 300) return reply.body as T
  const reason = (reply.body as { error?: unknown } | null)?.error
  throw new Error(typeof reason === "string" ? reason : `${reply.status}`)
}

/**
 * Requests as messages to the VS Code extension, each answered by a reply with its id;
 * anything else that arrives is left alone.
 */
export function bridge(
  post: (message: unknown) => void,
  listen: (handler: (message: unknown) => void) => void
): Transport {
  let last = 0
  const waiting = new Map<number, (reply: Reply) => void>()
  listen((message) => {
    const reply = message as { type?: unknown; id?: unknown; status?: unknown; body?: unknown }
    if (reply?.type !== "reply" || typeof reply.id !== "number") return
    const resolve = waiting.get(reply.id)
    if (!resolve) return
    waiting.delete(reply.id)
    resolve({ status: Number(reply.status), body: reply.body })
  })
  return (method, path, body) =>
    new Promise((resolve) => {
      last += 1
      waiting.set(last, resolve)
      post(
        body === undefined
          ? { type: "request", id: last, method, path }
          : { type: "request", id: last, method, path, body }
      )
    })
}

/** A picture's address: the server's own paths point at the ax server outside its page. */
export function assetUrl(path: string): string {
  return assetBase && path.startsWith("/") && !path.startsWith("//") ? assetBase + path : path
}

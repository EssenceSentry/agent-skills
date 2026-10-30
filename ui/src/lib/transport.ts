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

export const transportIdentity = () =>
  assetBase || (typeof location === "undefined" ? "local" : location.origin)

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
      const id = last
      const timer = setTimeout(() => {
        waiting.delete(id)
        resolve({
          status: 504,
          body: {
            error:
              "The extension request timed out. Check the server and retry; a submitted message may need reconciliation.",
          },
        })
      }, 60000)
      waiting.set(id, (reply) => {
        clearTimeout(timer)
        resolve(reply)
      })
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

export type ExtensionCall = (name: string, args?: unknown) => Promise<unknown>

/**
 * Calls the VS Code extension answers itself, such as picking files or reading the
 * editor's selection; each answered by a result with its id.
 */
export function extensionCalls(
  post: (message: unknown) => void,
  listen: (handler: (message: unknown) => void) => void
): ExtensionCall {
  let last = 0
  const waiting = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>()
  listen((message) => {
    const result = message as { type?: unknown; id?: unknown; value?: unknown; error?: unknown }
    if (result?.type !== "result" || typeof result.id !== "number") return
    const call = waiting.get(result.id)
    if (!call) return
    waiting.delete(result.id)
    if (typeof result.error === "string") call.reject(new Error(result.error))
    else call.resolve(result.value)
  })
  return (name, args) =>
    new Promise((resolve, reject) => {
      last += 1
      const id = last
      const timer = setTimeout(() => {
        waiting.delete(id)
        reject(new Error("The extension did not answer. Reload the tab and retry."))
      }, 60000)
      waiting.set(id, {
        resolve: (value) => {
          clearTimeout(timer)
          resolve(value)
        },
        reject: (error) => {
          clearTimeout(timer)
          reject(error)
        },
      })
      post(
        args === undefined
          ? { type: "call", id: last, name }
          : { type: "call", id: last, name, args }
      )
    })
}

let extension: ExtensionCall | null = null

export function setExtension(call: ExtensionCall | null) {
  extension = call
}

/** Whether the page runs in an editor that answers calls. */
export const inExtension = () => extension !== null

export async function askExtension<T>(name: string, args?: unknown): Promise<T> {
  if (!extension) throw new Error("this works only inside VS Code")
  return (await extension(name, args)) as T
}

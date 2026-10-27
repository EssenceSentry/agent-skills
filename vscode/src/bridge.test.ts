import { describe, expect, it } from "vitest"

import { allowed, call, forward, linkTarget } from "./bridge"

const SERVER = "http://127.0.0.1:8765"

type Call = {
  url: string
  method: string
  body: string | undefined
  headers: Record<string, string>
}

function fakeFetch(status: number, body: string, calls: Call[] = []): typeof fetch {
  return (async (url: string | URL, init?: RequestInit) => {
    calls.push({
      url: String(url),
      method: init?.method ?? "GET",
      body: init?.body as string | undefined,
      headers: (init?.headers ?? {}) as Record<string, string>,
    })
    return new Response(body, { status, statusText: status === 200 ? "OK" : "Bad Request" })
  }) as typeof fetch
}

describe("what the page may ask the ax server", () => {
  it("lists sessions, reads one and acts on chats", () => {
    expect(allowed("GET", "/api/sessions")).toBe(true)
    expect(allowed("GET", "/api/session?provider=claude&id=x&after=3")).toBe(true)
    expect(allowed("POST", "/api/chat")).toBe(true)
  })

  it("refuses anything else, however the path is dressed", () => {
    for (const [method, path] of [
      ["POST", "/api/act"],
      ["GET", "/api/note?path=/etc/passwd"],
      ["GET", "/api/chat"],
      ["POST", "/api/sessions"],
      ["GET", "/api/session/../act"],
      ["GET", "/api/sessions/../../secret"],
      ["GET", "//evil.example/api/sessions"],
      ["GET", "http://evil.example/api/sessions"],
      ["GET", "api/sessions"],
    ] as const)
      expect(allowed(method, path), `${method} ${path}`).toBe(false)
  })
})

describe("forwarding a request", () => {
  it("sends it to the ax server and hands back its JSON", async () => {
    const calls: Call[] = []
    const reply = await forward(
      SERVER,
      {
        type: "request",
        id: 7,
        method: "POST",
        path: "/api/chat",
        body: { action: "send", text: "hi" },
      },
      fakeFetch(200, '{"ok": true}', calls)
    )
    expect(reply).toEqual({ type: "reply", id: 7, status: 200, body: { ok: true } })
    expect(calls).toEqual([
      {
        url: "http://127.0.0.1:8765/api/chat",
        method: "POST",
        body: '{"action":"send","text":"hi"}',
        headers: { Accept: "application/json", "Content-Type": "application/json" },
      },
    ])
  })

  it("passes on the server's own error", async () => {
    const reply = await forward(
      SERVER,
      { type: "request", id: 1, method: "GET", path: "/api/session?provider=claude&id=x" },
      fakeFetch(400, '{"error": "no such session"}')
    )
    expect(reply).toEqual({ type: "reply", id: 1, status: 400, body: { error: "no such session" } })
  })

  it("turns a reply that isn't JSON into an error", async () => {
    const reply = await forward(
      SERVER,
      { type: "request", id: 2, method: "GET", path: "/api/sessions" },
      fakeFetch(400, "Unknown host name.")
    )
    expect(reply).toEqual({ type: "reply", id: 2, status: 400, body: { error: "400 Bad Request" } })
  })

  it("refuses a request it doesn't allow without calling the server", async () => {
    const calls: Call[] = []
    const reply = await forward(
      SERVER,
      { type: "request", id: 3, method: "POST", path: "/api/act" },
      fakeFetch(200, "{}", calls)
    )
    expect(reply.status).toBe(403)
    expect(calls).toEqual([])
  })

  it("says how to start ax when nothing answers", async () => {
    const down = (async () => {
      throw new TypeError("fetch failed")
    }) as typeof fetch
    const reply = await forward(
      SERVER,
      { type: "request", id: 4, method: "GET", path: "/api/sessions" },
      down
    )
    expect(reply).toEqual({
      type: "reply",
      id: 4,
      status: 502,
      body: { error: "ax isn't answering at http://127.0.0.1:8765: start it with `ax app start`" },
    })
  })

  it("keeps a server address with a trailing slash working", async () => {
    const calls: Call[] = []
    await forward(
      `${SERVER}/`,
      { type: "request", id: 5, method: "GET", path: "/api/sessions" },
      fakeFetch(200, "{}", calls)
    )
    expect(calls[0]?.url).toBe("http://127.0.0.1:8765/api/sessions")
  })
})

describe("the extension's own requests", () => {
  it("reach what the page may not ask for, such as usage", async () => {
    const calls: Call[] = []
    const answer = await call(
      SERVER,
      "GET",
      "/api/usage",
      undefined,
      fakeFetch(200, '{"usage": []}', calls)
    )
    expect(answer).toEqual({ status: 200, body: { usage: [] } })
    expect(calls[0]?.url).toBe("http://127.0.0.1:8765/api/usage")
  })
})

describe("where a link in the page opens", () => {
  it("opens web links in the browser, and the app's own pages on the ax server", () => {
    expect(linkTarget("https://example.com/a?b=1", SERVER)).toBe("https://example.com/a?b=1")
    expect(linkTarget("/jobs/build-42/", SERVER)).toBe("http://127.0.0.1:8765/jobs/build-42/")
  })

  it("leaves a file path to the editor, not the ax server", () => {
    expect(linkTarget("/Users/me/Repos/demo/report.html", SERVER)).toBeNull()
    expect(linkTarget("/jobsite/x", SERVER)).toBeNull()
  })

  it("opens nothing else", () => {
    for (const href of [
      "javascript:alert(1)",
      "file:///etc/passwd",
      "#/sessions",
      "",
      "//evil.example/x",
      "vscode://x",
    ])
      expect(linkTarget(href, SERVER), href).toBeNull()
  })
})

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
  it("lists sessions and both tools' models, reads one, searches, and acts on chats", () => {
    expect(allowed("GET", "/api/sessions")).toBe(true)
    expect(allowed("GET", "/api/find?q=status%20bar%20usage")).toBe(true)
    expect(allowed("GET", "/api/commands?provider=codex&cwd=%2Frepo")).toBe(true)
    expect(allowed("GET", "/api/models")).toBe(true)
    expect(allowed("GET", "/api/usage")).toBe(true)
    expect(allowed("GET", "/jobs/demo-scoring/api/job")).toBe(true)
    expect(allowed("GET", "/jobs/score%20v5/api/job")).toBe(true)
    expect(allowed("GET", "/api/session?provider=claude&id=x&after=3")).toBe(true)
    expect(allowed("POST", "/api/chat")).toBe(true)
    for (const route of ["search", "tool", "files", "catalog", "diff", "workspace"]) {
      expect(allowed("GET", `/api/session/${route}?provider=codex&id=one`)).toBe(true)
      expect(allowed("POST", `/api/session/${route}`)).toBe(false)
    }
  })

  it("refuses anything else, however the path is dressed", () => {
    for (const [method, path] of [
      ["POST", "/api/act"],
      ["GET", "/api/note?path=/etc/passwd"],
      ["GET", "/api/chat"],
      ["POST", "/api/sessions"],
      ["POST", "/api/models"],
      ["POST", "/api/usage"],
      ["POST", "/api/find"],
      ["POST", "/api/commands"],
      ["GET", "/api/share"],
      ["POST", "/api/share"],
      ["POST", "/jobs/demo-scoring/api/job"],
      ["GET", "/jobs/demo-scoring/"],
      ["GET", "/jobs/a/b/api/job"],
      ["GET", "/jobs/../api/job"],
      ["GET", "/jobs//api/job"],
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

  it("names the setting when this window's ax lives elsewhere, as the demo's does", async () => {
    const down = (async () => {
      throw new TypeError("fetch failed")
    }) as typeof fetch
    const reply = await forward(
      "http://127.0.0.1:8798",
      { type: "request", id: 6, method: "GET", path: "/api/sessions" },
      down
    )
    expect((reply.body as { error: string }).error).toBe(
      "ax isn't answering at http://127.0.0.1:8798, where this window's ax.server setting " +
        "points: start what serves it (the demo is `ax demo`), or remove the setting to " +
        "use your ax at http://127.0.0.1:8765"
    )
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
  it("opens web links in the browser, but never the ax app: a job's page is its card", () => {
    expect(linkTarget("https://example.com/a?b=1")).toBe("https://example.com/a?b=1")
    expect(linkTarget("/jobs/build-42/")).toBeNull()
  })

  it("leaves a file path to the editor, not the ax server", () => {
    expect(linkTarget("/Users/me/Repos/demo/report.html")).toBeNull()
    expect(linkTarget("/jobsite/x")).toBeNull()
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
      expect(linkTarget(href), href).toBeNull()
  })
})

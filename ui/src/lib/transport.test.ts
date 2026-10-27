import { afterEach, describe, expect, it } from "vitest"

import {
  askExtension,
  assetUrl,
  bridge,
  extensionCalls,
  request,
  setExtension,
  setTransport,
} from "@/lib/transport"

/** A stand-in for the extension: records what the page posts and answers on demand. */
function extension() {
  const posted: Record<string, unknown>[] = []
  let deliver: (message: unknown) => void = () => undefined
  const transport = bridge(
    (message) => posted.push(message as Record<string, unknown>),
    (handler) => {
      deliver = handler
    }
  )
  return { posted, transport, answer: (message: unknown) => deliver(message) }
}

afterEach(() => {
  setTransport(null)
  setExtension(null)
})

describe("requests through the VS Code extension", () => {
  it("asks the extension and resolves with its reply", async () => {
    const ext = extension()
    setTransport(ext.transport)
    const asked = request("GET", "/api/sessions")
    expect(ext.posted).toEqual([{ type: "request", id: 1, method: "GET", path: "/api/sessions" }])
    ext.answer({ type: "reply", id: 1, status: 200, body: { sessions: [], errors: [] } })
    await expect(asked).resolves.toEqual({ sessions: [], errors: [] })
  })

  it("matches each reply to its request, whatever the order", async () => {
    const ext = extension()
    setTransport(ext.transport)
    const first = request("GET", "/api/sessions")
    const second = request("POST", "/api/chat", { action: "stop" })
    expect(ext.posted[1]).toEqual({
      type: "request",
      id: 2,
      method: "POST",
      path: "/api/chat",
      body: { action: "stop" },
    })
    ext.answer({ type: "reply", id: 2, status: 200, body: { ok: true } })
    ext.answer({ type: "reply", id: 1, status: 200, body: { sessions: [] } })
    await expect(second).resolves.toEqual({ ok: true })
    await expect(first).resolves.toEqual({ sessions: [] })
  })

  it("ignores messages that aren't replies to it", async () => {
    const ext = extension()
    setTransport(ext.transport)
    const asked = request("GET", "/api/sessions")
    ext.answer({ type: "theme" })
    ext.answer({ type: "reply", id: 99, status: 200, body: "not yours" })
    ext.answer(null)
    ext.answer({ type: "reply", id: 1, status: 200, body: "yours" })
    await expect(asked).resolves.toBe("yours")
  })

  it("fails with the server's own words", async () => {
    const ext = extension()
    setTransport(ext.transport)
    const asked = request("POST", "/api/chat", {})
    ext.answer({ type: "reply", id: 1, status: 400, body: { error: "nothing to send" } })
    await expect(asked).rejects.toThrow("nothing to send")
  })

  it("fails with the status when the server gave no reason", async () => {
    const ext = extension()
    setTransport(ext.transport)
    const asked = request("GET", "/api/sessions")
    ext.answer({ type: "reply", id: 1, status: 500, body: null })
    await expect(asked).rejects.toThrow("500")
  })
})

describe("picture addresses", () => {
  it("point at the ax server when the page isn't served by it", () => {
    setTransport(extension().transport, "http://127.0.0.1:8765")
    expect(assetUrl("/api/session/image?provider=claude&id=x&line=2&n=0")).toBe(
      "http://127.0.0.1:8765/api/session/image?provider=claude&id=x&line=2&n=0"
    )
    expect(assetUrl("data:image/png;base64,AAAA")).toBe("data:image/png;base64,AAAA")
    expect(assetUrl("//elsewhere.example/a.png")).toBe("//elsewhere.example/a.png")
  })

  it("stay as they are on the server's own page", () => {
    expect(assetUrl("/api/session/image?line=1")).toBe("/api/session/image?line=1")
  })
})

describe("asking the extension itself", () => {
  it("calls by name and resolves with the extension's result", async () => {
    const posted: Record<string, unknown>[] = []
    let deliver: (message: unknown) => void = () => undefined
    setExtension(
      extensionCalls(
        (message) => posted.push(message as Record<string, unknown>),
        (handler) => {
          deliver = handler
        }
      )
    )
    const asked = askExtension("selection")
    expect(posted).toEqual([{ type: "call", id: 1, name: "selection" }])
    deliver({ type: "reply", id: 1, status: 200, body: "not this" })
    deliver({ type: "result", id: 1, value: { path: "/a.ts" } })
    await expect(asked).resolves.toEqual({ path: "/a.ts" })
  })

  it("fails with the extension's reason", async () => {
    let deliver: (message: unknown) => void = () => undefined
    setExtension(
      extensionCalls(
        () => undefined,
        (handler) => {
          deliver = handler
        }
      )
    )
    const asked = askExtension("pickFiles")
    deliver({ type: "result", id: 1, error: "no folder is open" })
    await expect(asked).rejects.toThrow("no folder is open")
  })

  it("isn't there outside an editor", async () => {
    await expect(askExtension("selection")).rejects.toThrow("only inside VS Code")
  })
})

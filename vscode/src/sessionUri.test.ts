import { describe, expect, it } from "vitest"
import { readSessionResource, sessionResource } from "./sessionUri"

describe("session resources", () => {
  it("distinguishes servers, providers and ids even when titles match", () => {
    const a = sessionResource("http://localhost:8765/", "claude", "a/b")
    expect(readSessionResource(a)).toEqual({
      server: "http://localhost:8765",
      provider: "claude",
      id: "a/b",
    })
    expect(a).not.toBe(sessionResource("http://localhost:8765", "codex", "a/b"))
    expect(a).not.toBe(sessionResource("http://localhost:8798", "claude", "a/b"))
  })
})

it("reads VS Code's encoded query serialization and legacy resources", () => {
  expect(
    readSessionResource(
      "ax-session:/claude/example.axsession?server%3Dhttp%3A%2F%2F127.0.0.1%3A8799"
    )
  ).toEqual({ provider: "claude", id: "example", server: "http://127.0.0.1:8799" })
})

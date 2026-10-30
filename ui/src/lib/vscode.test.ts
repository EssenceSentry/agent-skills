import { describe, expect, it } from "vitest"

import { themeFor, viewFrom } from "@/lib/vscode"

describe("the page inside VS Code", () => {
  it("follows VS Code's light, dark and high-contrast themes", () => {
    expect(themeFor("vscode-light")).toBe("light")
    expect(themeFor("vscode-dark")).toBe("dark")
    expect(themeFor("vscode-high-contrast")).toBe("dark")
    expect(themeFor("vscode-high-contrast-light")).toBe("light")
    expect(themeFor("vscode-reduce-motion vscode-dark")).toBe("dark")
    expect(themeFor("")).toBe("light")
  })

  it("reads which screen to show from the page the extension wrote", () => {
    expect(
      viewFrom({ screen: "session", provider: "codex", id: "t-1", server: "http://127.0.0.1:8765" })
    ).toEqual({ screen: "session", provider: "codex", id: "t-1", server: "http://127.0.0.1:8765" })
    expect(
      viewFrom({ screen: "new", folders: '["/a","/b"]', server: "http://127.0.0.1:8765" })
    ).toEqual({ screen: "new", folders: ["/a", "/b"], server: "http://127.0.0.1:8765" })
    expect(viewFrom({ screen: "panel", folders: '["/a"]', server: "s" })).toEqual({
      screen: "panel",
      folders: ["/a"],
      server: "s",
    })
    expect(viewFrom({ screen: "search", server: "s" })).toEqual({ screen: "search", server: "s" })
  })

  it("shows nothing for a page it can't read", () => {
    expect(viewFrom({ screen: "session", provider: "codex" })).toBeNull()
    expect(viewFrom({ screen: "session", provider: "gemini", id: "x", server: "s" })).toBeNull()
    expect(viewFrom({ screen: "new", folders: "not json", server: "s" })).toEqual({
      screen: "new",
      folders: [],
      server: "s",
    })
    expect(viewFrom({ screen: "nope", server: "s" })).toBeNull()
  })
})

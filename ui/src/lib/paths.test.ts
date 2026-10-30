import { describe, expect, it } from "vitest"

import { looksLikePath, shortPath } from "@/lib/paths"

describe("code that names a file", () => {
  it("counts paths, file names and file:line", () => {
    for (const text of [
      "src/lib/ax.ts",
      "src/lib/ax.ts:42",
      "ax.ts:42:7",
      "/Users/me/Repos/demo/report.html",
      "~/notes/today.md",
      "./README.md",
      "../other/a.md",
      "README.md",
      "models/news/",
      "vscode/media/webview/webview.js",
    ])
      expect(looksLikePath(text), text).toBe(true)
  })

  it("leaves commands, addresses, versions and names alone", () => {
    for (const text of [
      "npm run build",
      "https://example.com/a.js",
      "@/lib/time",
      "--active",
      "ax:hurry",
      "localhost:8765",
      "127.0.0.1:8765",
      "v1.3",
      "1.5",
      "e.g.",
      "*.vsix",
      "user.email=t",
      "foo()",
      "1/2",
      "a\nb.ts",
      "",
    ])
      expect(looksLikePath(text), text).toBe(false)
  })
})

describe("a path as people read it", () => {
  it("starts from ~ inside the home folder", () => {
    expect(shortPath("/Users/me/Documents/Codex/2026-10-27/l")).toBe(
      "~/Documents/Codex/2026-10-27/l"
    )
    expect(shortPath("/home/me/repo")).toBe("~/repo")
    expect(shortPath("/Users/me")).toBe("~")
  })

  it("leaves a path outside it as it is", () => {
    expect(shortPath("/tmp/scratch")).toBe("/tmp/scratch")
    expect(shortPath("/Users")).toBe("/Users")
  })
})

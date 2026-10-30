import { describe, expect, it } from "vitest"

import { globMatches, openWith, saveStart, unplaced } from "./opening"

const editors = ["*.pdf", "*.{jpg,jpe,jpeg,png,bmp,gif,ico,webp,avif}", "*.{mp4,webm}"]

describe("where a file opens", () => {
  it("opens text in the editor", () => {
    expect(openWith("/repo/a.py", { editors, text: true })).toBe("editor")
    expect(openWith("/repo/notes", { editors: [], text: true })).toBe("editor")
  })

  it("opens what an installed editor takes in VS Code, PDFs and pictures included", () => {
    expect(openWith("/repo/report.pdf", { editors, text: false })).toBe("editor")
    expect(openWith("/repo/Shot.PNG", { editors, text: false })).toBe("editor")
    expect(openWith("/repo/demo.mp4", { editors, text: false })).toBe("editor")
  })

  it("opens anything else in its own app", () => {
    expect(openWith("/repo/data.xlsx", { editors, text: false })).toBe("app")
    expect(openWith("/repo/report.pdf", { editors: [], text: false })).toBe("app")
  })
})

describe("an editor's file pattern", () => {
  it("matches names by extension, braces and folders", () => {
    expect(globMatches("*.{png,jpg}", "a.jpg")).toBe(true)
    expect(globMatches("**/*.ipynb", "x.ipynb")).toBe(true)
    expect(globMatches("*.pdf", "a.pdf.txt")).toBe(false)
    expect(globMatches("Dockerfile", "Dockerfile")).toBe(true)
    expect(globMatches("*.pdf", "A.PDF")).toBe(true)
  })
})

describe("a reference that can't be placed", () => {
  it("says why when the session's folder isn't known", () => {
    expect(unplaced("models/a.py:3", null)).toBe(
      "This session's folder isn't known, so models/a.py can't be found."
    )
  })

  it("is nothing for what can be placed or isn't a path", () => {
    expect(unplaced("/abs/a.py", null)).toBeNull()
    expect(unplaced("models/a.py", "/repo")).toBeNull()
    expect(unplaced("https://example.com", null)).toBeNull()
    expect(unplaced("#/sessions", null)).toBeNull()
  })
})

describe("where a web page opens", () => {
  it("opens in the browser, drawn, not as its code", () => {
    expect(openWith("/repo/dist/index.html", { editors, text: true })).toBe("browser")
    expect(openWith("/repo/Report.HTM", { editors, text: true })).toBe("browser")
  })

  it("opens at a line in the editor when the link names one: that is about its code", () => {
    expect(openWith("/repo/index.html", { editors, text: true, line: 42 })).toBe("editor")
  })
})

describe("where saving a page's Markdown starts", () => {
  it("is the session's folder, under the page's name for the file", () => {
    expect(saveStart("/repo", "plan-themed-charts.md", "/home/me")).toBe(
      "/repo/plan-themed-charts.md"
    )
  })

  it("is home without a folder, and only ever a file name, never a path", () => {
    expect(saveStart(null, "plan.md", "/home/me")).toBe("/home/me/plan.md")
    expect(saveStart("/repo", "../../etc/plan.md", "/home/me")).toBe("/repo/plan.md")
    expect(saveStart("/repo", 3, "/home/me")).toBe("/repo/plan.md")
  })
})

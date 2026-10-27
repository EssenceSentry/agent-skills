import { describe, expect, it } from "vitest"

import { fileReference, selectionReference } from "./selection"

describe("the selection a message can carry", () => {
  it("names the file, its lines from one, and the code", () => {
    expect(
      selectionReference({
        path: "/repo/b.py",
        startLine: 11,
        endLine: 13,
        endCharacter: 12,
        text: "def f():\n    return 1",
        languageId: "python",
      })
    ).toEqual({
      kind: "selection",
      path: "/repo/b.py",
      start: 12,
      end: 14,
      text: "def f():\n    return 1",
      language: "python",
    })
  })

  it("leaves out a last line the selection only touches", () => {
    const whole = selectionReference({
      path: "/repo/b.py",
      startLine: 11,
      endLine: 14,
      endCharacter: 0,
      text: "a\nb\nc\n",
      languageId: "python",
    })
    expect(whole).toMatchObject({ start: 12, end: 14 })
  })

  it("is nothing when nothing is selected", () => {
    expect(
      selectionReference({
        path: "/repo/b.py",
        startLine: 3,
        endLine: 3,
        endCharacter: 5,
        text: "",
        languageId: "python",
      })
    ).toBeNull()
  })
})

describe("a file or folder a message can carry", () => {
  it("says which it is", () => {
    expect(fileReference("/repo/src", true)).toEqual({ kind: "folder", path: "/repo/src" })
    expect(fileReference("/repo/a.ts", false)).toEqual({ kind: "file", path: "/repo/a.ts" })
  })
})

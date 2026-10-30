import { afterEach, describe, expect, it } from "vitest"

import { copyText } from "@/lib/copy"
import { setExtension } from "@/lib/transport"

afterEach(() => setExtension(null))

describe("copying an answer", () => {
  it("goes through VS Code's clipboard in the editor", async () => {
    const calls: unknown[] = []
    setExtension(async (name, args) => {
      calls.push([name, args])
    })
    await copyText("**Done.** See `app.py`.", true)
    expect(calls).toEqual([["copy", { text: "**Done.** See `app.py`." }]])
  })
})

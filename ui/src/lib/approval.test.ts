import { describe, expect, it } from "vitest"

import { describeApproval } from "@/lib/approval"
import type { Approval } from "@/lib/sessions"

const asked = (fields: Partial<Approval>): Approval => ({
  id: "a1",
  tool: "Bash",
  summary: "",
  reason: null,
  detail: null,
  ...fields,
})

describe("what an approval asks, as Codex words it", () => {
  it("shows a command to run under the terminal's name", () => {
    const bash = asked({
      summary: "run `rm -rf build && npm run build`",
      detail: JSON.stringify({ command: "rm -rf build && npm run build", description: "Rebuild" }),
    })
    expect(describeApproval(bash, "claude")).toEqual({
      label: "Terminal",
      title: "Do you want Claude to run this command?",
      command: "rm -rf build && npm run build",
      files: [],
      detail: null,
    })
    const codex = asked({ tool: "commandExecution", summary: "run `ls -la src`" })
    expect(describeApproval(codex, "codex")).toMatchObject({
      label: "Terminal",
      title: "Do you want Codex to run this command?",
      command: "ls -la src",
    })
  })

  it("names the files an edit would change", () => {
    const edit = asked({ tool: "Edit", detail: JSON.stringify({ file_path: "/repo/src/a.ts" }) })
    expect(describeApproval(edit, "claude")).toEqual({
      label: "Edit files",
      title: "Do you want Claude to edit this file?",
      command: null,
      files: ["/repo/src/a.ts"],
      detail: `Proposed patch unavailable from this provider.\n${edit.detail}`,
    })
    const codex = asked({ tool: "fileChange", summary: "change files under /repo/src" })
    expect(describeApproval(codex, "codex")).toMatchObject({
      label: "Edit files",
      title: "Do you want Codex to edit files under /repo/src?",
      files: [],
    })
  })

  it("asks about any other tool by its name, with what it would be given", () => {
    const fetch = asked({
      tool: "WebFetch",
      summary: "fetch example.com",
      detail: JSON.stringify({ url: "https://example.com" }, null, 2),
    })
    expect(describeApproval(fetch, "claude")).toEqual({
      label: "WebFetch",
      title: "Do you want Claude to fetch example.com?",
      command: null,
      files: [],
      detail: JSON.stringify({ url: "https://example.com" }, null, 2),
    })
    const more = asked({ tool: "permissions", summary: "use more permissions" })
    expect(describeApproval(more, "codex").title).toBe("Do you want Codex to use more permissions?")
  })
})

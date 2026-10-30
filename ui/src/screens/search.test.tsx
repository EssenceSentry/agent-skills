import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { EditorHost } from "@/lib/host"
import { readHref } from "@/lib/routes"
import type { Hit } from "@/lib/search"
import { Results } from "@/screens/search"

const conversation: Hit = {
  source: "conversation",
  path: "/vault/Sessions/2026-10-24 claude ds-models - ax (48402546).md",
  title: "Usage in the status bar",
  snippet: "the weekly windows by each tool's mark",
  handle: "ax:48402546",
  session: "2e065b04-622e-46a0-9d88-95f848402546",
  provider: "claude",
  project: "ds-models",
  date: "2026-10-24",
  note: "Sessions/2026-10-24 claude ds-models - ax (48402546).md",
}
const memory: Hit = {
  source: "memory",
  path: "/Users/me/.claude/projects/-Users-me-Repos-ds-models/memory/usage.md",
  title: "usage",
  snippet: "The status bar shows each tool's weekly window",
  project: "ds-models",
}
const none = () => undefined

describe("search results", () => {
  it("open a conversation's note in the reader on the web", () => {
    const out = renderToStaticMarkup(<Results hits={[conversation, memory]} />)
    expect(out).toContain(`href="${readHref(conversation.note as string)}"`)
  })

  it("in VS Code, open a conversation as its session's tab and a memory as its file", () => {
    const out = renderToStaticMarkup(
      <EditorHost.Provider value={true}>
        <Results hits={[conversation, memory]} onOpen={none} />
      </EditorHost.Provider>
    )
    expect(out).toContain('aria-label="Open the session Usage in the status bar"')
    expect(out).toContain(`href="${memory.path}"`)
    expect(out).not.toContain("#/read/")
  })
})

import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Markdown } from "@/blocks/markdown"
import { EditorHost } from "@/lib/host"

const html = (text: string) => renderToStaticMarkup(<Markdown>{text}</Markdown>)
const inEditor = (text: string) =>
  renderToStaticMarkup(
    <EditorHost.Provider value={true}>
      <Markdown>{text}</Markdown>
    </EditorHost.Provider>
  )

describe("Markdown", () => {
  it("turns a callout into an aside with its title", () => {
    const out = html("> [!warning] Mind the gap\n> Body text.")
    expect(out).toContain('<aside class="callout" data-callout="warning">')
    expect(out).toContain('<div class="callout-title">Mind the gap</div>')
    expect(out).toContain("<p>Body text.</p>")
    expect(out).not.toContain("[!warning]")
  })

  it("names an untitled callout after its type and leaves plain quotes alone", () => {
    expect(html("> [!note]\n> Body.")).toContain('<div class="callout-title">Note</div>')
    expect(html("> [!tip]- Folded\n> Body.")).toContain('<div class="callout-title">Folded</div>')
    const quote = html("> Just a quote.")
    expect(quote).toContain("<blockquote>")
    expect(quote).not.toContain("aside")
  })

  it("keeps a title's formatting and the body after it", () => {
    const out = html("> [!note] A **bold** title\n> Then the body.")
    expect(out).toContain('<div class="callout-title">A <strong>bold</strong> title</div>')
    expect(out).toContain("<p>Then the body.</p>")
  })

  it("shows a link to a missing note as text, and opens other sites in a new tab", () => {
    expect(html("[Gone](#/missing/Gone)")).toContain(
      '<span class="missing-link" title="No note named Gone">Gone</span>'
    )
    const out = html("[docs](https://example.com) and [a note](#/read/A.md)")
    expect(out).toContain('href="https://example.com" target="_blank" rel="noreferrer"')
    expect(out).toContain('<a href="#/read/A.md">a note</a>')
  })

  it("never renders raw HTML from a note", () => {
    const out = html('<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">')
    expect(out).not.toContain("<script")
    expect(out).not.toContain("<img")
  })

  it("renders tables and task lists", () => {
    expect(html("| a | b |\n|---|---|\n| 1 | 2 |")).toContain("<table>")
    expect(html("- [x] done")).toContain('type="checkbox"')
  })

  it("links the files code names inside the editor, and only there", () => {
    expect(inEditor("See `src/lib/ax.ts:42`.")).toContain(
      '<a href="src/lib/ax.ts:42" data-file=""><code>src/lib/ax.ts:42</code></a>'
    )
    expect(inEditor("Run `npm run build`.")).toContain("<code>npm run build</code>")
    expect(inEditor("Run `npm run build`.")).not.toContain("<a")
    expect(html("See `src/lib/ax.ts:42`.")).toContain("<code>src/lib/ax.ts:42</code>")
    expect(html("See `src/lib/ax.ts:42`.")).not.toContain("<a")
  })
})

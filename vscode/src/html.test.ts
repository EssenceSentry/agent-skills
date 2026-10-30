import { describe, expect, it } from "vitest"

import { pageHtml } from "./html"

const base = {
  cspSource: "https://file+.vscode-resource.vscode-cdn.net",
  nonce: "n0nce123",
  script: "https://file+.vscode-resource.vscode-cdn.net/ext/media/webview/webview.js",
  style: "https://file+.vscode-resource.vscode-cdn.net/ext/media/webview/webview.css",
  server: "http://127.0.0.1:8765",
  icons: "https://file+.vscode-resource.vscode-cdn.net/ext/media/ax-icons.woff",
}

function policy(html: string): Record<string, string> {
  const content = html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/)?.[1] ?? ""
  return Object.fromEntries(
    content
      .split(";")
      .map((d) => d.trim())
      .filter(Boolean)
      .map((d) => [d.split(" ")[0], d.split(" ").slice(1).join(" ")])
  )
}

describe("the page in a session tab", () => {
  const html = pageHtml({ ...base, view: { screen: "session", provider: "codex", id: "t-1" } })

  it("runs only the bundled script, by its nonce, and the code it loads from the extension", () => {
    expect(policy(html)["default-src"]).toBe("'none'")
    // Mermaid is large, so it loads from the extension's own files only when a diagram shows.
    expect(policy(html)["script-src"]).toBe(`'nonce-n0nce123' ${base.cspSource}`)
    expect(html).toContain(`<script nonce="n0nce123" type="module" src="${base.script}"></script>`)
    expect(html.match(/<script/g)).toHaveLength(1)
  })

  it("loads pictures from the ax server and pasted ones, styles and fonts from the extension", () => {
    expect(policy(html)["img-src"]).toBe(`${base.cspSource} ${base.server} data: blob:`)
    expect(policy(html)["style-src"]).toBe(`${base.cspSource} 'unsafe-inline'`)
    expect(policy(html)["font-src"]).toBe(base.cspSource)
    expect(policy(html)["connect-src"]).toBeUndefined()
    expect(html).toContain(`<link rel="stylesheet" href="${base.style}">`)
  })

  it("gives the page the status bar's marks, from the extension's icon font", () => {
    expect(html).toContain(
      `<style>@font-face{font-family:"ax icons";src:url("${base.icons}") format("woff")}</style>`
    )
  })

  it("tells the page which session to show, that it is live, and where ax is", () => {
    expect(html).toContain('<meta name="ax-live" content="vscode">')
    expect(html).toContain('data-screen="session"')
    expect(html).toContain('data-provider="codex"')
    expect(html).toContain('data-id="t-1"')
    expect(html).toContain('data-server="http://127.0.0.1:8765"')
  })

  it("says it is reading the session until the page has loaded, never a blank tab", () => {
    expect(html).toMatch(
      /<div id="root"[^>]*><p [^>]*role="status"[^>]*>Reading the session…<\/p><\/div>/
    )
  })

  it("lets text selected in the page be copied: the page takes the focus, not its body", () => {
    // VS Code copies in a webview by focusing again the element that last had the focus,
    // the message box, whenever the focus is on the body; the selection goes with it.
    expect(html).toContain('<div id="root" tabindex="-1">')
  })
})

describe("the page for a new session", () => {
  it("offers the workspace's folders, escaped", () => {
    const html = pageHtml({
      ...base,
      view: { screen: "new", folders: ['/Users/me/Repos/"odd" <name>', "/Users/me/Repos/b"] },
    })
    expect(html).toContain('data-screen="new"')
    expect(html).toContain(
      'data-folders="[&quot;/Users/me/Repos/\\&quot;odd\\&quot; &lt;name&gt;&quot;,&quot;/Users/me/Repos/b&quot;]"'
    )
    expect(html).not.toContain("<name>")
  })

  it("tells a search tab it is one", () => {
    const html = pageHtml({ ...base, view: { screen: "search" } })
    expect(html).toContain('data-screen="search"')
    expect(html).not.toContain("data-folders")
  })

  it("tells the panel on the right it is the panel, with the workspace's folders", () => {
    const html = pageHtml({ ...base, view: { screen: "panel", folders: ["/Users/me/Repos/b"] } })
    expect(html).toContain('data-screen="panel"')
    expect(html).toContain('data-folders="[&quot;/Users/me/Repos/b&quot;]"')
  })
})

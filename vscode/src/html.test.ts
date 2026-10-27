import { describe, expect, it } from "vitest"

import { pageHtml } from "./html"

const base = {
  cspSource: "https://file+.vscode-resource.vscode-cdn.net",
  nonce: "n0nce123",
  script: "https://file+.vscode-resource.vscode-cdn.net/ext/media/webview/webview.js",
  style: "https://file+.vscode-resource.vscode-cdn.net/ext/media/webview/webview.css",
  server: "http://127.0.0.1:8765",
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

  it("runs only the bundled script, by its nonce", () => {
    expect(policy(html)["default-src"]).toBe("'none'")
    expect(policy(html)["script-src"]).toBe("'nonce-n0nce123'")
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

  it("tells the page which session to show, that it is live, and where ax is", () => {
    expect(html).toContain('<meta name="ax-live" content="vscode">')
    expect(html).toContain('data-screen="session"')
    expect(html).toContain('data-provider="codex"')
    expect(html).toContain('data-id="t-1"')
    expect(html).toContain('data-server="http://127.0.0.1:8765"')
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
})

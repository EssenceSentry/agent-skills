/** The HTML of a session tab: the app's conversation page, bundled, with a strict policy. */

import type { Provider } from "./tree"

export type View =
  | { screen: "session"; provider: Provider; id: string }
  | { screen: "new"; folders: string[] }

export type Page = {
  /** The webview's own origin for the extension's files (`webview.cspSource`). */
  cspSource: string
  nonce: string
  script: string
  style: string
  /** The ax server, which the page's pictures load from. */
  server: string
  view: View
}

const attribute = (text: string) =>
  text
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")

/**
 * Only the bundled script runs; the page reaches ax through the extension, never itself,
 * so it may connect nowhere. Pictures come from the ax server, or are pasted (data:).
 */
export function pageHtml({ cspSource, nonce, script, style, server, view }: Page): string {
  const policy = [
    "default-src 'none'",
    `img-src ${cspSource} ${server} data: blob:`,
    `style-src ${cspSource} 'unsafe-inline'`,
    `font-src ${cspSource}`,
    `script-src 'nonce-${nonce}'`,
  ].join("; ")
  const data: Record<string, string> =
    view.screen === "session"
      ? { screen: "session", provider: view.provider, id: view.id }
      : { screen: "new", folders: JSON.stringify(view.folders) }
  const attributes = Object.entries({ ...data, server })
    .map(([key, value]) => `data-${key}="${attribute(value)}"`)
    .join(" ")
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${policy}">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="ax-live" content="vscode">
    <link rel="stylesheet" href="${style}">
  </head>
  <body ${attributes}>
    <div id="root"></div>
    <script nonce="${nonce}" type="module" src="${script}"></script>
  </body>
</html>
`
}

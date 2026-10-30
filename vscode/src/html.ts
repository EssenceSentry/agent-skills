/** The HTML of a session tab: the app's conversation page, bundled, with a strict policy. */

import type { Provider } from "./listing"

export type View =
  | { screen: "session"; provider: Provider; id: string }
  | { screen: "new"; folders: string[] }
  | { screen: "panel"; folders: string[] }
  | { screen: "search" }

export type Page = {
  /** The webview's own origin for the extension's files (`webview.cspSource`). */
  cspSource: string
  nonce: string
  script: string
  style: string
  /** The extension's icon font, the status bar's marks: ax's and each tool's. */
  icons: string
  /** The ax server, which the page's pictures load from. */
  server: string
  view: View
}

/** What a tab says while its page loads, which can take a few seconds. */
const LOADING: Record<View["screen"], string> = {
  session: "Reading the session…",
  new: "Opening…",
  panel: "Reading your sessions…",
  search: "Opening search…",
}

const attribute = (text: string) =>
  text
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")

/**
 * Only the bundled script runs, with the code it loads from the extension's own files; the
 * page reaches ax through the extension, never itself, so it may connect nowhere. Pictures come from the ax server, or are pasted (data:).
 */
export function pageHtml({ cspSource, nonce, script, style, icons, server, view }: Page): string {
  const policy = [
    "default-src 'none'",
    `img-src ${cspSource} ${server} data: blob:`,
    `style-src ${cspSource} 'unsafe-inline'`,
    `font-src ${cspSource}`,
    // The bundled script, and the code it loads from the extension when needed (Mermaid).
    `script-src 'nonce-${nonce}' ${cspSource}`,
  ].join("; ")
  const data: Record<string, string> =
    view.screen === "session"
      ? { screen: "session", provider: view.provider, id: view.id }
      : view.screen === "search"
        ? { screen: "search" }
        : { screen: view.screen, folders: JSON.stringify(view.folders) }
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
    <style>@font-face{font-family:"ax icons";src:url("${icons.replaceAll('"', "%22")}") format("woff")}</style>
  </head>
  <body ${attributes}>
    <div id="root" tabindex="-1"><p role="status" style="margin:0;padding:14px;font:var(--vscode-font-size,13px) var(--vscode-font-family,sans-serif);color:var(--vscode-descriptionForeground)">${LOADING[view.screen]}</p></div>
    <script nonce="${nonce}" type="module" src="${script}"></script>
  </body>
</html>
`
}

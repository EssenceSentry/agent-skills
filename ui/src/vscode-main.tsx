import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "@atelier/theme/direction.css"
import "./index.css"
import "./vscode.css"
import { NewSession } from "@/blocks/new-session"
import { EditorHost } from "@/lib/host"
import { bridge, setTransport } from "@/lib/transport"
import { themeFor, viewFrom } from "@/lib/vscode"
import { SessionScreen } from "@/screens/session"

declare function acquireVsCodeApi(): {
  postMessage(message: unknown): void
  setState(state: unknown): void
}

// The page of a VS Code tab: one session, or the form for a new one. The extension
// wrote which on the body, and answers the page's requests to ax.
const vscode = acquireVsCodeApi()
const view = viewFrom({ ...document.body.dataset })

setTransport(
  bridge(
    (message) => vscode.postMessage(message),
    (handler) => window.addEventListener("message", (e) => handler(e.data))
  ),
  view?.server
)

// VS Code marks its theme on the body and changes it when the user switches themes.
const follow = () => {
  document.documentElement.dataset.theme = themeFor(document.body.className)
}
follow()
new MutationObserver(follow).observe(document.body, {
  attributes: true,
  attributeFilter: ["class"],
})

// A tab can't navigate: links open through the extension, files in the editor and the
// rest in the browser; a relative path starts from the session's folder.
document.addEventListener(
  "click",
  (e) => {
    const link = (e.target as Element | null)?.closest?.("a[href]")
    if (!link) return
    e.preventDefault()
    const cwd = link.closest("[data-cwd]")?.getAttribute("data-cwd") ?? null
    vscode.postMessage({ type: "open", href: link.getAttribute("href"), cwd })
  },
  true
)

// Kept by VS Code, so the tab comes back on this session after a restart.
if (view?.screen === "session") vscode.setState({ provider: view.provider, id: view.id })

function Tab() {
  if (view?.screen === "session")
    return <SessionScreen provider={view.provider} id={view.id} back={false} />
  if (view?.screen === "new")
    return (
      <main className="mx-auto max-w-[860px] p-4 md:p-6">
        <NewSession
          folders={view.folders}
          onClose={() => vscode.postMessage({ type: "close" })}
          onStarted={(provider, id, name) =>
            vscode.postMessage({ type: "started", provider, id, name })
          }
        />
      </main>
    )
  return (
    <main className="p-6 text-sm text-muted-foreground">
      This tab doesn't say which session to show. Open one from the ax sidebar.
    </main>
  )
}

const root = document.getElementById("root")
if (!root) throw new Error("the tab's page needs an element with id root")

createRoot(root).render(
  <StrictMode>
    <EditorHost.Provider value={true}>
      <Tab />
    </EditorHost.Provider>
  </StrictMode>
)

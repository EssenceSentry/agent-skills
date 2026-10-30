import { StrictMode, useState } from "react"
import { createRoot } from "react-dom/client"

import "@atelier/theme/direction.css"
import "./index.css"
import "./look.css"
import "./vscode.css"
import { showJob } from "@/blocks/job-card"
import { NewSession } from "@/blocks/new-session"
import { EditorHost, EditorLook } from "@/lib/host"
import { jobKey } from "@/lib/job"
import { bridge, extensionCalls, setExtension, setTransport } from "@/lib/transport"
import { themeFor, viewFrom } from "@/lib/vscode"
import { SessionsPanel } from "@/screens/panel"
import { SearchScreen } from "@/screens/search"
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

// The conversation's look, in look.css, applies under the first mark; what only VS Code
// needs, in vscode.css, under the second.
document.documentElement.dataset.look = "editor"
document.documentElement.dataset.host = "vscode"

// Files, folders and the editor's selection come from the extension itself.
setExtension(
  extensionCalls(
    (message) => vscode.postMessage(message),
    (handler) => window.addEventListener("message", (e) => handler(e.data))
  )
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

// A tab can't navigate: a link to a job's page opens the job's card, and the rest open
// through the extension, files in the editor and web pages in the browser; a relative
// path starts from the session's folder. The click goes no further: VS Code's frame
// around the page opens any link it sees clicked too, resolved against the tab's own
// address.
document.addEventListener(
  "click",
  (e) => {
    const link = (e.target as Element | null)?.closest?.("a[href]")
    if (!link) return
    e.preventDefault()
    e.stopPropagation()
    const href = link.getAttribute("href") ?? ""
    const job = jobKey(href)
    if (job && showJob(job)) return
    const cwd = link.closest("[data-cwd]")?.getAttribute("data-cwd") ?? null
    vscode.postMessage({ type: "open", href, cwd })
  },
  true
)

window.addEventListener("message", (event) => {
  if (event.data?.type === "preferences") window.dispatchEvent(new Event("ax:preferences"))
  if (event.data?.type === "visibility") {
    document.body.dataset.hostVisible = String(event.data.visible)
    window.dispatchEvent(new CustomEvent("ax:visibility", { detail: event.data.visible }))
  }
})

vscode.postMessage({ type: "ready" })

// Kept by VS Code, so the tab comes back on this session after a restart.
if (view?.screen === "session") vscode.setState({ provider: view.provider, id: view.id })

/** The search tab: the web app's search screen, its query its own, each hit opening in
 * the editor. */
function SearchTab() {
  const [query, setQuery] = useState("")
  return (
    <SearchScreen
      query={query}
      onSearch={setQuery}
      onOpen={(provider, id, name) =>
        vscode.postMessage({ type: "openSession", provider, id, name })
      }
    />
  )
}

function Tab() {
  if (view?.screen === "panel")
    return (
      <main>
        <SessionsPanel
          folders={view.folders}
          onOpen={(provider, id, name, beside) =>
            vscode.postMessage({ type: "openSession", provider, id, name, beside })
          }
          onStarted={(provider, id, name) =>
            vscode.postMessage({ type: "started", provider, id, name })
          }
          onChanges={(provider, id, name) =>
            vscode.postMessage({ type: "changes", provider, id, name, base: "turn" })
          }
        />
      </main>
    )
  if (view?.screen === "search") return <SearchTab />
  if (view?.screen === "session")
    return (
      <SessionScreen
        provider={view.provider}
        id={view.id}
        back={false}
        onState={(state, name) =>
          vscode.postMessage({ type: "state", provider: view.provider, id: view.id, state, name })
        }
      />
    )
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
    <EditorLook.Provider value={true}>
      <EditorHost.Provider value={true}>
        <Tab />
      </EditorHost.Provider>
    </EditorLook.Provider>
  </StrictMode>
)

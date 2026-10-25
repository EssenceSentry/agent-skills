import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "@atelier/theme/direction.css"
import "./index.css"
import App from "./App.tsx"
import { LIVE } from "./lib/ax"

// A shared link carries the run's access token; the server keeps it in a cookie, so take
// it out of the address bar, history and any copied link.
if (new URLSearchParams(window.location.search).has("token")) {
  window.history.replaceState(null, "", window.location.pathname + window.location.hash)
}

// Installed, the app can then open from its last page while its server restarts.
if (LIVE && "serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => undefined)
}

const root = document.getElementById("root")
if (!root) throw new Error("index.html needs an element with id root")

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>
)

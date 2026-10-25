// The ax app's service worker. Installed, the app opens from the last page it loaded
// while `ax serve` restarts; its data always comes live from the server, never a cache.
const CACHE = "ax-shell"

// The first visit happens before this worker is in control, so it keeps the page and
// its assets as soon as it installs; later visits refresh them.
async function keepShell() {
  const cache = await caches.open(CACHE)
  const response = await fetch("/", { cache: "no-store" })
  if (!response.ok) return
  const page = await response.clone().text()
  await cache.put("/", response)
  await cache.addAll([...new Set(page.match(/\/assets\/[^"']+/g) || [])])
}

self.addEventListener("install", (event) =>
  event.waitUntil(
    keepShell()
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  )
)
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()))

self.addEventListener("fetch", (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== "GET" || url.origin !== self.location.origin) return
  if (url.pathname.startsWith("/api/") || url.pathname === "/events") return

  if (url.pathname.startsWith("/assets/")) {
    // Named by their content, so a cached copy is never stale.
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const hit = await cache.match(request)
        if (hit) return hit
        const response = await fetch(request)
        if (response.ok) cache.put(request, response.clone())
        return response
      })
    )
    return
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone()
            caches.open(CACHE).then((cache) => cache.put("/", copy))
          }
          return response
        })
        .catch(() => caches.match("/"))
    )
  }
})

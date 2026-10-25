// Serve the build and look at it in light and dark, on desktop and phone.
// Fails on a chart that did not render, a console error, or a page that
// scrolls sideways on a phone. Screenshots land in checks/ for a person or an
// agent to look at. Run `npm run build` first.
import { mkdir } from "node:fs/promises"
import { chromium } from "playwright"
import { preview } from "vite"

const out = "checks"
const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
]

await mkdir(out, { recursive: true })
const server = await preview({ preview: { port: 4317, strictPort: false }, logLevel: "warn" })
const url = server.resolvedUrls?.local[0]
if (!url) throw new Error("vite preview did not report a local address")

const browser = await chromium.launch()
const problems = []
// The Now screen, a note in the reader, Help and a search, from the example data.
const routes = [
  { name: "now", hash: "" },
  {
    name: "reader",
    hash: "#/read/Sessions/2026/10/2026-10-25%20Build%20the%20ax%20app%2048402546.md",
  },
  { name: "help", hash: "#/help" },
  { name: "search", hash: "#/search?q=reserve%20then%20settle" },
]
for (const colorScheme of ["light", "dark"]) {
  for (const viewport of viewports)
    for (const route of routes) {
      const label = `${colorScheme}/${viewport.name}/${route.name}`
      const page = await browser.newPage({
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme,
        deviceScaleFactor: 2,
      })
      page.on(
        "console",
        (m) => m.type() === "error" && problems.push(`${label} console: ${m.text()}`)
      )
      page.on("pageerror", (e) => problems.push(`${label} page error: ${e.message}`))
      await page.goto(url + route.hash, { waitUntil: "networkidle" })
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(250)
      const charts = await page.$$eval("figure.plot-figure", (els) =>
        // Charts in panels hidden at this width never get a size; skip them.
        els.filter((e) => e.getClientRects().length > 0).map((e) => e.dataset.state)
      )
      for (const state of charts) if (state !== "ok") problems.push(`${label}: chart ${state}`)
      const { scroll, client } = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }))
      if (scroll > client) problems.push(`${label}: page scrolls sideways (${scroll} > ${client})`)
      await page.screenshot({
        path: `${out}/${colorScheme}-${viewport.name}-${route.name}.png`,
        fullPage: true,
      })
      await page.close()
    }
}
await browser.close()
await server.close()

console.log(problems.length ? problems.join("\n") : `checks clean; screenshots in ${out}/`)
process.exit(problems.length ? 1 : 0)

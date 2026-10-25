// Render the app's installable icons from its mark: the plain mark at 192 and 512 px, a
// full-bleed version for maskable and Apple touch icons, which crop to their own shapes.
// Run after changing the mark; the PNGs are committed.
import { chromium } from "playwright"

const ACCENT = "#3665e4" // check-colours: off (a file outside the page, like favicon.svg)
const MARK = `<path d="M9 9 L23 23 M23 9 L9 23" stroke="#fff" stroke-width="3.4" stroke-linecap="round"/>
  <circle cx="23" cy="9" r="3.6" fill="${ACCENT}"/><circle cx="23" cy="9" r="2.4" fill="#fff"/>`
const rounded = `<rect width="32" height="32" rx="8" fill="${ACCENT}"/>${MARK}`
// The maskable safe zone is the inner 80%; the mark sits well inside it.
const bleed = `<rect width="32" height="32" fill="${ACCENT}"/>
  <g transform="translate(16 16) scale(0.72) translate(-16 -16)">${MARK}</g>`

const icons = [
  ["icon-192.png", 192, rounded],
  ["icon-512.png", 512, rounded],
  ["maskable-512.png", 512, bleed],
  ["apple-touch-icon.png", 180, bleed],
]

const browser = await chromium.launch()
const page = await browser.newPage()
for (const [name, size, body] of icons) {
  await page.setViewportSize({ width: size, height: size })
  await page.setContent(
    `<style>html,body{margin:0;background:transparent}</style>
     <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="${size}" height="${size}">${body}</svg>`
  )
  await page.screenshot({ path: `public/icons/${name}`, omitBackground: true })
}
await browser.close()
console.log(`wrote ${icons.length} icons to public/icons/`)

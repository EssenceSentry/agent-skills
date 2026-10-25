import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { areas, commands } from "@/lib/help"
import { HelpScreen } from "@/screens/help"

describe("HelpScreen", () => {
  // Compare against the page's text: the markup escapes quotes and ampersands.
  const page = renderToStaticMarkup(<HelpScreen />)
    .replaceAll("&#x27;", "'")
    .replaceAll("&quot;", '"')
    .replaceAll("&amp;", "&")

  it("shows every area of ax and every command", () => {
    for (const area of areas) expect(page).toContain(area.title)
    for (const [name] of commands) expect(page).toContain(name)
  })

  it("says how a pause works and what agents may do alone", () => {
    expect(page).toContain("AX_INTENT")
    expect(page).toContain("What agents may do alone")
  })
})

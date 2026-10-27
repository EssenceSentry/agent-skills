import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Lightbox } from "@/blocks/pictures"

describe("the picture gallery", () => {
  it("shows the picture chosen, where it is among the others, and ways to move and zoom", () => {
    const html = renderToStaticMarkup(
      <Lightbox urls={["/a.png", "/b.png", "/c.png"]} index={1} onClose={() => undefined} />
    )
    expect(html).toContain('src="/b.png"')
    expect(html).toContain("2 / 3")
    expect(html).toContain('aria-label="Previous picture"')
    expect(html).toContain('aria-label="Next picture"')
    expect(html).toContain('aria-label="Zoom in"')
    expect(html).toContain('aria-label="Picture 3"')
  })

  it("shows one picture alone, still zoomable", () => {
    const html = renderToStaticMarkup(
      <Lightbox urls={["/a.png"]} index={0} onClose={() => undefined} />
    )
    expect(html).not.toContain("Previous picture")
    expect(html).not.toContain("1 / 1")
    expect(html).toContain('aria-label="Zoom in"')
  })

  it("is nothing when no picture is open", () => {
    expect(renderToStaticMarkup(<Lightbox urls={[]} index={0} onClose={() => undefined} />)).toBe(
      ""
    )
  })
})

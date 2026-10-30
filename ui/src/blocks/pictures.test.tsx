// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it } from "vitest"

import { Lightbox, MissingPicture } from "@/blocks/pictures"

afterEach(cleanup)

describe("the picture gallery", () => {
  it("shows the chosen picture and traps focus until it closes", async () => {
    const user = userEvent.setup()
    function Gallery() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open pictures
          </button>
          <button type="button">Background action</button>
          <Lightbox
            urls={open ? ["/a.png", "/b.png", "/c.png"] : []}
            index={1}
            onClose={() => setOpen(false)}
          />
        </>
      )
    }
    render(<Gallery />)
    const opener = screen.getByRole("button", { name: "Open pictures" })
    await user.click(opener)
    const dialog = screen.getByRole("dialog", { name: "Pictures, full size" })
    expect(dialog.querySelector('img[src="/b.png"]')).not.toBeNull()
    expect(dialog.textContent).toContain("2 / 3")
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))
    for (let i = 0; i < 14; i++) {
      await user.tab()
      await waitFor(() =>
        expect(dialog.contains(document.activeElement), document.activeElement?.outerHTML).toBe(
          true
        )
      )
    }
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(document.activeElement).toBe(opener)
  })

  it("renders nothing when closed", () => {
    expect(renderToStaticMarkup(<Lightbox urls={[]} index={0} onClose={() => undefined} />)).toBe(
      ""
    )
  })
})

describe("a picture that doesn't load", () => {
  it("keeps its thumbnail's place and says so, instead of an empty sliver", () => {
    const out = renderToStaticMarkup(<MissingPicture label="Screenshots it took" n={2} />)
    expect(out).toContain('aria-label="Screenshots it took: picture 2 didn&#x27;t load"')
    expect(out).toContain("Didn’t load")
    expect(out).toMatch(/class="[^"]*\bh-24\b/)
  })
})

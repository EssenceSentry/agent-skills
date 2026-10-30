import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { SlashMenu } from "@/blocks/slash-menu"

const none = () => undefined

describe("the / menu", () => {
  const sections = [
    {
      label: null,
      rows: [
        { key: "goal", title: "Goal", description: "Set a goal", marks: [], icon: "goal" as const },
      ],
    },
    {
      label: "Skills",
      rows: [
        {
          key: "atelier",
          title: "Atelier",
          description: "Build dashboards",
          scope: "Personal",
          marks: [0, 1],
          icon: "skill" as const,
        },
      ],
    },
  ]

  it("lists commands, then skills under their heading, the typed letters in bold", () => {
    const out = renderToStaticMarkup(
      <SlashMenu sections={sections} active={1} onPick={none} onHover={none} />
    )
    expect(out).toContain('role="listbox"')
    expect(out).toContain(">Skills<")
    expect(out).toContain("<strong>At</strong>elier")
    expect(out).toContain("Personal")
    expect(out).toMatch(
      /aria-selected="true"[^>]*>(?:(?!role="option").)*<strong>At<\/strong>elier/s
    )
    expect(out).toMatch(/aria-selected="false"[^>]*>(?:(?!role="option").)*Goal/s)
  })

  it("says when it is still asking the tool, or why the tool couldn't answer", () => {
    const reading = renderToStaticMarkup(
      <SlashMenu sections={[]} active={0} onPick={none} onHover={none} note="Asking Claude…" />
    )
    expect(reading).toContain("Asking Claude…")
  })
})

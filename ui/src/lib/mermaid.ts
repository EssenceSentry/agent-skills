// Mermaid, loaded only once an answer shows a diagram.
import mermaid from "mermaid"

let drawn = 0
let setUp: string | null = null

/**
 * A diagram's SVG, in the page's font and its light or dark. Mermaid's strict mode keeps
 * scripts and click handlers out of what an answer draws; labels are plain SVG text, so
 * the diagram also shows as a picture, full size.
 */
export async function drawDiagram(source: string, dark: boolean, font: string): Promise<string> {
  const wanted = `${dark ? "dark" : "neutral"}|${font}`
  if (setUp !== wanted) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: dark ? "dark" : "neutral",
      fontFamily: font,
      htmlLabels: false,
      flowchart: { htmlLabels: false },
      // A diagram that can't be drawn, as while it is still being written, says so in
      // the answer; Mermaid's own error picture would land at the foot of the page.
      suppressErrorRendering: true,
    })
    setUp = wanted
  }
  await mermaid.parse(source)
  drawn += 1
  const id = `ax-diagram-${drawn}`
  try {
    const { svg } = await mermaid.render(id, source)
    return svg
  } finally {
    document.getElementById(`d${id}`)?.remove() // its scratch element, if left behind
  }
}

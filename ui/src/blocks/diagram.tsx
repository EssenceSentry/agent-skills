import { Maximize2 } from "lucide-react"
import { useEffect, useState } from "react"

import { Lightbox } from "@/blocks/pictures"

/**
 * The drawn SVG as a picture for the gallery: sized from its viewBox, so it scales
 * sharply as it zooms, on the page's background, so dark lines stay visible.
 */
export function svgPicture(svg: string, background: string): string {
  const box = /viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"/.exec(svg)
  let sized = svg.replace(/\swidth="100%"/, "").replace(/\sstyle="max-width:[^"]*"/, "")
  sized = sized.replace(
    "<svg",
    `<svg${box ? ` width="${box[1]}" height="${box[2]}"` : ""} style="background-color:${background}"`
  )
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(sized)}`
}

/**
 * A Mermaid diagram from an answer, drawn when Mermaid has loaded: its source shows until
 * then, and stays with a note if it can't be drawn (as while it is still being written).
 * It opens full size in the picture gallery, to zoom and drag.
 */
export function Diagram({ source }: { source: string }) {
  const [svg, setSvg] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [picture, setPicture] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    const root = getComputedStyle(document.documentElement)
    const dark = root.colorScheme.includes("dark")
    const font = getComputedStyle(document.body).fontFamily
    import("@/lib/mermaid")
      .then(({ drawDiagram }) => drawDiagram(source, dark, font))
      .then(
        (drawn) => {
          if (!current) return
          setSvg(drawn)
          setFailed(null)
        },
        (error: Error) => {
          if (!current) return
          setSvg(null)
          setFailed(error.message.split("\n")[0] ?? "Mermaid couldn't read it")
        }
      )
    return () => {
      current = false
    }
  }, [source])

  const open = () => {
    if (!svg) return
    setPicture(svgPicture(svg, getComputedStyle(document.body).backgroundColor))
  }

  return (
    <figure className="mermaid-diagram group relative">
      {svg ? (
        // Mermaid's strict mode has already sanitised what it drew.
        <button
          type="button"
          className="mermaid-drawn block w-full cursor-zoom-in"
          onClick={open}
          tabIndex={-1}
          // biome-ignore lint/security/noDangerouslySetInnerHtml: Mermaid's sanitised SVG
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : (
        <pre className="mermaid-source">
          <code>{source}</code>
        </pre>
      )}
      {failed && (
        <figcaption className="text-[12px] text-muted-foreground">
          This diagram didn't draw: {failed}
        </figcaption>
      )}
      <button
        type="button"
        className="mermaid-zoom absolute top-1.5 right-1.5 grid size-7 place-items-center rounded-md border bg-card text-muted-foreground opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 hover:text-foreground disabled:hidden"
        aria-label="Open the diagram full size"
        title="Open full size, to zoom and drag"
        disabled={!svg}
        onClick={open}
      >
        <Maximize2 className="size-3.5" aria-hidden />
      </button>
      <Lightbox urls={picture ? [picture] : []} index={0} onClose={() => setPicture(null)} />
    </figure>
  )
}

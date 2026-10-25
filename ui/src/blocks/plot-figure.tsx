import type { VizTokens } from "@atelier/theme/viz"
import * as Plot from "@observablehq/plot"
import { useEffect, useRef, useState } from "react"

import { useVizTokens } from "@/blocks/use-viz-tokens"
import { cn } from "@/lib/utils"

type Build = (t: VizTokens, width: number) => Plot.PlotOptions

/** Shared axis and type styling so every chart recedes the same way. */
export function baseOptions(t: VizTokens, width: number): Plot.PlotOptions {
  return {
    width,
    style: {
      background: "transparent",
      color: t.text,
      fontFamily: t.labelFont,
      fontSize: "11px",
      overflow: "visible",
    },
  }
}

/** Tooltip styled from the direction's popover tokens. */
export const tipStyle = (t: VizTokens) => ({
  fill: t.popover,
  stroke: t.border,
  textPadding: 8,
  fontSize: 11,
})

export function PlotFigure({
  build,
  height,
  className,
}: {
  build: Build
  height: number
  className?: string
}) {
  const ref = useRef<HTMLElement>(null)
  const tokens = useVizTokens()
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    // Measure once up front: ResizeObserver waits for a rendered frame, which
    // background tabs and headless captures may never produce.
    setWidth(Math.floor(el.getBoundingClientRect().width))
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    // data-state lets screenshot QA tell a slow chart from a broken one.
    if (!tokens || width === 0) {
      el.dataset.state = tokens ? "no-width" : "no-tokens"
      return
    }
    let chart: ReturnType<typeof Plot.plot>
    try {
      chart = Plot.plot({ ...baseOptions(tokens, width), height, ...build(tokens, width) })
    } catch (error) {
      el.dataset.state = `error: ${(error as Error).message}`
      console.error("chart failed", error)
      return
    }
    el.dataset.state = "ok"
    el.replaceChildren(chart)
    return () => chart.remove()
  }, [tokens, width, height, build])

  return <figure ref={ref} className={cn("plot-figure m-0 w-full", className)} style={{ height }} />
}

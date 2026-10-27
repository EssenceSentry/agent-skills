import { ChevronLeft, ChevronRight, Minus, Plus, RotateCcw, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { step, type View, WHOLE, zoomAround } from "@/lib/gallery"
import { assetUrl } from "@/lib/transport"
import { cn } from "@/lib/utils"

/** A row of thumbnails; each opens the gallery of them, at itself. */
export function Pictures({
  urls,
  onOpen,
  label,
  className,
}: {
  urls: string[]
  onOpen: (urls: string[], index: number) => void
  label: string
  className?: string
}) {
  if (!urls.length) return null
  return (
    <ul className={cn("flex flex-wrap gap-2", className)} aria-label={label}>
      {urls.map((url, i) => (
        <li key={url}>
          <button
            type="button"
            onClick={() => onOpen(urls, i)}
            className="block overflow-hidden rounded-lg border bg-sunken/60 transition-opacity hover:opacity-90"
            aria-label={`${label}: picture ${i + 1}, full size`}
          >
            <img
              src={assetUrl(url)}
              alt=""
              loading="lazy"
              className="h-24 w-auto max-w-[220px] object-cover"
            />
          </button>
        </li>
      ))}
    </ul>
  )
}

const ROUND =
  "grid size-9 place-items-center rounded-full bg-card text-foreground shadow transition-colors hover:bg-muted disabled:opacity-40"

/**
 * The pictures of one message over the page, as large as fits: the arrows, a key or a
 * thumbnail go to the others; the wheel, the buttons or a double-click zoom, and a zoomed
 * picture drags. Escape, the cross or a click beside the picture closes it.
 */
export function Lightbox({
  urls,
  index,
  onClose,
}: {
  urls: string[]
  index: number
  onClose: () => void
}) {
  const [at, setAt] = useState(index)
  const [view, setView] = useState<View>(WHOLE)
  const frame = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; from: View } | null>(null)
  const dragged = useRef(false) // the click that ends a drag doesn't close
  const many = urls.length > 1
  const go = (delta: number) => setAt((i) => step(i, urls.length, delta))

  // Each opening starts at the picture chosen, whole.
  // biome-ignore lint/correctness/useExhaustiveDependencies: another message's pictures reopen it
  useEffect(() => {
    setAt(index)
    setView(WHOLE)
  }, [urls, index])
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new picture starts whole
  useEffect(() => setView(WHOLE), [at])

  // Where the pointer is, in the frame the picture is laid out in.
  const pointIn = (clientX: number, clientY: number) => {
    const box = frame.current?.getBoundingClientRect()
    return box ? { x: clientX - box.left, y: clientY - box.top } : { x: 0, y: 0 }
  }
  const centre = () => {
    const box = frame.current?.getBoundingClientRect()
    return box ? { x: box.width / 2, y: box.height / 2 } : { x: 0, y: 0 }
  }

  useEffect(() => {
    if (!urls.length) return
    const keys = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
      else if (e.key === "ArrowRight" && many) go(1)
      else if (e.key === "ArrowLeft" && many) go(-1)
      else if (e.key === "+" || e.key === "=") setView((v) => zoomAround(v, 1.5, centre()))
      else if (e.key === "-") setView((v) => zoomAround(v, 1 / 1.5, centre()))
      else if (e.key === "0") setView(WHOLE)
    }
    window.addEventListener("keydown", keys)
    // The wheel zooms; it needs a listener that may stop the page from scrolling.
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      setView((v) => zoomAround(v, Math.exp(-e.deltaY * 0.002), pointIn(e.clientX, e.clientY)))
    }
    const surface = frame.current
    surface?.addEventListener("wheel", wheel, { passive: false })
    return () => {
      window.removeEventListener("keydown", keys)
      surface?.removeEventListener("wheel", wheel)
    }
  })

  const url = urls[at]
  if (!url) return null
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Pictures, full size"
      className="chat-gallery fixed inset-0 z-50 flex flex-col bg-background/95 backdrop-blur-sm"
    >
      <div className="flex items-center justify-between gap-3 px-4 pt-3">
        <span className="num text-xs text-muted-foreground">
          {many ? `${at + 1} / ${urls.length}` : ""}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={ROUND}
            aria-label="Zoom out"
            onClick={() => setView((v) => zoomAround(v, 1 / 1.5, centre()))}
            disabled={view.scale <= 1}
          >
            <Minus className="size-4" />
          </button>
          <span className="num w-12 text-center text-xs text-muted-foreground">
            {Math.round(view.scale * 100)}%
          </span>
          <button
            type="button"
            className={ROUND}
            aria-label="Zoom in"
            onClick={() => setView((v) => zoomAround(v, 1.5, centre()))}
          >
            <Plus className="size-4" />
          </button>
          <button
            type="button"
            className={ROUND}
            aria-label="Whole picture"
            onClick={() => setView(WHOLE)}
            disabled={view.scale <= 1}
          >
            <RotateCcw className="size-4" />
          </button>
          <button type="button" className={ROUND} aria-label="Close" onClick={onClose}>
            <X className="size-4" />
          </button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        {/* A click beside the picture closes; on the picture, it zooms or drags. */}
        <div
          ref={frame}
          role="application"
          aria-label="Picture: double-click or use the wheel to zoom, drag to move"
          className={cn(
            "absolute inset-0 overflow-hidden",
            view.scale > 1 ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"
          )}
          onClick={(e) => {
            if (dragged.current) dragged.current = false
            else if (!(e.target instanceof HTMLImageElement)) onClose()
          }}
          onKeyDown={(e) => e.key === "Enter" && onClose()}
          onPointerDown={(e) => {
            if (view.scale <= 1) return
            drag.current = { x: e.clientX, y: e.clientY, from: view }
            dragged.current = false
            e.currentTarget.setPointerCapture(e.pointerId)
          }}
          onPointerMove={(e) => {
            const from = drag.current
            if (from && Math.hypot(e.clientX - from.x, e.clientY - from.y) > 3)
              dragged.current = true
            if (from)
              setView({
                ...from.from,
                x: from.from.x + e.clientX - from.x,
                y: from.from.y + e.clientY - from.y,
              })
          }}
          onPointerUp={() => {
            drag.current = null
          }}
          onDoubleClick={(e) =>
            setView((v) =>
              v.scale > 1 ? WHOLE : zoomAround(v, 2.5, pointIn(e.clientX, e.clientY))
            )
          }
        >
          <div
            className="flex size-full items-center justify-center p-4"
            style={{
              transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
              transformOrigin: "0 0",
            }}
          >
            <img
              src={assetUrl(url)}
              alt=""
              draggable={false}
              className="max-h-full max-w-full rounded-lg border object-contain shadow-lg select-none"
            />
          </div>
        </div>
        {many && (
          <>
            <button
              type="button"
              className={cn(ROUND, "absolute top-1/2 left-3 -translate-y-1/2")}
              aria-label="Previous picture"
              onClick={() => go(-1)}
            >
              <ChevronLeft className="size-4" />
            </button>
            <button
              type="button"
              className={cn(ROUND, "absolute top-1/2 right-3 -translate-y-1/2")}
              aria-label="Next picture"
              onClick={() => go(1)}
            >
              <ChevronRight className="size-4" />
            </button>
          </>
        )}
      </div>

      {many && (
        <ul
          className="flex justify-center gap-2 overflow-x-auto px-4 py-3"
          aria-label="All pictures"
        >
          {urls.map((u, i) => (
            <li key={u}>
              <button
                type="button"
                aria-label={`Picture ${i + 1}`}
                aria-current={i === at ? "true" : undefined}
                onClick={() => setAt(i)}
                className={cn(
                  "block overflow-hidden rounded-md border-2 transition-opacity",
                  i === at ? "border-primary" : "border-transparent opacity-60 hover:opacity-100"
                )}
              >
                <img src={assetUrl(u)} alt="" className="h-14 w-auto max-w-[120px] object-cover" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

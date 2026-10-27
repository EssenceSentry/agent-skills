import { X } from "lucide-react"
import { useEffect } from "react"

import { assetUrl } from "@/lib/transport"
import { cn } from "@/lib/utils"

/** A row of thumbnails; each opens full size. */
export function Pictures({
  urls,
  onOpen,
  label,
  className,
}: {
  urls: string[]
  onOpen: (url: string) => void
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
            onClick={() => onOpen(url)}
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

/** One picture over the page, as large as fits; Escape, a click or the cross closes it. */
export function Lightbox({ url, onClose }: { url: string | null; onClose: () => void }) {
  useEffect(() => {
    if (!url) return
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", close)
    return () => window.removeEventListener("keydown", close)
  }, [url, onClose])
  if (!url) return null
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Picture, full size"
      className="fixed inset-0 z-50 grid place-items-center bg-background/90 p-4 backdrop-blur-sm"
      onClick={onClose}
      onKeyDown={(e) => e.key === "Enter" && onClose()}
    >
      <img
        src={assetUrl(url)}
        alt=""
        className="max-h-[90svh] max-w-full rounded-lg border object-contain shadow-lg"
      />
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute top-3 right-3 grid size-9 place-items-center rounded-full bg-card text-foreground shadow"
      >
        <X className="size-4" />
      </button>
    </div>
  )
}

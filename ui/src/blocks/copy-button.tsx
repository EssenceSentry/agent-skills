import { Check, Copy } from "lucide-react"
import { useContext, useState } from "react"

import { copyText } from "@/lib/copy"
import { EditorHost } from "@/lib/host"
import { cn } from "@/lib/utils"

/**
 * A small button that copies `text`, ticked for a moment once it has. Shown on hover or
 * focus of its `group` where there is a pointer to hover with, and always on a touch
 * screen.
 */
export function CopyButton({
  text,
  label,
  className,
}: {
  text: string
  label: string
  className?: string
}) {
  const editor = useContext(EditorHost)
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      aria-label={label}
      title={copied ? "Copied" : label}
      className={cn(
        "chat-copy inline-flex size-6 items-center justify-center rounded-md text-muted-foreground transition-opacity hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:hover)]:opacity-0",
        className
      )}
      onClick={() =>
        copyText(text, editor).then(
          () => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          },
          () => undefined
        )
      }
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </button>
  )
}

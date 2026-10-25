import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"

import { BrandMark } from "@/blocks/primitives"
import { cn } from "@/lib/utils"

export function AppBar({
  product,
  icon,
  crumbs = [],
  center,
  right,
  className,
}: {
  product: string
  /** The app's own mark; atelier's default mark when omitted. */
  icon?: ReactNode
  crumbs?: string[]
  center?: ReactNode
  right?: ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        "sticky top-[env(safe-area-inset-top,0px)] z-20 flex h-14 items-center gap-4 border-b bg-background/85 px-4 backdrop-blur-md md:px-6",
        className
      )}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        {icon ?? <BrandMark />}
        <span className="font-heading text-[15px] font-semibold tracking-tight">{product}</span>
        {crumbs.map((c, i) => (
          <span
            key={c}
            className="hidden min-w-0 items-center gap-2.5 text-sm text-muted-foreground sm:flex"
          >
            <ChevronRight className="size-3.5 text-faint" />
            <span className={cn("truncate", i === crumbs.length - 1 && "text-foreground")}>
              {c}
            </span>
          </span>
        ))}
      </div>
      <div className="hidden flex-1 justify-center lg:flex">{center}</div>
      <div className="ml-auto flex items-center gap-2">{right}</div>
    </header>
  )
}

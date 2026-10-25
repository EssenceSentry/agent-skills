import { Search } from "lucide-react"
import { type FormEvent, useState } from "react"

import { Input } from "@/components/ui/input"
import { searchHref } from "@/lib/routes"
import { cn } from "@/lib/utils"

/** A box that runs `ax find` when you press Enter; nothing happens while you type. */
export function SearchBox({
  initial = "",
  autoFocus = false,
  className,
}: {
  initial?: string
  autoFocus?: boolean
  className?: string
}) {
  const [query, setQuery] = useState(initial)

  function submit(event: FormEvent) {
    event.preventDefault()
    const wanted = query.trim()
    if (wanted) window.location.hash = searchHref(wanted)
  }

  return (
    <search className={cn("block", className)}>
      <form onSubmit={submit} className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-faint" />
        <Input
          type="search"
          enterKeyHint="search"
          autoFocus={autoFocus}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search everything, then Enter"
          aria-label="Search conversations, memories, notes, docs and code"
          className="pl-8"
        />
      </form>
    </search>
  )
}

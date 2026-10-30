import { Search } from "lucide-react"
import { type FormEvent, useState } from "react"

import { Input } from "@/components/ui/input"
import { searchHref } from "@/lib/routes"
import { cn } from "@/lib/utils"

/** A box that runs `ax find` when you press Enter, on the search screen's address or, in
 * VS Code, through `onSearch`; nothing happens while you type. */
export function SearchBox({
  initial = "",
  autoFocus = false,
  className,
  onSearch,
}: {
  initial?: string
  autoFocus?: boolean
  className?: string
  onSearch?: (query: string) => void
}) {
  const [query, setQuery] = useState(initial)

  function submit(event: FormEvent) {
    event.preventDefault()
    const wanted = query.trim()
    if (!wanted) return
    if (onSearch) onSearch(wanted)
    else window.location.hash = searchHref(wanted)
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
          placeholder="Search sessions and memories, then Enter"
          aria-label="Search past conversations and memories"
          className="pl-8"
        />
      </form>
    </search>
  )
}

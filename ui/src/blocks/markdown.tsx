import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

import { remarkCallouts } from "@/lib/callouts"
import { cn } from "@/lib/utils"

const MISSING = "#/missing/"

function decode(part: string): string {
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

const components: Components = {
  a: ({ href = "", children }) => {
    if (href.startsWith(MISSING)) {
      const name = decode(href.slice(MISSING.length))
      return (
        <span className="missing-link" title={`No note named ${name}`}>
          {children}
        </span>
      )
    }
    if (/^https?:/i.test(href)) {
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      )
    }
    return <a href={href}>{children}</a>
  },
}

/**
 * A vault note's Markdown. The server has already turned `[[wiki links]]` into app links;
 * callouts become asides here. Raw HTML in a note is never rendered.
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("note-prose", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkCallouts]} components={components} skipHtml>
        {children}
      </ReactMarkdown>
    </div>
  )
}

import { useContext } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

import { remarkCallouts } from "@/lib/callouts"
import { EditorHost } from "@/lib/host"
import { looksLikePath } from "@/lib/paths"
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
 * In an editor's tab, code that names a file is also a link to it, a link to a file is
 * marked as one, and a wide table scrolls on its own.
 */
const inEditor: Components = {
  ...components,
  a: ({ href = "", children }) =>
    /^(?:[a-z][a-z0-9+.-]*:|#)/i.test(href) ? (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ) : (
      <a href={href} data-file="">
        {children}
      </a>
    ),
  table: ({ children }) => (
    <div className="table-scroll">
      <table>{children}</table>
    </div>
  ),
  code: ({ children, className }) => {
    const text = typeof children === "string" ? children : null
    if (text && !className && looksLikePath(text))
      return (
        <a href={text} data-file="">
          <code>{text}</code>
        </a>
      )
    return <code className={className}>{children}</code>
  },
}

/**
 * A vault note's Markdown. The server has already turned `[[wiki links]]` into app links;
 * callouts become asides here. Raw HTML in a note is never rendered.
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  const editor = useContext(EditorHost)
  return (
    <div className={cn("note-prose", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkCallouts]}
        components={editor ? inEditor : components}
        skipHtml
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

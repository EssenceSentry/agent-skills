import { type ReactNode, useContext, useEffect, useRef } from "react"
import ReactMarkdown, { type Components, type Options } from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"

import { remarkCallouts } from "@/lib/callouts"
import { EditorHost } from "@/lib/host"
import { mathDelimiters } from "@/lib/math"
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

/**
 * LaTeX, typeset by KaTeX once it has loaded; until then, and if it can't be read, the
 * source shows as it was written.
 */
function MathTex({ tex, display }: { tex: string; display: boolean }) {
  const shown = useRef<HTMLElement | null>(null)
  const keep = (element: HTMLElement | null) => {
    shown.current = element
  }
  useEffect(() => {
    let current = true
    import("@/lib/katex").then(({ default: katex }) => {
      if (current && shown.current)
        katex.render(tex, shown.current, { displayMode: display, throwOnError: false })
    })
    return () => {
      current = false
    }
  }, [tex, display])
  return display ? (
    <div ref={keep} className="math" data-math="display">
      {tex}
    </div>
  ) : (
    <span ref={keep} className="math" data-math="inline">
      {tex}
    </span>
  )
}

const mathKind = (className?: string) =>
  className?.includes("math-display")
    ? "display"
    : className?.includes("math-inline")
      ? "inline"
      : null

const text = (children: ReactNode) => (typeof children === "string" ? children : null)

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
  // A display formula arrives as code inside a <pre>, which it doesn't need.
  pre: ({ children, node }) => {
    const first = node?.children[0]
    const classes = first?.type === "element" ? String(first.properties.className ?? "") : ""
    return mathKind(classes) ? <>{children}</> : <pre>{children}</pre>
  },
  code: ({ children, className }) => {
    const kind = mathKind(className)
    const tex = text(children)
    if (kind && tex !== null) return <MathTex key={tex} tex={tex} display={kind === "display"} />
    return <code className={className}>{children}</code>
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
  code: (props) => {
    const path = text(props.children)
    if (path && !props.className && looksLikePath(path))
      return (
        <a href={path} data-file="">
          <code>{path}</code>
        </a>
      )
    const base = components.code as (p: typeof props) => ReactNode
    return base(props)
  },
}

const PLUGINS: Options["remarkPlugins"] = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
  remarkCallouts,
]

/**
 * A vault note's Markdown, or an agent's answer. The server has already turned `[[wiki
 * links]]` into app links; callouts become asides here, and LaTeX is typeset. Raw HTML is
 * never rendered.
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  const editor = useContext(EditorHost)
  return (
    <div className={cn("note-prose", className)}>
      <ReactMarkdown remarkPlugins={PLUGINS} components={editor ? inEditor : components} skipHtml>
        {mathDelimiters(children)}
      </ReactMarkdown>
    </div>
  )
}

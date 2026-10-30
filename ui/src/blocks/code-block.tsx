import { useEffect, useRef } from "react"
import { CopyButton } from "./copy-button"

export function CodeBlock({ source, language }: { source: string; language: string }) {
  const code = useRef<HTMLElement>(null)
  useEffect(() => {
    let current = true
    if (code.current) {
      code.current.textContent = source
      delete code.current.dataset.highlighted
    }
    if (language)
      void import("highlight.js/lib/common")
        .then(({ default: highlight }) => {
          if (current && code.current && highlight.getLanguage(language))
            highlight.highlightElement(code.current)
        })
        .catch(() => {})
    return () => {
      current = false
    }
  }, [source, language])
  return (
    <div className="my-3 overflow-hidden rounded-lg border">
      <div className="flex items-center justify-between gap-3 bg-muted px-2 py-1 text-xs text-muted-foreground">
        <span>{language || "Code"}</span>
        <CopyButton text={source} label="Copy code" />
      </div>
      <pre className="m-0 overflow-auto p-3">
        <code ref={code} className={`language-${language}`}>
          {source}
        </code>
      </pre>
    </div>
  )
}

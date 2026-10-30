import { useEffect, useRef, useState } from "react"
import type { Reference } from "@/lib/plus"
import { referenceLabel } from "@/lib/plus"
import { askExtension, inExtension, request } from "@/lib/transport"

export function ContextPicker({
  text,
  setText,
  cwd,
  add,
}: {
  text: string
  setText: (text: string) => void
  cwd: string | null
  add: (refs: Reference[]) => void
}) {
  const query = /(?:^|\s)@([^\s@]*)$/.exec(text)?.[1]
  const root = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState(0)
  const [files, setFiles] = useState<Reference[]>([])
  const choose = (file: Reference) => {
    add([file])
    setText(text.replace(/@[^\s@]*$/, ""))
    setFiles([])
  }
  useEffect(() => {
    if (!files.length) return
    const key = (event: KeyboardEvent) => {
      const area = root.current?.closest("form") ?? root.current?.parentElement
      if (!(event.target instanceof HTMLTextAreaElement) || !area?.contains(event.target)) return
      if (
        !["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(event.key) ||
        event.shiftKey ||
        event.ctrlKey ||
        event.metaKey
      )
        return
      event.preventDefault()
      event.stopPropagation()
      if (event.key === "Escape") setFiles([])
      else if (event.key === "Enter") choose(files[selected] ?? files[0])
      else
        setSelected(
          (was) => (was + (event.key === "ArrowDown" ? 1 : files.length - 1)) % files.length
        )
    }
    window.addEventListener("keydown", key, true)
    return () => window.removeEventListener("keydown", key, true)
  })
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let current = true
    if (query === undefined) {
      setFiles([])
      return
    }
    const timer = setTimeout(() => {
      const load = inExtension()
        ? askExtension<Reference[]>("completeFiles", query)
        : request<Reference[]>(
            "GET",
            `/api/session/files?${new URLSearchParams({ cwd: cwd ?? "", q: query })}`
          )
      void load.then(
        (found) => {
          if (current) {
            setFiles(found)
            setSelected(0)
            setError(null)
          }
        },
        (e: Error) => current && setError(e.message)
      )
    }, 120)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [query, cwd])
  return (
    <div ref={root}>
      <div className="flex flex-wrap gap-3 px-1 text-xs text-muted-foreground">
        {inExtension() && (
          <>
            <button
              type="button"
              onClick={() =>
                void askExtension<Reference[]>("terminal").then(add, (e: Error) =>
                  setError(e.message)
                )
              }
            >
              Attach terminal selection
            </button>
            <button
              type="button"
              onClick={() =>
                void askExtension<Reference[]>("problems").then(add, (e: Error) =>
                  setError(e.message)
                )
              }
            >
              Attach Problems
            </button>
          </>
        )}
        <span>@file or @file:line–line</span>
      </div>
      {files.length > 0 && (
        <ul
          aria-label="File references"
          className="max-h-48 overflow-auto rounded border bg-card p-1 text-xs"
        >
          {files.map((file, index) => (
            <li key={`${file.kind}:${file.path}`}>
              <button
                type="button"
                className={`w-full p-1 text-left hover:bg-muted ${selected === index ? "bg-muted" : ""}`}
                onClick={() => choose(file)}
              >
                {referenceLabel(file)}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="text-xs text-critical">{error}</p>}
    </div>
  )
}

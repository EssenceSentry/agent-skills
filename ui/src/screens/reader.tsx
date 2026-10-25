import { ChevronLeft, ChevronRight, FileText, Folder } from "lucide-react"

import { Markdown } from "@/blocks/markdown"
import { SearchBox } from "@/blocks/search-box"
import { type Folder as FolderData, loadFolder, loadNote, type Note, useLoad } from "@/lib/ax"
import { folderHref, type Route, readHref } from "@/lib/routes"
import { ago } from "@/lib/time"
import { cn } from "@/lib/utils"

const SHOWN = 300

const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "")

function Crumbs({ dir }: { dir: string }) {
  const parts = dir ? dir.split("/") : []
  return (
    <nav aria-label="Folder" className="flex min-w-0 flex-wrap items-center gap-1 text-[13px]">
      <a href={folderHref("")} className="text-muted-foreground hover:text-foreground">
        Vault
      </a>
      {parts.map((part, i) => {
        const path = parts.slice(0, i + 1).join("/")
        return (
          <span key={path} className="flex min-w-0 items-center gap-1">
            <ChevronRight className="size-3 shrink-0 text-faint" />
            <a
              href={folderHref(path)}
              className={cn(
                "truncate hover:text-foreground",
                i === parts.length - 1 ? "font-medium text-foreground" : "text-muted-foreground"
              )}
            >
              {part}
            </a>
          </span>
        )
      })}
    </nav>
  )
}

function FolderPanel({
  dir,
  folder,
  error,
  current,
}: {
  dir: string
  folder?: FolderData
  error?: string
  current?: string
}) {
  const folders = folder?.folders ?? []
  const notes = folder?.notes ?? []
  return (
    <div className="panel flex min-w-0 flex-col overflow-hidden">
      <div className="space-y-3 border-b p-4">
        <Crumbs dir={dir} />
        <SearchBox />
      </div>
      {error && <p className="p-4 text-sm text-muted-foreground">{error}</p>}
      {!error && !folder && <p className="p-4 text-sm text-muted-foreground">Loading…</p>}
      {folder && (
        <ul className="divide-y overflow-y-auto lg:max-h-[calc(100svh-15rem)]">
          {folder.parent !== null && (
            <li>
              <a
                href={folderHref(folder.parent)}
                className="flex items-center gap-2.5 px-4 py-2 text-[13px] text-muted-foreground hover:bg-muted"
              >
                <ChevronLeft className="size-4" /> Up
              </a>
            </li>
          )}
          {folders.map((f) => (
            <li key={f.path}>
              <a
                href={folderHref(f.path)}
                className="flex items-center gap-2.5 px-4 py-2 text-[13px] hover:bg-muted"
              >
                <Folder className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate">{f.name}</span>
              </a>
            </li>
          ))}
          {notes.slice(0, SHOWN).map((n) => (
            <li key={n.path}>
              <a
                href={readHref(n.path)}
                aria-current={n.path === current ? "page" : undefined}
                className={cn(
                  "flex items-start gap-2.5 px-4 py-2 hover:bg-muted",
                  n.path === current && "bg-primary-soft hover:bg-primary-soft"
                )}
              >
                <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0">
                  <span className="line-clamp-2 text-[13px] leading-snug">{n.title}</span>
                  <span className="text-[11px] text-muted-foreground">{ago(n.modified)}</span>
                </span>
              </a>
            </li>
          ))}
          {notes.length > SHOWN && (
            <li className="px-4 py-2 text-xs text-muted-foreground">
              {notes.length - SHOWN} more; search to find them.
            </li>
          )}
          {!folders.length && !notes.length && (
            <li className="px-4 py-3 text-[13px] text-muted-foreground">This folder is empty.</li>
          )}
        </ul>
      )}
    </div>
  )
}

function NoteView({ note }: { note: Note }) {
  return (
    <article className="panel min-w-0 p-5 md:p-8">
      <div className="label-mono text-[11px] break-all text-muted-foreground">{note.path}</div>
      <h1 className="mt-2 text-[24px] leading-tight break-words md:text-[30px]">{note.title}</h1>
      <div className="mt-1.5 text-xs text-muted-foreground">
        modified {ago(note.modified)} · read-only here; edit it in VS Code
      </div>
      {note.properties.length > 0 && (
        <dl className="well mt-5 grid grid-cols-[minmax(5.5rem,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5 p-3 text-[13px]">
          {note.properties.map((p) => (
            <div key={p.key} className="contents">
              <dt className="label-mono pt-px text-[11.5px] text-muted-foreground">{p.key}</dt>
              <dd className="min-w-0 break-words">
                <Markdown className="note-inline">{p.value || "—"}</Markdown>
              </dd>
            </div>
          ))}
        </dl>
      )}
      <Markdown className="mt-6">{note.markdown}</Markdown>
    </article>
  )
}

export function ReaderScreen({
  route,
}: {
  route: Exclude<Route, { screen: "now" | "help" | "search" }>
}) {
  const reading = route.screen === "read" ? route.path : null
  const dir = route.screen === "notes" ? route.dir : parentOf(route.path)
  const folder = useLoad(dir, loadFolder)
  const note = useLoad(reading, loadNote)
  return (
    <main className="mx-auto grid max-w-[1360px] gap-4 p-4 md:gap-5 md:p-6 lg:grid-cols-[minmax(17rem,20rem)_minmax(0,1fr)]">
      <div className={cn("min-w-0", reading && "hidden lg:block")}>
        <FolderPanel
          key={dir}
          dir={dir}
          folder={folder.data}
          error={folder.error}
          current={reading ?? undefined}
        />
      </div>
      <div className="min-w-0 space-y-3">
        {reading && (
          <a
            href={folderHref(dir)}
            className="inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground lg:hidden"
          >
            <ChevronLeft className="size-4" /> {dir || "Vault"}
          </a>
        )}
        {reading && note.data && <NoteView note={note.data} />}
        {reading && note.error && (
          <div className="panel p-6 text-sm text-muted-foreground">
            This note can't be shown: {note.error}
          </div>
        )}
        {reading && note.loading && (
          <div className="panel p-6 text-sm text-muted-foreground">Loading…</div>
        )}
        {!reading && (
          <div className="panel hidden p-8 text-sm text-muted-foreground lg:block">
            <div className="text-[15px] font-medium text-foreground">Pick a note</div>
            <p className="mt-1 max-w-prose">
              Every note in your vault, read-only. Links between notes open here; conversation notes
              are rewritten by <code className="label-mono">ax sync</code>, and you can edit the
              others in VS Code.
            </p>
          </div>
        )}
      </div>
    </main>
  )
}

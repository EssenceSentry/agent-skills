import { Popover } from "@base-ui/react/popover"
import { Check, ChevronDown, Folder, FolderOpen } from "lucide-react"
import { type ReactNode, useState } from "react"

import { type FolderChoice, folderChoices } from "@/lib/panel"
import { shortPath } from "@/lib/paths"
import type { Session } from "@/lib/sessions"

/*
 * Where a new session starts, picked as the Claude app picks an environment: a pill under
 * the message box opening a searchable list of the workspace's folders and the folders of
 * recent sessions, and Choose… for any other.
 */

const label = (path: string) => path.split("/").filter(Boolean).at(-1) ?? path

function Heading({ children }: { children: ReactNode }) {
  return (
    <div className="chat-folder-heading px-2 pt-2 pb-1 text-[12px] text-muted-foreground">
      {children}
    </div>
  )
}

/** The list the pill opens: search, the folders, and Choose…. */
export function FolderMenu({
  folder,
  workspace,
  sessions,
  onPick,
  onChoose,
}: {
  folder: string
  workspace: string[]
  sessions: Session[]
  onPick: (path: string) => void
  /** Any other folder, from the system's dialog, where an editor is behind the page; on
   * the web page a path typed in the search is offered instead. */
  onChoose?: () => void
}) {
  const [query, setQuery] = useState("")
  const found = folderChoices(workspace, sessions, query)
  const typed = /^[/~]/.test(query.trim()) ? query.trim() : null
  const listed = [...found.workspace, ...found.recent].some((f) => f.path === folder)
  // One chosen from anywhere stays offered, first among the recent ones.
  const recent =
    folder &&
    !listed &&
    !workspace.includes(folder) &&
    folder.toLowerCase().includes(query.trim().toLowerCase())
      ? [{ path: folder, label: label(folder) }, ...found.recent]
      : found.recent
  const row = (f: FolderChoice) => {
    const on = f.path === folder
    return (
      <button
        key={f.path}
        type="button"
        role="option"
        aria-selected={on}
        aria-checked={on}
        title={f.path}
        className="chat-folder-row flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-muted"
        onClick={() => onPick(f.path)}
      >
        <Folder className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 shrink-0">{f.label}</span>
        {/* Where it lives: two folders of one name, or a scratch folder, tell apart. */}
        <span className="chat-folder-where min-w-0 flex-1 truncate text-[12px] text-muted-foreground">
          {shortPath(f.path.slice(0, f.path.length - f.label.length).replace(/\/$/, ""))}
        </span>
        {on && <Check className="chat-folder-check size-4 shrink-0 text-primary" />}
      </button>
    )
  }
  return (
    <div className="chat-folder-menu flex flex-col">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search folders…"
        aria-label="Search folders"
        className="chat-folder-search border-b bg-transparent px-3 py-2.5 text-[13px] outline-none placeholder:text-muted-foreground"
      />
      <div role="listbox" aria-label="Folders" className="max-h-72 overflow-y-auto p-1">
        {found.workspace.length > 0 && (
          <>
            <Heading>Workspace</Heading>
            {found.workspace.map(row)}
          </>
        )}
        {recent.length > 0 && (
          <>
            <Heading>Recent</Heading>
            {recent.map(row)}
          </>
        )}
        {found.workspace.length === 0 && recent.length === 0 && (
          <p className="px-2 py-2 text-[12.5px] text-muted-foreground">No folder matches.</p>
        )}
      </div>
      {(onChoose || typed) && (
        <div className="border-t p-1">
          <button
            type="button"
            className="chat-folder-row flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-muted"
            title={typed ?? undefined}
            onClick={onChoose ?? (() => typed && onPick(typed))}
          >
            <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{onChoose ? "Choose…" : `Use ${typed}`}</span>
          </button>
        </div>
      )}
    </div>
  )
}

/** The pill naming the folder, and the list it opens. */
export function FolderPicker({
  folder,
  workspace,
  sessions,
  onChange,
  onChoose,
  disabled,
}: {
  folder: string
  workspace: string[]
  sessions: Session[]
  onChange: (path: string) => void
  /** Any other folder, from the system's dialog; null when none was picked. Only where
   * an editor is behind the page. */
  onChoose?: () => Promise<string | null>
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const name = folder ? label(folder) : "Choose a folder"
  return (
    <span className="chat-folder-wrap inline-flex min-w-0">
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger
          className="chat-folder inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          aria-label={`Folder: ${name}`}
          title={folder || undefined}
          disabled={disabled}
        >
          <Folder className="size-3.5 shrink-0" />
          <span className="truncate">{name}</span>
          <ChevronDown className="size-3.5 shrink-0" />
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Positioner side="top" align="start" sideOffset={6} className="isolate z-50">
            <Popover.Popup
              className="chat-folder-popup w-72 overflow-hidden rounded-2xl border bg-popover text-popover-foreground shadow-lg outline-none"
              aria-label="Folders"
            >
              <FolderMenu
                folder={folder}
                workspace={workspace}
                sessions={sessions}
                onPick={(path) => {
                  onChange(path)
                  setOpen(false)
                }}
                onChoose={
                  onChoose &&
                  (() => {
                    setOpen(false)
                    void onChoose().then((path) => path && onChange(path))
                  })
                }
              />
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      </Popover.Root>
    </span>
  )
}

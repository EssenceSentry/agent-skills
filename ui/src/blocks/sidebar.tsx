import { CircleHelp, House, NotebookText, Search } from "lucide-react"

import { AppIcon } from "@/app-icon"
import { StatusBadge } from "@/blocks/primitives"
import type { LiveStatus } from "@/lib/ax"
import { type Route, sessionHref } from "@/lib/routes"
import { SessionsPanel } from "@/screens/panel"

const LIVE_BADGE: Record<
  Exclude<LiveStatus, "live">,
  { status: "queued" | "warning" | "paused"; label: string }
> = {
  connecting: { status: "queued", label: "Connecting" },
  offline: { status: "warning", label: "Offline" },
  example: { status: "paused", label: "Example data" },
  locked: { status: "warning", label: "Locked" },
}

/** The other screens, from the sidebar's head as VS Code's view actions sit on its title. */
const SCREENS = [
  { href: "#/search", label: "Search", Icon: Search, on: ["search"] },
  { href: "#/", label: "Now", Icon: House, on: ["now", "usage", "sessions"] },
  { href: "#/notes", label: "Notes", Icon: NotebookText, on: ["notes", "read"] },
  { href: "#/help", label: "What ax can do", Icon: CircleHelp, on: ["help"] },
] as const

function Head({ route, status }: { route: Route; status: LiveStatus }) {
  const badge = status === "live" ? null : LIVE_BADGE[status]
  return (
    <header className="chat-panel-top flex shrink-0 items-center gap-2 px-4 pt-3 pb-1">
      <span className="flex items-center gap-2 text-[13px] font-semibold">
        <AppIcon className="size-5" />
        ax
      </span>
      {badge && <StatusBadge status={badge.status} label={badge.label} />}
      <nav aria-label="Screens" className="ml-auto flex items-center gap-0.5">
        {SCREENS.map(({ href, label, Icon, on }) => (
          <a
            key={href}
            aria-current={(on as readonly string[]).includes(route.screen) ? "page" : undefined}
            href={href}
            aria-label={label}
            title={label}
            className="chat-panel-tool grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Icon className="size-4" aria-hidden />
          </a>
        ))}
      </nav>
    </header>
  )
}

/**
 * The web page's sidebar: ax's VS Code panel on the left, as VS Code would show it, each
 * session a link that opens it beside, the one open marked; the other screens and whether
 * ax answers in its head. A session started from its foot opens beside it too.
 */
export function Sidebar({ route, status }: { route: Route; status: LiveStatus }) {
  const current = route.screen === "session" ? { provider: route.provider, id: route.id } : null
  return (
    <aside className="ax-sidebar" aria-label="ax">
      <SessionsPanel
        folders={[]}
        hrefFor={sessionHref}
        current={current}
        onStarted={(provider, id) => {
          window.location.hash = sessionHref(provider, id)
        }}
        head={<Head route={route} status={status} />}
      />
    </aside>
  )
}

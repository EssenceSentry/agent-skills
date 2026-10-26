import { CircleHelp } from "lucide-react"

import { AppIcon } from "@/app-icon"
import { AppBar } from "@/blocks/app-bar"
import { StatusBadge } from "@/blocks/primitives"
import { UsageIndicator } from "@/blocks/usage-band"
import { TooltipProvider } from "@/components/ui/tooltip"
import { type LiveStatus, useNow, useTick } from "@/lib/ax"
import { type Route, useRoute } from "@/lib/routes"
import { ago } from "@/lib/time"
import { cn } from "@/lib/utils"
import { HelpScreen } from "@/screens/help"
import { NowScreen } from "@/screens/now"
import { ReaderScreen } from "@/screens/reader"
import { SearchScreen } from "@/screens/search"
import { SessionScreen } from "@/screens/session"
import { SessionsScreen } from "@/screens/sessions"
import { UsageScreen } from "@/screens/usage"

const LIVE_BADGE: Record<
  LiveStatus,
  { status: "running" | "queued" | "warning" | "paused"; label: string }
> = {
  live: { status: "running", label: "Live" },
  connecting: { status: "queued", label: "Connecting" },
  offline: { status: "warning", label: "Offline" },
  example: { status: "paused", label: "Example data" },
  locked: { status: "warning", label: "Locked" },
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: string }) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-lg px-2 py-1 text-sm transition-colors sm:px-2.5",
        active
          ? "bg-primary-soft font-medium text-primary-ink"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {children}
    </a>
  )
}

const CRUMBS: Record<Route["screen"], string> = {
  now: "Now",
  help: "Help",
  notes: "Notes",
  read: "Notes",
  search: "Search",
  sessions: "Sessions",
  session: "Sessions",
  usage: "Usage",
}

export default function App() {
  const route = useRoute()
  const { state, status, refresh } = useNow()
  useTick()
  const badge = LIVE_BADGE[status]
  return (
    <TooltipProvider>
      <div className="min-h-svh">
        <AppBar
          product="ax"
          icon={<AppIcon />}
          crumbs={[CRUMBS[route.screen]]}
          right={
            <>
              <nav className="flex items-center gap-1" aria-label="Screens">
                <NavLink href="#/" active={route.screen === "now"}>
                  Now
                </NavLink>
                <NavLink href="#/sessions" active={["sessions", "session"].includes(route.screen)}>
                  Sessions
                </NavLink>
                <NavLink href="#/notes" active={["notes", "read", "search"].includes(route.screen)}>
                  Notes
                </NavLink>
                <a
                  href="#/help"
                  aria-label="What ax can do"
                  title="What ax can do"
                  aria-current={route.screen === "help" ? "page" : undefined}
                  className={cn(
                    "grid size-8 place-items-center rounded-lg transition-colors",
                    route.screen === "help"
                      ? "bg-primary-soft text-primary-ink"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <CircleHelp className="size-[18px]" />
                </a>
              </nav>
              {state && <UsageIndicator rows={state.usage} credits={state.credits ?? []} />}
              <span
                className="hidden text-[11px] text-muted-foreground md:inline"
                title="When ax last archived your conversations"
              >
                synced {ago(state?.last_sync)}
              </span>
              {/* On a phone the bar has room only for a status that needs reading. */}
              <StatusBadge
                status={badge.status}
                label={badge.label}
                className={cn((status === "live" || status === "example") && "max-sm:hidden")}
              />
            </>
          }
        />
        {route.screen === "help" ? (
          <HelpScreen />
        ) : state ? (
          route.screen === "now" ? (
            <NowScreen state={state} refresh={refresh} />
          ) : route.screen === "search" ? (
            <SearchScreen query={route.query} />
          ) : route.screen === "usage" ? (
            <UsageScreen state={state} />
          ) : route.screen === "sessions" ? (
            <SessionsScreen />
          ) : route.screen === "session" ? (
            <SessionScreen provider={route.provider} id={route.id} />
          ) : (
            <ReaderScreen route={route} />
          )
        ) : (
          <main className="mx-auto max-w-[1360px] p-4 md:p-6">
            <div className="panel p-6 text-sm text-muted-foreground">
              {status === "locked"
                ? "This shared link has expired or lost its access. Open the newest link ax sent you."
                : status === "offline"
                  ? "ax isn't answering; retrying…"
                  : "Reading your ax…"}
            </div>
          </main>
        )}
      </div>
    </TooltipProvider>
  )
}

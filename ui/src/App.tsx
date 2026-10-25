import { AppIcon } from "@/app-icon"
import { AppBar } from "@/blocks/app-bar"
import { StatusBadge } from "@/blocks/primitives"
import { UsageBand } from "@/blocks/usage-band"
import { TooltipProvider } from "@/components/ui/tooltip"
import { type LiveStatus, useNow, useTick } from "@/lib/ax"
import { type Route, useRoute } from "@/lib/routes"
import { ago } from "@/lib/time"
import { cn } from "@/lib/utils"
import { NowScreen } from "@/screens/now"
import { ReaderScreen } from "@/screens/reader"

const LIVE_BADGE: Record<
  LiveStatus,
  { status: "running" | "queued" | "warning" | "paused"; label: string }
> = {
  live: { status: "running", label: "Live" },
  connecting: { status: "queued", label: "Connecting" },
  offline: { status: "warning", label: "Offline" },
  example: { status: "paused", label: "Example data" },
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: string }) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-lg px-2.5 py-1 text-sm transition-colors",
        active
          ? "bg-primary-soft font-medium text-primary-ink"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {children}
    </a>
  )
}

const crumb = (route: Route) => (route.screen === "now" ? "Now" : "Notes")

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
          crumbs={[crumb(route)]}
          right={
            <>
              <nav className="flex items-center gap-1" aria-label="Screens">
                <NavLink href="#/" active={route.screen === "now"}>
                  Now
                </NavLink>
                <NavLink href="#/notes" active={route.screen !== "now"}>
                  Notes
                </NavLink>
              </nav>
              <span
                className="hidden text-[11px] text-muted-foreground md:inline"
                title="When ax last archived your conversations"
              >
                synced {ago(state?.last_sync)}
              </span>
              <StatusBadge status={badge.status} label={badge.label} />
            </>
          }
        />
        {state ? (
          <>
            <UsageBand rows={state.usage} credits={state.credits ?? []} />
            {route.screen === "now" ? (
              <NowScreen state={state} refresh={refresh} />
            ) : (
              <ReaderScreen route={route} />
            )}
          </>
        ) : (
          <main className="mx-auto max-w-[1360px] p-4 md:p-6">
            <div className="panel p-6 text-sm text-muted-foreground">
              {status === "offline" ? "ax isn't answering; retrying…" : "Reading your ax…"}
            </div>
          </main>
        )}
      </div>
    </TooltipProvider>
  )
}

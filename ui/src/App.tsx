import { PanelLeft } from "lucide-react"
import { useEffect, useState } from "react"

import { AppIcon } from "@/app-icon"
import { Sidebar } from "@/blocks/sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useNow, useTick } from "@/lib/ax"
import { EditorLook } from "@/lib/host"
import { type Route, useRoute } from "@/lib/routes"
import { HelpScreen } from "@/screens/help"
import { NowScreen } from "@/screens/now"
import { ReaderScreen } from "@/screens/reader"
import { SearchScreen } from "@/screens/search"
import { SessionScreen } from "@/screens/session"
import { SessionsScreen } from "@/screens/sessions"
import { UsageScreen } from "@/screens/usage"

const CRUMBS: Record<Route["screen"], string> = {
  now: "Now",
  help: "Help",
  notes: "Notes",
  read: "Notes",
  search: "Search",
  sessions: "Sessions",
  session: "Session",
  usage: "Usage",
}

/**
 * ax's page as VS Code shows its extension: the sessions panel as a sidebar on the left,
 * and beside it the conversation picked there, or another of ax's screens. On a phone
 * the sidebar slides over from a bar at the top and closes on whatever is picked.
 */
export default function App() {
  const route = useRoute()
  const { state, status, refresh } = useNow()
  useTick()
  const [drawer, setDrawer] = useState(false)
  useEffect(() => {
    const close = () => setDrawer(false)
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close()
    window.addEventListener("hashchange", close)
    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("hashchange", close)
      window.removeEventListener("keydown", onKey)
    }
  }, [])
  return (
    <TooltipProvider>
      <EditorLook.Provider value={true}>
        <div className="ax-shell" data-drawer={drawer || undefined}>
          <Sidebar route={route} status={status} />
          <button
            type="button"
            className="ax-scrim"
            aria-label="Close the sidebar"
            onClick={() => setDrawer(false)}
          />
          <div className="ax-main" data-screen={route.screen}>
            <header className="ax-phonebar items-center gap-2 px-3 py-2">
              <button
                type="button"
                className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Show the sessions and screens"
                aria-expanded={drawer}
                onClick={() => setDrawer(true)}
              >
                <PanelLeft className="size-[18px]" aria-hidden />
              </button>
              <AppIcon className="size-5" />
              <span className="text-[15px] font-semibold">{CRUMBS[route.screen]}</span>
            </header>
            {route.screen === "help" ? (
              <HelpScreen />
            ) : route.screen === "session" ? (
              <SessionScreen provider={route.provider} id={route.id} back={false} />
            ) : state ? (
              route.screen === "now" ? (
                <NowScreen state={state} refresh={refresh} />
              ) : route.screen === "search" ? (
                <SearchScreen query={route.query} />
              ) : route.screen === "usage" ? (
                <UsageScreen state={state} />
              ) : route.screen === "sessions" ? (
                <SessionsScreen />
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
        </div>
      </EditorLook.Provider>
    </TooltipProvider>
  )
}

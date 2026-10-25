import { TriangleAlert } from "lucide-react"

import type { Credits, UsageRow } from "@/lib/ax"
import { ago, clock, until } from "@/lib/time"
import { cn } from "@/lib/utils"

const PROVIDERS = [
  { id: "claude", name: "Claude" },
  { id: "codex", name: "Codex" },
]
const WINDOWS: Record<string, { label: string; hint: string; order: number }> = {
  session: { label: "Session", hint: "The 5-hour window", order: 0 },
  weekly: { label: "Weekly", hint: "The 7-day window, all models", order: 1 },
  weekly_fable: { label: "Fable weekly", hint: "The 7-day window for Fable", order: 2 },
}
// On a phone every tool gets three columns, so the same window lines up across tools.
const COLUMNS = ["md:grid-cols-1", "md:grid-cols-1", "md:grid-cols-2", "md:grid-cols-3"]
const UNKNOWN: Record<string, string> = {
  unavailable: "not reported",
  stale: "stale reading",
  ambiguous: "unclear reading",
  reset_passed: "reset since last read",
}

function tone(row: UsageRow): "primary" | "warning" | "critical" {
  if ((row.used ?? 0) >= 95) return "critical"
  return (row.used ?? 0) >= 80 || row.lasts === false ? "warning" : "primary"
}

function Window({ row }: { row: UsageRow }) {
  const meta = WINDOWS[row.window] ?? { label: row.window.replace(/_/g, " "), hint: "", order: 9 }
  const level = tone(row)
  const risky = row.used !== null && row.lasts === false
  const foot =
    row.used === null
      ? (UNKNOWN[row.status] ?? row.status)
      : risky
        ? `may run out ${row.runs_out_at ? `~${clock(row.runs_out_at)}` : "before reset"}`
        : row.resets_at
          ? `resets ${until(row.resets_at)}`
          : ""
  return (
    <div className="min-w-0" title={meta.hint}>
      <div className="flex items-center justify-between gap-1.5">
        <span className="truncate text-[11.5px] text-muted-foreground">{meta.label}</span>
        {risky && <TriangleAlert className="size-3.5 shrink-0 text-warning" aria-hidden />}
      </div>
      <div className="mt-0.5 flex items-baseline gap-0.5">
        <span className={cn("figure text-[22px]", row.used === null && "text-faint")}>
          {row.used === null ? "—" : Math.round(row.used)}
        </span>
        {row.used !== null && <span className="text-xs text-muted-foreground">% used</span>}
      </div>
      <div
        className={cn(
          "mt-1.5 h-1 w-full overflow-hidden rounded-full",
          row.used === null ? "bg-muted" : level === "primary" ? "bg-primary-soft" : "bg-warning/20"
        )}
      >
        {row.used !== null && (
          <div
            className={cn(
              "h-full rounded-full",
              level === "primary" && "bg-primary",
              level === "warning" && "bg-warning",
              level === "critical" && "bg-critical"
            )}
            style={{ width: `${Math.min(100, Math.max(0, row.used))}%` }}
          />
        )}
      </div>
      <div
        className={cn(
          "mt-1 line-clamp-2 text-[11px] leading-snug",
          risky ? "text-foreground" : "text-muted-foreground"
        )}
      >
        {foot}
        {row.used !== null && row.status !== "fresh" && ` · ${UNKNOWN[row.status] ?? row.status}`}
      </div>
    </div>
  )
}

// Credits are what is left beyond the plan's windows: a balance, with no limit to fill
// toward and no reset, so no meter.
function CreditCell({ credits }: { credits: Credits }) {
  const figure = credits.unlimited
    ? "Unlimited"
    : credits.balance === null
      ? "—"
      : Math.round(credits.balance).toLocaleString()
  return (
    <div className="min-w-0" title="Credits used once the plan's windows run out">
      <div className="flex items-center justify-between gap-1.5">
        <span className="truncate text-[11.5px] text-muted-foreground">Credits</span>
      </div>
      <div className="mt-0.5 flex items-baseline gap-0.5">
        <span className={cn("figure text-[22px]", credits.balance === null && "text-faint")}>
          {figure}
        </span>
        {!credits.unlimited && credits.balance !== null && (
          <span className="text-xs text-muted-foreground">left</span>
        )}
      </div>
      <div className="mt-1.5 h-1" />
      <div className="mt-1 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
        {credits.has_credits || credits.unlimited
          ? `read ${ago(credits.observed_at)}`
          : "none left"}
        {credits.status !== "fresh" && ` · ${UNKNOWN[credits.status] ?? credits.status}`}
      </div>
    </div>
  )
}

/** Both tools' allowance, every window and Codex's credits, at the top of every screen. */
export function UsageBand({ rows, credits }: { rows: UsageRow[]; credits: Credits[] }) {
  return (
    <section
      aria-label="Usage"
      className="border-b bg-background/85 backdrop-blur-md md:sticky md:top-14 md:z-10"
    >
      <div className="mx-auto flex max-w-[1360px] flex-col gap-3 px-4 py-3 md:flex-row md:gap-8 md:px-6">
        {PROVIDERS.map((provider) => {
          const windows = rows
            .filter((r) => r.provider === provider.id)
            .sort((a, b) => (WINDOWS[a.window]?.order ?? 9) - (WINDOWS[b.window]?.order ?? 9))
          const balance = credits.filter((c) => c.provider === provider.id)
          const cells = windows.length + balance.length
          return (
            <div
              key={provider.id}
              className="flex min-w-0 gap-3"
              style={{ flexGrow: Math.max(cells, 1), flexBasis: 0 }}
            >
              <div className="w-12 shrink-0 pt-px text-[13px] font-semibold">{provider.name}</div>
              {cells ? (
                <div
                  className={cn(
                    "grid min-w-0 flex-1 grid-cols-3 gap-4",
                    COLUMNS[Math.min(cells, 3)]
                  )}
                >
                  {windows.map((row) => (
                    <Window key={row.window} row={row} />
                  ))}
                  {balance.map((c) => (
                    <CreditCell key={`credits-${c.provider}`} credits={c} />
                  ))}
                </div>
              ) : (
                <div className="pt-px text-[12px] text-muted-foreground">not reported</div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

import { Gauge } from "lucide-react"

import type { Credits, UsageRow } from "@/lib/ax"
import { ago } from "@/lib/time"
import { EVEN_PER_DAY, UNREAD, usageFoot, usagePace, usageSummary, usageTone } from "@/lib/usage"
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
const PACE_HINT = {
  tight: `Less than an even ${Math.round(EVEN_PER_DAY)}% a day left: go easy`,
  spare: `Well over an even ${Math.round(EVEN_PER_DAY)}% a day left: room to use before it resets`,
}

function Window({ row, now }: { row: UsageRow; now?: number }) {
  const meta = WINDOWS[row.window] ?? { label: row.window.replace(/_/g, " "), hint: "", order: 9 }
  const level = usageTone(row, now)
  // The colour says it; yellow means tight unless what is left is spare, and the hint on
  // hover says which.
  const pace = level === "warning" ? usagePace(row, now) : null
  const off = pace === "tight" || pace === "spare"
  const foot = row.used === null ? (UNREAD[row.status] ?? row.status) : usageFoot(row, now)
  return (
    <div className="min-w-0" title={off ? PACE_HINT[pace] : meta.hint}>
      <div className="truncate text-[11.5px] text-muted-foreground">{meta.label}</div>
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
          level === "primary" ? "text-muted-foreground" : "text-foreground"
        )}
      >
        {foot}
        {row.used !== null && row.status !== "fresh" && ` · ${UNREAD[row.status] ?? row.status}`}
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
        {credits.status !== "fresh" && ` · ${UNREAD[credits.status] ?? credits.status}`}
      </div>
    </div>
  )
}

/** Each tool's mark in the VS Code extension's icon font, the one its status bar uses. */
export const MARK: Record<string, string> = { claude: "\uE001", codex: "\uE002" }

/**
 * Both tools' allowance, every window and Codex's credits, one tool per row. Stacked, as
 * in ax's narrow VS Code panel, each tool's mark and name head its windows, which take
 * the whole width, three to a row where their labels fit and two elsewhere.
 */
export function UsageDetails({
  rows,
  credits,
  stacked = false,
  now,
}: {
  rows: UsageRow[]
  credits: Credits[]
  stacked?: boolean
  now?: number
}) {
  return (
    <section aria-label="Usage" className="flex flex-col gap-4">
      {PROVIDERS.map((provider) => {
        const windows = rows
          .filter((r) => r.provider === provider.id)
          .sort((a, b) => (WINDOWS[a.window]?.order ?? 9) - (WINDOWS[b.window]?.order ?? 9))
        const balance = credits.filter((c) => c.provider === provider.id)
        const tiles =
          windows.length + balance.length ? (
            <div
              key="tiles"
              className={cn(
                "grid min-w-0 flex-1",
                stacked ? "grid-cols-2 gap-3 @[240px]:grid-cols-3" : "grid-cols-3 gap-4"
              )}
            >
              {windows.map((row) => (
                <Window key={row.window} row={row} now={now} />
              ))}
              {balance.map((c) => (
                <CreditCell key={`credits-${c.provider}`} credits={c} />
              ))}
            </div>
          ) : (
            <div key="tiles" className="pt-px text-[12px] text-muted-foreground">
              not reported
            </div>
          )
        return stacked ? (
          <div key={provider.id} className="@container min-w-0 space-y-2">
            <div className="flex items-center gap-1.5 text-[12.5px] font-semibold">
              <span className="ax-mark text-[17px] font-normal" aria-hidden>
                {MARK[provider.id]}
              </span>
              {provider.name}
            </div>
            {tiles}
          </div>
        ) : (
          <div key={provider.id} className="flex min-w-0 gap-3">
            <div className="w-12 shrink-0 pt-px text-[13px] font-semibold">{provider.name}</div>
            {tiles}
          </div>
        )
      })}
    </section>
  )
}

const TONE = {
  primary: "text-muted-foreground",
  warning: "text-warning",
  critical: "text-critical",
}

/**
 * Usage in the bar, read at a glance: the most used window, coloured by the most urgent.
 * The details open on hover or focus on a computer, and on their own page from a phone.
 */
export function UsageIndicator({ rows, credits }: { rows: UsageRow[]; credits: Credits[] }) {
  const summary = usageSummary(rows)
  return (
    <div className="group relative">
      <a
        href="#/usage"
        aria-label={`${summary.label}; all usage`}
        className="flex h-8 items-center gap-1.5 rounded-lg px-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Gauge className={cn("size-[18px]", TONE[summary.tone])} aria-hidden />
        {summary.used !== null && (
          <span className="num hidden text-[13px] sm:inline">{Math.round(summary.used)}%</span>
        )}
      </a>
      <div className="invisible absolute top-full right-0 z-30 pt-2 opacity-0 transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 max-sm:hidden">
        <div className="w-[min(680px,calc(100vw-2rem))] rounded-xl border bg-card p-4 shadow-lg">
          <UsageDetails rows={rows} credits={credits} />
        </div>
      </div>
    </div>
  )
}

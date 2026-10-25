import { CircleAlert, CircleCheck, CircleDashed, CirclePause, TriangleAlert } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function Eyebrow({
  children,
  index,
  className,
}: {
  children: ReactNode
  index?: string
  className?: string
}) {
  return (
    <div className={cn("eyebrow flex items-center gap-2", className)}>
      {index && <span className="eyebrow-index text-faint">{index}</span>}
      <span>{children}</span>
    </div>
  )
}

export function SectionHeader({
  eyebrow,
  index,
  title,
  meta,
  actions,
  className,
}: {
  eyebrow?: string
  index?: string
  title: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-x-4 gap-y-2", className)}>
      <div className="min-w-0 space-y-1.5">
        {eyebrow && <Eyebrow index={index}>{eyebrow}</Eyebrow>}
        <h3 className="truncate text-[15px] leading-tight">{title}</h3>
      </div>
      <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
        {meta}
        {actions}
      </div>
    </div>
  )
}

export type Status = "running" | "succeeded" | "failed" | "warning" | "queued" | "paused"

const statusMeta: Record<Status, { label: string; icon: ReactNode; tone: string }> = {
  running: {
    label: "Running",
    icon: <span className="live-dot !size-1.5" />,
    tone: "bg-primary-soft text-primary-ink",
  },
  succeeded: {
    label: "Succeeded",
    icon: <CircleCheck className="text-good" />,
    tone: "bg-muted text-ink-2",
  },
  failed: {
    label: "Failed",
    icon: <CircleAlert className="text-critical" />,
    tone: "bg-critical/10 text-foreground",
  },
  warning: {
    label: "Attention",
    icon: <TriangleAlert className="text-warning" />,
    tone: "bg-warning/12 text-foreground",
  },
  queued: {
    label: "Queued",
    icon: <CircleDashed className="text-faint" />,
    tone: "bg-muted text-muted-foreground",
  },
  paused: {
    label: "Paused",
    icon: <CirclePause className="text-muted-foreground" />,
    tone: "bg-muted text-ink-2",
  },
}

/** Status always carries an icon and a word, never colour alone. */
export function StatusBadge({
  status,
  label,
  className,
}: {
  status: Status
  label?: string
  className?: string
}) {
  const meta = statusMeta[status]
  return (
    <span
      className={cn(
        "label-mono inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[11px] font-medium whitespace-nowrap [&_svg]:size-3.5",
        meta.tone,
        className
      )}
    >
      {meta.icon}
      {label ?? meta.label}
    </span>
  )
}

export function StatusIcon({ status, className }: { status: Status; className?: string }) {
  return (
    <span className={cn("inline-flex [&_svg]:size-4", className)}>{statusMeta[status].icon}</span>
  )
}

export function Sparkline({
  values,
  width = 96,
  height = 28,
  className,
}: {
  values: number[]
  width?: number
  height?: number
  className?: string
}) {
  const min = Math.min(...values)
  const max = Math.max(...values)
  const x = (i: number) => 2 + (i / (values.length - 1)) * (width - 6)
  const y = (v: number) => height - 3 - ((v - min) / (max - min || 1)) * (height - 8)
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")
  const last = values.length - 1
  return (
    <svg width={width} height={height} className={cn("overflow-visible", className)} aria-hidden>
      <path
        d={`${d}L${x(last)},${height}L${x(0)},${height}Z`}
        fill="var(--primary)"
        opacity={0.1}
      />
      <path
        d={d}
        fill="none"
        stroke="var(--primary)"
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={x(last)}
        cy={y(values[last])}
        r={4}
        fill="var(--primary)"
        stroke="var(--card)"
        strokeWidth={2}
      />
    </svg>
  )
}

export function Delta({
  value,
  goodWhenUp = true,
  period,
}: {
  value: number
  goodWhenUp?: boolean
  period: string
}) {
  const good = value >= 0 === goodWhenUp
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn("num font-medium", good ? "text-good" : "text-critical")}>
        {value >= 0 ? "▲" : "▼"} {Math.abs(value * 100).toFixed(0)}%
      </span>
      <span>{period}</span>
    </span>
  )
}

export function StatTile({
  label,
  value,
  unit,
  delta,
  trend,
  footer,
  className,
}: {
  label: string
  value: string
  unit?: string
  delta?: ReactNode
  trend?: number[]
  footer?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-3", className)}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="flex items-end justify-between gap-3">
        <div className="figure text-[28px] text-foreground">
          {value}
          {unit && (
            <span className="ml-1 text-sm font-normal tracking-normal text-muted-foreground">
              {unit}
            </span>
          )}
        </div>
        {trend && <Sparkline values={trend} className="hidden shrink-0 sm:block" />}
      </div>
      {delta}
      {footer}
    </div>
  )
}

export function Meter({
  value,
  max,
  tone = "primary",
}: {
  value: number
  max: number
  tone?: "primary" | "warning"
}) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full",
        tone === "primary" ? "bg-primary-soft" : "bg-warning/20"
      )}
    >
      <div
        className={cn("h-full rounded-full", tone === "primary" ? "bg-primary" : "bg-warning")}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

// check-colours: off. Landscape illustrations have their own palette; they
// are picture content, not interface colour.
const SCENES = [
  {
    sky: ["#f6c9a8", "#f3e3d3"],
    sun: "#fff4e0",
    ridges: ["#c79a9e", "#8f6f86", "#4d3f5c"],
    water: "#e9cdb9",
  },
  {
    sky: ["#9cc3e6", "#e4eef6"],
    sun: "#ffffff",
    ridges: ["#9fb3c8", "#6b8299", "#36485c"],
    water: "#b9cfe2",
  },
  {
    sky: ["#3b2f5e", "#c56b6b"],
    sun: "#ffd29a",
    ridges: ["#6a4c6e", "#3f2d4c", "#1f1730"],
    water: "#8a5a6d",
  },
  {
    sky: ["#0f1630", "#3d3a78"],
    sun: "#e8e6ff",
    ridges: ["#3a3f6b", "#262a4d", "#14162b"],
    water: "#2b2f5a",
  },
  {
    sky: ["#f1d7a6", "#f7ecd6"],
    sun: "#fffaf0",
    ridges: ["#d9a86c", "#b47b4a", "#7a4e30"],
    water: "#e8c995",
  },
  {
    sky: ["#b8c6d6", "#e9ecef"],
    sun: "#ffffff",
    ridges: ["#a7b0bb", "#77818f", "#454d59"],
    water: "#c9d1da",
  },
]

function hash(text: string) {
  let h = 2166136261
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619)
  return h >>> 0
}

/**
 * Generated landscape standing in for real thumbnails, so the board works
 * offline and never ships someone else's images.
 */
export function Thumb({
  seed,
  className,
}: {
  seed: string
  className?: string
  w?: number
  h?: number
}) {
  const h = hash(seed)
  const r = (n: number) => ((Math.imul(h, n * 2654435761) >>> 0) % 1000) / 1000
  const palette = SCENES[h % SCENES.length]
  const water = r(3) > 0.45
  const horizon = water ? 58 : 90
  const ridge = (i: number) => {
    const base = 30 + i * 13 + r(10 + i) * 8
    const amp = 14 - i * 3
    const pts = Array.from({ length: 17 }, (_, k) => {
      const x = k * 10
      const y =
        base -
        amp * Math.abs(Math.sin(k * (0.45 + r(20 + i) * 0.5) + r(30 + i) * 6)) -
        r(40 + k + i * 17) * 4
      return `${x},${Math.min(y, horizon).toFixed(1)}`
    })
    return `0,${horizon} ${pts.join(" ")} 160,${horizon}`
  }
  const id = `s${h.toString(36)}`
  return (
    <div className={cn("relative overflow-hidden bg-muted", className)}>
      <svg
        viewBox="0 0 160 90"
        preserveAspectRatio="xMidYMid slice"
        className="absolute inset-0 size-full"
        aria-hidden
      >
        <defs>
          <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={palette.sky[0]} />
            <stop offset="1" stopColor={palette.sky[1]} />
          </linearGradient>
          <linearGradient id={`${id}-water`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={palette.water} />
            <stop offset="1" stopColor={palette.ridges[2]} />
          </linearGradient>
        </defs>
        <rect width="160" height="90" fill={`url(#${id}-sky)`} />
        <circle
          cx={30 + r(5) * 100}
          cy={14 + r(6) * 18}
          r={6 + r(7) * 6}
          fill={palette.sun}
          opacity={0.85}
        />
        {[0, 1, 2].map((i) => (
          <polygon key={i} points={ridge(i)} fill={palette.ridges[i]} />
        ))}
        {water && (
          <>
            <rect y={horizon} width="160" height={90 - horizon} fill={`url(#${id}-water)`} />
            {[0, 1, 2, 3].map((k) => (
              <rect
                key={k}
                x={20 + r(50 + k) * 100}
                y={horizon + 4 + k * 6}
                width={14 + r(60 + k) * 24}
                height="0.8"
                fill="#fff"
                opacity="0.35"
              />
            ))}
          </>
        )}
      </svg>
    </div>
  )
}

// check-colours: on

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={cn("size-5", className)} aria-hidden>
      <rect x="1" y="1" width="8" height="8" rx="2" fill="var(--primary)" />
      <rect x="11" y="1" width="8" height="8" rx="4" fill="var(--primary)" opacity="0.45" />
      <rect x="1" y="11" width="8" height="8" rx="4" fill="var(--primary)" opacity="0.45" />
      <rect x="11" y="11" width="8" height="8" rx="2" fill="var(--foreground)" opacity="0.85" />
    </svg>
  )
}

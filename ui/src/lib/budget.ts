// How a budget reads on the Now screen: its figures in words, its bar, and its colour.

type Figures = {
  spent: number
  reserved: number
  cap: number
  left: number
  unit: string
  state: string
}

const FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 })

/** 43 -> "43", 12.5 -> "12.5", 62431.25 -> "62,431.25". */
export function amount(value: number): string {
  return FORMAT.format(value)
}

/** "12.5 of 40 usd · 5 reserved · 22.5 left", or "· 3 over" past the limit. */
export function budgetSummary(b: Figures): string {
  const parts = [`${amount(b.spent)} of ${amount(b.cap)} ${b.unit}`]
  if (b.reserved) parts.push(`${amount(b.reserved)} reserved`)
  parts.push(b.left < 0 ? `${amount(-b.left)} over` : `${amount(b.left)} left`)
  return parts.join(" · ")
}

/** Spent and reserved as percentages of the bar: of the limit, or of what was committed
 * once that is past the limit. */
export function budgetBar(b: Figures): { spent: number; reserved: number } {
  const scale = Math.max(b.cap, b.spent + b.reserved) || 1
  return { spent: (b.spent / scale) * 100, reserved: (b.reserved / scale) * 100 }
}

export function budgetTone(b: Figures): "primary" | "warning" | "critical" {
  if (b.state === "over") return "critical"
  return b.state === "near" ? "warning" : "primary"
}

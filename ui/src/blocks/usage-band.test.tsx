import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { UsageDetails } from "@/blocks/usage-band"
import type { Credits, UsageRow } from "@/lib/ax"

const NOW = Date.parse("2026-10-27T12:00:00Z")

const row = (r: Pick<UsageRow, "provider" | "window"> & Partial<UsageRow>): UsageRow => ({
  used: null,
  status: "fresh",
  resets_at: null,
  lasts: null,
  projected_high: null,
  runs_out_at: null,
  ...r,
})

const credits: Credits = {
  provider: "codex",
  balance: 1234.4,
  unlimited: false,
  has_credits: true,
  observed_at: "2026-10-27T11:50:00Z",
  status: "fresh",
}

const panel = (rows: UsageRow[], given: Credits[] = []) =>
  renderToStaticMarkup(<UsageDetails rows={rows} credits={given} now={NOW} stacked />)

describe("usage in ax's panel", () => {
  it("heads each tool's windows with its mark and name, in order", () => {
    const out = panel([
      row({ provider: "claude", window: "weekly", used: 22, resets_at: "2026-11-01T12:00:00Z" }),
      row({ provider: "claude", window: "session", used: 45, resets_at: "2026-10-27T14:00:00Z" }),
    ])
    expect(out).toMatch(/class="ax-mark[^"]*"[^>]*>\uE001<\/span>Claude</)
    expect(out.indexOf("Session")).toBeLessThan(out.indexOf("Weekly"))
    expect(out).toContain(">45<")
    expect(out).toContain(">22<")
  })

  it("keeps what each window leaves you in view, not only on hover", () => {
    const out = panel([
      row({ provider: "claude", window: "session", used: 45, resets_at: "2026-10-27T14:00:00Z" }),
      row({ provider: "claude", window: "weekly", used: 22, resets_at: "2026-11-01T12:00:00Z" }),
    ])
    expect(out).toContain(">resets in 2 h 0 min<")
    expect(out).toContain(">16% a day for 5 days<")
  })

  it("colours a window running tight, and says why only on hover", () => {
    const out = panel([
      row({ provider: "claude", window: "weekly", used: 80, resets_at: "2026-10-31T12:00:00Z" }),
    ])
    expect(out).toContain('title="Less than an even 14% a day left: go easy"') // on hover
    expect(out).toContain("bg-warning") // the colour says it
    expect(out).not.toContain("<svg") // no icon besides
  })

  it("marks a window it can't read, and shows Codex's credits", () => {
    const out = panel([row({ provider: "claude", window: "weekly", status: "stale" })], [credits])
    expect(out).toContain("—")
    expect(out).toContain("stale reading")
    expect(out).toContain(">1,234<")
    expect(out).toContain("read ")
  })
})

describe("usage on the web page", () => {
  it("names each tool beside its windows, without the editor's marks", () => {
    const out = renderToStaticMarkup(
      <UsageDetails rows={[row({ provider: "codex", window: "weekly", used: 31 })]} credits={[]} />
    )
    expect(out).toContain("Codex")
    expect(out).not.toContain("ax-mark")
  })
})

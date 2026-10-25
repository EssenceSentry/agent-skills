import { describe, expect, it } from "vitest"

import { amount, budgetBar, budgetSummary, budgetTone } from "@/lib/budget"

const budget = (spent: number, reserved: number, cap: number, state = "ok") => ({
  spent,
  reserved,
  cap,
  left: cap - spent - reserved,
  unit: "usd",
  state,
})

describe("amount", () => {
  it("drops trailing zeros and groups thousands", () => {
    expect(amount(43)).toBe("43")
    expect(amount(12.5)).toBe("12.5")
    expect(amount(0.0015)).toBe("0.0015")
    expect(amount(62431.25)).toBe("62,431.25")
  })
})

describe("budgetSummary", () => {
  it("says what is spent, held and left", () => {
    expect(budgetSummary(budget(12.5, 5, 40))).toBe("12.5 of 40 usd · 5 reserved · 22.5 left")
    expect(budgetSummary(budget(10, 0, 40))).toBe("10 of 40 usd · 30 left")
  })

  it("says how far over a budget went", () => {
    expect(budgetSummary(budget(43, 0, 40, "over"))).toBe("43 of 40 usd · 3 over")
    expect(budgetSummary(budget(38, 5, 40, "over"))).toBe("38 of 40 usd · 5 reserved · 3 over")
  })
})

describe("budgetBar", () => {
  it("gives the spent and reserved shares of the limit", () => {
    expect(budgetBar(budget(10, 10, 40))).toEqual({ spent: 25, reserved: 25 })
  })

  it("scales to what was committed when it is over, so the bar stays full width", () => {
    expect(budgetBar(budget(40, 10, 40, "over"))).toEqual({ spent: 80, reserved: 20 })
  })
})

describe("budgetTone", () => {
  it("colours like the usage band: yellow near the limit, red over it", () => {
    expect(budgetTone(budget(10, 0, 40))).toBe("primary")
    expect(budgetTone(budget(33, 0, 40, "near"))).toBe("warning")
    expect(budgetTone(budget(43, 0, 40, "over"))).toBe("critical")
  })
})

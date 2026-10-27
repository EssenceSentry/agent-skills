import { describe, expect, it } from "vitest"

import { mathDelimiters } from "@/lib/math"

describe("the math delimiters agents write", () => {
  it("turns \\[ … \\] into a display block", () => {
    expect(mathDelimiters("The loss is\n\\[ L = -\\sum_i y_i \\log p_i \\]\nfor each batch.")).toBe(
      "The loss is\n\n$$\nL = -\\sum_i y_i \\log p_i\n$$\n\nfor each batch."
    )
  })

  it("keeps a display block that spans lines", () => {
    expect(mathDelimiters("\\[\na &= b \\\\\nc &= d\n\\]")).toBe("\n$$\na &= b \\\\\nc &= d\n$$\n")
  })

  it("turns \\( … \\) into inline math", () => {
    expect(mathDelimiters("with \\(p < 0.05\\) and \\( n = 40 \\).")).toBe(
      "with $$p < 0.05$$ and $$n = 40$$."
    )
  })

  it("leaves code, dollar amounts and $$ math alone", () => {
    const code = "Run `echo \\(x\\)` and\n```tex\n\\[ x \\]\n```\n"
    expect(mathDelimiters(code)).toBe(code)
    expect(mathDelimiters("It costs $5 and $10.")).toBe("It costs $5 and $10.")
    expect(mathDelimiters("Already $$x^2$$ here.")).toBe("Already $$x^2$$ here.")
  })
})

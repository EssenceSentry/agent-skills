import { describe, expect, it } from "vitest"

import {
  effortLabel,
  goalLine,
  modelChoice,
  type Reference,
  referenceLabel,
  withReferences,
} from "@/lib/plus"
import type { ChatState } from "@/lib/sessions"

const file: Reference = { kind: "file", path: "/repo/src/a.ts" }
const folder: Reference = { kind: "folder", path: "/repo/docs" }
const picked: Reference = {
  kind: "selection",
  path: "/repo/src/b.py",
  start: 12,
  end: 14,
  text: "def f():\n    return 1\n",
  language: "python",
}

describe("references sent with a message", () => {
  it("lists files and folders after the words", () => {
    expect(withReferences("Look at these", [file, folder])).toBe(
      "Look at these\n\nFiles:\n- `/repo/src/a.ts`\n- `/repo/docs/`"
    )
  })

  it("sends a selection as a fenced block with where it comes from", () => {
    expect(withReferences("Why is this slow?", [picked])).toBe(
      "Why is this slow?\n\nSelected in `/repo/src/b.py`, lines 12–14:\n```python\ndef f():\n    return 1\n```"
    )
  })

  it("sends the references alone when there are no words, and the words alone without them", () => {
    expect(withReferences("  ", [file])).toBe("Files:\n- `/repo/src/a.ts`")
    expect(withReferences("Just words", [])).toBe("Just words")
  })

  it("labels each one briefly", () => {
    expect([file, folder, picked].map(referenceLabel)).toEqual(["a.ts", "docs/", "b.py:12–14"])
    expect(referenceLabel({ ...picked, start: 3, end: 3 })).toBe("b.py:3")
  })
})

function chat(over: Partial<ChatState>): ChatState {
  return {
    holder: "ax",
    can_send: true,
    take_over: false,
    pending: false,
    busy: false,
    partial: "",
    approval: null,
    error: null,
    note: "",
    settings: { plan: false, auto: false, model: null, effort: null },
    models: [],
    goal: null,
    ...over,
  }
}

const codexModels = [
  {
    id: "gpt-6-astra",
    label: "GPT-6-Astra",
    efforts: ["low", "medium", "xhigh"],
    default_effort: "medium",
  },
  { id: "gpt-6-sol", label: "GPT-6-Sol", efforts: ["low", "high"], default_effort: "low" },
]

describe("the model picker", () => {
  it("names the model and effort the session runs", () => {
    const choice = modelChoice(
      chat({
        models: codexModels,
        settings: { plan: false, auto: true, model: "gpt-6-astra", effort: "xhigh" },
      })
    )
    expect(choice).toEqual({
      label: "GPT-6-Astra · Extra high",
      model: "gpt-6-astra",
      effort: "xhigh",
      efforts: ["low", "medium", "xhigh"],
    })
  })

  it("names the default model while the session runs its own", () => {
    const choice = modelChoice(
      chat({
        models: [
          {
            id: "default",
            label: "Default (recommended)",
            efforts: ["low", "high"],
            default_effort: null,
          },
        ],
      })
    )
    expect(choice?.label).toBe("Default (recommended)")
    expect(choice?.efforts).toEqual(["low", "high"])
  })

  it("shows nothing before the session reports its models", () => {
    expect(modelChoice(chat({ models: [] }))).toBeNull()
    expect(modelChoice(chat({ settings: null, models: codexModels }))).toBeNull()
  })
})

describe("efforts by name", () => {
  it("names each effort as people say it", () => {
    expect(["minimal", "low", "medium", "high", "xhigh", "max"].map(effortLabel)).toEqual([
      "Minimal",
      "Low",
      "Medium",
      "High",
      "Extra high",
      "Max",
    ])
    expect(effortLabel("turbo")).toBe("turbo")
  })
})

describe("the goal line", () => {
  it("says the status, the time and the tokens", () => {
    expect(
      goalLine({
        objective: "ship",
        status: "active",
        tokens_used: 1200,
        token_budget: 50000,
        seconds: 95,
      })
    ).toBe("Active · 1 min · 1.2k of 50k tokens")
    expect(
      goalLine({
        objective: "ship",
        status: "budgetLimited",
        tokens_used: 50000,
        token_budget: 50000,
        seconds: 4000,
      })
    ).toBe("Budget reached · 1 h 6 min · 50k of 50k tokens")
  })

  it("says only that it is set when the tool reports nothing more", () => {
    expect(
      goalLine({
        objective: "ship",
        status: "set",
        tokens_used: null,
        token_budget: null,
        seconds: null,
      })
    ).toBe("Set")
  })
})

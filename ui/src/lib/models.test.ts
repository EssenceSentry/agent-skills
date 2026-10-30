import { describe, expect, it } from "vitest"

import {
  choose,
  chosen,
  featured,
  type ModelGroup,
  type ModelOffer,
  modelName,
  shownName,
  startingPick,
} from "@/lib/models"

const groups: ModelGroup[] = [
  {
    provider: "claude",
    label: "Claude Code",
    models: [
      {
        id: "default",
        label: "Default (recommended)",
        description: "Opus 5.5 · Best for everyday, complex tasks",
        default: true,
        efforts: ["low", "medium", "high", "xhigh", "max"],
        default_effort: null,
      },
      {
        id: "opus",
        label: "Opus 5.5",
        description: "",
        default: false,
        efforts: ["low", "medium", "high", "xhigh", "max"],
        default_effort: null,
      },
      {
        id: "claude-haiku-4-5",
        label: "Haiku 4.5",
        description: "",
        default: false,
        efforts: [],
        default_effort: null,
      },
    ],
  },
  {
    provider: "codex",
    label: "Codex",
    models: [
      {
        id: "gpt-6.1-sol",
        label: "GPT-6.1-Sol",
        description: "Latest workhorse",
        default: true,
        efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
        default_effort: "low",
      },
      {
        id: "gpt-6-astra",
        label: "GPT-6-Astra",
        description: "Frontier intelligence",
        default: false,
        efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
        default_effort: "medium",
      },
    ],
  },
]

describe("the model and effort a session runs on", () => {
  it("names models as Codex does", () => {
    expect(modelName("GPT-6.1-Sol")).toBe("GPT-6.1 Sol")
    expect(modelName("GPT-6-Astra")).toBe("GPT-6 Astra")
    expect(modelName("Default (recommended)")).toBe("Default")
    expect(modelName("Opus 5.5")).toBe("Opus 5.5")
  })

  it("names the model behind Claude's default by what it runs", () => {
    const [claudeDefault, opus] = groups[0].models
    expect(shownName(claudeDefault)).toBe("Opus 5.5")
    expect(shownName(opus)).toBe("Opus 5.5")
    expect(shownName({ ...claudeDefault, description: "" })).toBe("Default")
  })

  it("reads a choice left to the tool as its default model, at its default effort", () => {
    expect(chosen(groups, { provider: "claude", model: null, effort: null })).toMatchObject({
      model: { id: "default" },
      effort: null,
    })
    expect(chosen(groups, { provider: "codex", model: null, effort: null })).toMatchObject({
      model: { id: "gpt-6.1-sol" },
      effort: "low",
    })
    expect(
      chosen(groups, { provider: "codex", model: "gpt-6-astra", effort: "xhigh" })
    ).toMatchObject({ model: { id: "gpt-6-astra" }, effort: "xhigh" })
  })

  it("moves between the tools, keeping the effort where the new model has it", () => {
    const astra = { provider: "codex" as const, model: "gpt-6-astra", effort: "xhigh" }
    expect(choose(groups, astra, "claude", "opus")).toEqual({
      provider: "claude",
      model: "opus",
      effort: "xhigh",
    })
    expect(choose(groups, { ...astra, effort: "ultra" }, "claude", "opus")).toEqual({
      provider: "claude",
      model: "opus",
      effort: null,
    })
    expect(choose(groups, astra, "claude", "claude-haiku-4-5").effort).toBeNull()
    // The default entry is the tool's own choice, so nothing is pinned.
    expect(choose(groups, astra, "claude", "default")).toEqual({
      provider: "claude",
      model: null,
      effort: "xhigh",
    })
  })
})

const offer = (id: string, label: string): ModelOffer => ({
  id,
  label,
  efforts: ["low", "high"],
  default_effort: null,
})

describe("the models each tool shows first", () => {
  // As the tools list them on 2026-10-27.
  const claude = [
    offer("default", "Default (recommended)"),
    offer("opus", "Opus 5.5"),
    offer("fable", "Fable 5.1"),
    offer("sonnet", "Sonnet 5.5"),
    offer("haiku", "Haiku 5.5"),
    offer("claude-haiku-4-5-20251001", "Haiku 4.5"),
    offer("claude-sonnet-5", "Sonnet 5"),
    offer("claude-opus-5", "Opus 5"),
    offer("claude-fable-5", "Fable 5"),
    offer("claude-opus-4-8", "Opus 4.8"),
  ]
  const codex = [
    offer("gpt-6.1-sol", "GPT-6.1-Sol"),
    offer("gpt-6-astra", "GPT-6-Astra"),
    offer("gpt-6.1-terra", "GPT-6.1 Terra"),
    offer("gpt-6-sol", "GPT-6-Sol"),
    offer("gpt-6-luna", "GPT-6-Luna"),
    offer("gpt-5.6-sol", "GPT-5.6-Sol"),
  ]

  it("are the latest Opus and Fable for Claude, the latest Sol and Astra for Codex", () => {
    expect(featured("claude", claude).map((m) => m.id)).toEqual(["opus", "fable"])
    expect(featured("codex", codex).map((m) => m.id)).toEqual(["gpt-6.1-sol", "gpt-6-astra"])
  })

  it("follow new versions without being told", () => {
    const later = [
      ...claude,
      offer("claude-opus-6", "Opus 6"),
      offer("claude-fable-5-2", "Fable 5.2"),
    ]
    expect(featured("claude", later).map((m) => m.label)).toEqual(["Opus 6", "Fable 5.2"])
    const older = [offer("gpt-6-sol", "GPT-6-Sol"), offer("gpt-6.2-sol", "GPT-6.2-Sol")]
    expect(featured("codex", older).map((m) => m.id)).toEqual(["gpt-6.2-sol"])
  })

  it("leave out a family the tool doesn't offer", () => {
    expect(featured("claude", [offer("opus", "Opus 5.5")]).map((m) => m.id)).toEqual(["opus"])
    expect(featured("codex", [])).toEqual([])
  })
})

describe("the model a new session starts on", () => {
  it("is Claude's latest featured model, once the lists arrive", () => {
    expect(startingPick(groups)).toEqual({ provider: "claude", model: "opus", effort: null })
    expect(startingPick([])).toEqual({ provider: "claude", model: null, effort: null })
  })
})

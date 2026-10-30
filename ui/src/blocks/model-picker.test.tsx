import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { ModelEffortPicker, ModelPanel } from "@/blocks/model-picker"
import type { ModelGroup } from "@/lib/models"

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
        default: false,
        efforts: ["low", "medium", "high", "xhigh", "max"],
        default_effort: null,
      },
    ],
  },
  {
    provider: "codex",
    label: "Codex",
    models: [
      {
        id: "gpt-6-astra",
        label: "GPT-6-Astra",
        default: true,
        efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
        default_effort: "medium",
      },
    ],
  },
]
const astra = { provider: "codex" as const, model: "gpt-6-astra", effort: "xhigh" }
const none = () => undefined

describe("the model picker, as Codex draws it", () => {
  it("shows the model and its effort on the button", () => {
    const out = renderToStaticMarkup(
      <ModelEffortPicker groups={groups} pick={astra} onPick={none} />
    )
    expect(out).toContain("GPT-6 Astra")
    expect(out).toContain("Extra high")
  })

  it("sets the effort on a slider under the effort's name and the model's", () => {
    const out = renderToStaticMarkup(
      <ModelPanel groups={groups} pick={astra} onPick={none} view="effort" onView={none} />
    )
    expect(out).toContain("Extra high")
    expect(out).toContain("GPT-6 Astra")
    expect(out).toContain('type="range"')
    expect(out).toContain('max="5"')
    expect(out).toContain('value="3"')
    expect(out.match(/chat-slider-tick/g)).toHaveLength(6)
    expect(out).toContain('aria-label="Reset to default"')
  })

  it("names the model's default effort as the default when none is chosen", () => {
    const out = renderToStaticMarkup(
      <ModelPanel
        groups={groups}
        pick={{ ...astra, effort: null }}
        onPick={none}
        view="effort"
        onView={none}
      />
    )
    expect(out).toContain("Medium · default")
    expect(out).toContain('value="1"')
    expect(out).toContain("chat-slider-thumb")
  })

  it("says the tool picks the effort when it doesn't say which is its default", () => {
    const opus = {
      provider: "claude" as const,
      model: groups[0]?.models[0]?.id ?? "",
      effort: null,
    }
    const out = renderToStaticMarkup(
      <ModelPanel groups={groups} pick={opus} onPick={none} view="effort" onView={none} />
    )
    expect(out).toContain("Default effort")
    expect(out).toContain("Claude Code picks its own until you choose one")
  })

  it("shows each tool's latest models first, the rest behind more, the chosen one checked", () => {
    const out = renderToStaticMarkup(
      <ModelPanel groups={groups} pick={astra} onPick={none} view="models" onView={none} />
    )
    expect(out).toContain("Select model")
    expect(out).toContain("Claude Code")
    expect(out).toContain("Codex")
    expect(out).toContain("Opus 5.5")
    expect(out).not.toContain("Best for everyday") // the Default entry waits behind more
    expect(out).toContain("Show 1 more")
    expect(out).toMatch(/aria-checked="true"[^>]*>.*?GPT-6 Astra/s)
  })

  it("lists all of a tool's models once more is open", () => {
    const out = renderToStaticMarkup(
      <ModelPanel
        groups={groups}
        pick={astra}
        onPick={none}
        view="models"
        onView={none}
        more={["claude"]}
      />
    )
    expect(out).toContain("Default")
    expect(out).toContain("Opus 5.5 · Best for everyday, complex tasks")
    expect(out).toContain("Show fewer")
  })

  it("lists one tool's models without naming the tool, in a session that has one", () => {
    const out = renderToStaticMarkup(
      <ModelPanel groups={[groups[1]]} pick={astra} onPick={none} view="models" onView={none} />
    )
    expect(out).not.toContain("Claude Code")
    expect(out).toMatch(/<legend class="[^"]*sr-only[^"]*">Codex</) // named for screen readers only
  })
})

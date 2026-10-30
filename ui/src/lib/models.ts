/** The models each tool offers, and the one a session runs on, with its effort. */

import type { Provider } from "@/lib/sessions"

export type ModelOffer = {
  id: string
  label: string
  description?: string
  /** The tool's own pick: Claude's "Default" entry, Codex's default model. */
  default?: boolean
  efforts: string[]
  default_effort: string | null
}

export type ModelGroup = { provider: Provider; label: string; models: ModelOffer[] }

/** A model and effort chosen; null leaves either to the tool. */
export type ModelPick = { provider: Provider; model: string | null; effort: string | null }

/** A model's name as Codex writes it: "GPT-6.1 Sol", and Claude's "Default" without "(recommended)". */
export function modelName(label: string): string {
  return label.replace(/(\d)-(?=[A-Za-z])/g, "$1 ").replace(/\s*\(recommended\)$/i, "")
}

/** The name to show for a model: what Claude's "Default" runs, as its description begins. */
export function shownName(model: ModelOffer): string {
  const runs = model.default ? model.description?.split(" · ")[0]?.trim() : ""
  return runs && /^default/i.test(model.label) ? runs : modelName(model.label)
}

/** What a pick runs on: the model named, else the tool's default one, and its effort. */
export function chosen(groups: ModelGroup[], pick: ModelPick) {
  const group = groups.find((g) => g.provider === pick.provider)
  const models = group?.models ?? []
  const model =
    models.find((m) => m.id === pick.model) ?? models.find((m) => m.default) ?? models[0] ?? null
  const effort = pick.effort ?? model?.default_effort ?? null
  return { group: group ?? null, model, effort }
}

/** A model picked from any tool's list: the effort carries over when the model has it. */
export function choose(
  groups: ModelGroup[],
  pick: ModelPick,
  provider: Provider,
  id: string
): ModelPick {
  const model = groups.find((g) => g.provider === provider)?.models.find((m) => m.id === id)
  const keeps = pick.effort !== null && (model?.efforts.includes(pick.effort) ?? false)
  // Claude's "Default" entry is no pin at all: the tool chooses.
  const pinned = model?.default && provider === "claude" ? null : id
  return { provider, model: pinned, effort: keeps ? pick.effort : null }
}

/** The efforts past which Codex colours the choice as its most. */
export const isMaximum = (effort: string | null) => effort === "max" || effort === "ultra"

/** The model families each tool shows first, in this order; the rest wait behind "more". */
export const FEATURED: Record<Provider, string[]> = {
  claude: ["Opus", "Fable"],
  codex: ["Sol", "Astra"],
}

/** A model's version from its name, as numbers to compare: "GPT-6.1-Sol" → [6, 1]. */
function version(label: string): number[] {
  return (label.match(/\d+(?:\.\d+)*/)?.[0] ?? "").split(".").filter(Boolean).map(Number)
}

function newer(a: number[], b: number[]): number {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0)
    if (d) return d
  }
  return 0
}

/** The latest model of each featured family the tool offers; the first listed wins a tie. */
export function featured(provider: Provider, models: ModelOffer[]): ModelOffer[] {
  return FEATURED[provider].flatMap((family) => {
    const named = new RegExp(`\\b${family}\\b`, "i")
    const mine = models.filter((m) => named.test(modelName(m.label)))
    const latest = mine.reduce<ModelOffer | null>(
      (best, m) => (best && newer(version(m.label), version(best.label)) <= 0 ? best : m),
      null
    )
    return latest ? [latest] : []
  })
}

/** What a new session starts on: Claude's first featured model, at its default effort. */
export function startingPick(groups: ModelGroup[]): ModelPick {
  const claude =
    groups.find((g) => g.provider === "claude" && g.models.length) ??
    groups.find((g) => g.models.length)
  const first = claude
    ? (featured(claude.provider, claude.models)[0] ?? claude.models[0])
    : undefined
  return { provider: claude?.provider ?? "claude", model: first?.id ?? null, effort: null }
}

// What the search screen groups ax find's hits by.

export type Hit = {
  source: string
  path: string
  title: string
  snippet: string
  note?: string | null
  handle?: string
  provider?: string
  project?: string | null
  date?: string
  line?: number | null
}

export const KINDS = [
  { kind: "conversation", label: "Conversations", one: "Conversation" },
  { kind: "note", label: "Notes", one: "Note" },
  { kind: "memory", label: "Memories", one: "Memory" },
  { kind: "doc", label: "Docs", one: "Doc" },
  { kind: "code", label: "Code", one: "Code" },
  { kind: "subagent", label: "Subagents", one: "Subagent" },
] as const

/** Each kind present in the hits with its count, in the chips' order. */
export function kindCounts(hits: { source: string }[]) {
  return KINDS.map(({ kind, label }) => ({
    kind,
    label,
    count: hits.filter((h) => h.source === kind).length,
  })).filter((k) => k.count > 0)
}

export function ofKind<T extends { source: string }>(hits: T[], kind: string | null): T[] {
  return kind ? hits.filter((h) => h.source === kind) : hits
}

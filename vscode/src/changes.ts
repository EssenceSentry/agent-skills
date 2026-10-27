/** Helpers for showing what a session changed in VS Code's diff view. */

export type Base = "turn" | "commit"
export type BeforeSide = { provider: "claude" | "codex"; id: string; base: Base }
export type Before = { exists: boolean; text: string }

/** The query of an `ax-before:` address, the left side of a diff: whose file, before what. */
export function beforeQuery(side: BeforeSide): string {
  return new URLSearchParams(side).toString()
}

export function readBeforeQuery(query: string): BeforeSide | null {
  const found = new URLSearchParams(query)
  const provider = found.get("provider")
  const id = found.get("id")
  const base = found.get("base")
  if ((provider !== "claude" && provider !== "codex") || !id) return null
  if (base !== "turn" && base !== "commit") return null
  return { provider, id, base }
}

/** Whether a file differs from how it was: changed, added or removed. */
export function changed(before: Before, now: string | null): boolean {
  if (!before.exists) return now !== null
  return now === null || now !== before.text
}

export function changesTitle(name: string, base: Base, count: number): string {
  const files = count === 1 ? "1 file" : `${count} files`
  return `${name}: ${files} changed ${base === "turn" ? "this turn" : "since the last commit"}`
}

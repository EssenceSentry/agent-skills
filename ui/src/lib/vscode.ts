import { PROVIDERS, type Provider } from "@/lib/sessions"

/** What a VS Code tab shows, as the extension wrote it on the page's body. */
export type TabView =
  | { screen: "session"; provider: Provider; id: string; server: string }
  | { screen: "new"; folders: string[]; server: string }

/** VS Code marks its theme on the body; high contrast counts as dark unless it says light. */
export function themeFor(classes: string): "light" | "dark" {
  const kinds = classes.split(/\s+/)
  if (kinds.includes("vscode-light") || kinds.includes("vscode-high-contrast-light")) return "light"
  if (kinds.includes("vscode-dark") || kinds.includes("vscode-high-contrast")) return "dark"
  return "light"
}

function folders(json: string | undefined): string[] {
  try {
    const parsed: unknown = JSON.parse(json ?? "[]")
    return Array.isArray(parsed) ? parsed.filter((f): f is string => typeof f === "string") : []
  } catch {
    return []
  }
}

export function viewFrom(data: Record<string, string | undefined>): TabView | null {
  const { screen, provider, id, server } = data
  if (!server) return null
  if (screen === "new") return { screen, folders: folders(data.folders), server }
  const known = PROVIDERS.find((p) => p.provider === provider)?.provider
  if (screen === "session" && known && id) return { screen, provider: known, id, server }
  return null
}

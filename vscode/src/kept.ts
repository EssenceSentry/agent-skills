/**
 * A session tab VS Code kept from before a reload. VS Code restores such a webview only
 * when it is first shown, so until then the extension doesn't know it; found by its
 * session's name, it can be shown instead of opening the session a second time.
 */

export type TabLike = { viewType?: string; label: string }
export type GroupLike = { viewColumn: number; tabs: readonly TabLike[] }

/** Where ax's tab named after the session sits: its group's column and its place in it. */
export function keptTab(
  groups: readonly GroupLike[],
  name: string
): { viewColumn: number; index: number } | null {
  for (const group of groups) {
    const index = group.tabs.findIndex(
      (tab) => tab.viewType?.endsWith("ax.session") && tab.label === name
    )
    if (index >= 0) return { viewColumn: group.viewColumn, index }
  }
  return null
}

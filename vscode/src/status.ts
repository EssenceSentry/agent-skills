import * as vscode from "vscode"

import { call } from "./bridge"
import { type Credits, type UsageRow, usageStatus } from "./usage"

/** Usage in the status bar: the gauge's figure and colour, every window on hover. */
export class UsageBar {
  private readonly item = vscode.window.createStatusBarItem(
    "ax.usage",
    vscode.StatusBarAlignment.Right,
    100
  )

  constructor(private readonly server: () => string) {
    this.item.name = "ax usage"
    this.item.command = "ax.openUsage"
  }

  async refresh() {
    const answer = await call(this.server(), "GET", "/api/usage")
    if (answer.status !== 200) return this.item.hide()
    const { usage, credits } = answer.body as { usage: UsageRow[]; credits: Credits[] }
    const shown = usageStatus(usage, credits)
    this.item.text = shown.text
    this.item.backgroundColor = shown.background
      ? new vscode.ThemeColor(shown.background)
      : undefined
    const tooltip = new vscode.MarkdownString(shown.tooltip.join("  \n"))
    tooltip.appendMarkdown("\n\n---\n\nClick for the details in the ax app.")
    this.item.tooltip = tooltip
    this.item.show()
  }

  dispose() {
    this.item.dispose()
  }
}

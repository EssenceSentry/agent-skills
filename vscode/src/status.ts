import * as vscode from "vscode"

import { call } from "./bridge"
import { type Credits, offlineStatus, type UsageRow, usageStatus } from "./usage"

/** Usage in the status bar: each tool's week, every window on hover, and a click opens
 * ax's panel, which shows usage above the sessions. */
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
    if (answer.status !== 200) {
      const offline = offlineStatus(this.server())
      this.item.text = offline.text
      this.item.tooltip = offline.tooltip
      return this.item.show()
    }
    const { usage, credits } = answer.body as { usage: UsageRow[]; credits: Credits[] }
    const shown = usageStatus(usage, credits)
    this.item.text = shown.text
    const tooltip = new vscode.MarkdownString(shown.tooltip, true)
    tooltip.supportHtml = true // the lighter, smaller reset times
    this.item.tooltip = tooltip
    this.item.show()
  }

  dispose() {
    this.item.dispose()
  }
}

/** While ax is shared, a mark in the status bar saying so, since the link reaches every
 * session; a click copies the link or stops sharing. */
export class SharedBar {
  private readonly item = vscode.window.createStatusBarItem(
    "ax.shared",
    vscode.StatusBarAlignment.Right,
    101
  )

  constructor() {
    this.item.name = "ax shared"
    this.item.text = "$(radio-tower) Shared"
    this.item.tooltip =
      "ax is shared through Cloudflare: whoever holds the link sees and can write to every session. Click to copy the link or stop sharing."
    this.item.command = "ax.sharing"
  }

  show(shared: boolean) {
    if (shared) this.item.show()
    else this.item.hide()
  }

  dispose() {
    this.item.dispose()
  }
}

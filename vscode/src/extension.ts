import { randomBytes } from "node:crypto"
import * as vscode from "vscode"

import { type BridgeRequest, forward, linkTarget } from "./bridge"
import { pageHtml, type View } from "./html"
import { type Listing, sessionTree, type TreeNode, waitingCount } from "./tree"

const server = () =>
  vscode.workspace.getConfiguration("ax").get<string>("server", "http://127.0.0.1:8765")

const isProvider = (value: unknown): value is "claude" | "codex" =>
  value === "claude" || value === "codex"

/** The sidebar: every live session, read from ax every few seconds. */
class SessionsTree implements vscode.TreeDataProvider<TreeNode> {
  private nodes: TreeNode[] = []
  private readonly changed = new vscode.EventEmitter<undefined>()
  readonly onDidChangeTreeData = this.changed.event

  /** The latest listing, or null while ax doesn't answer. */
  async read(): Promise<Listing | null> {
    const reply = await forward(server(), {
      type: "request",
      id: 0,
      method: "GET",
      path: "/api/sessions",
    })
    const listing = reply.status === 200 ? (reply.body as Listing) : null
    const error = (reply.body as { error?: string } | null)?.error ?? `ax answered ${reply.status}`
    this.nodes = sessionTree(listing ?? { error }, Date.now())
    this.changed.fire(undefined)
    return listing
  }

  getChildren(node?: TreeNode): TreeNode[] {
    if (!node) return this.nodes
    return node.kind === "group" ? node.children : []
  }

  getTreeItem(node: TreeNode): vscode.TreeItem {
    const { Expanded, None } = vscode.TreeItemCollapsibleState
    const item = new vscode.TreeItem(node.label, node.kind === "group" ? Expanded : None)
    item.id = node.key
    if (node.kind === "group") {
      item.description = node.description
      return item
    }
    item.iconPath = new vscode.ThemeIcon(
      node.icon.id,
      node.icon.color ? new vscode.ThemeColor(node.icon.color) : undefined
    )
    item.tooltip = node.tooltip
    if (node.kind === "session") {
      item.description = node.description
      item.contextValue = "session"
      item.command = {
        command: "ax.openSession",
        title: "Open Session",
        arguments: [node.provider, node.id, node.label],
      }
    }
    return item
  }
}

/** Session tabs: one webview per session, reused when it is open already. */
class Tabs {
  private readonly open = new Map<string, vscode.WebviewPanel>()

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly started: () => void
  ) {}

  private options(): vscode.WebviewPanelOptions & vscode.WebviewOptions {
    return {
      enableScripts: true,
      // Switching tabs keeps the conversation where it was instead of reading it again.
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "media")],
    }
  }

  session(
    provider: "claude" | "codex",
    id: string,
    name?: string,
    column = vscode.ViewColumn.Active
  ) {
    const shown = this.open.get(`${provider}:${id}`)
    if (shown) return shown.reveal(shown.viewColumn)
    const panel = vscode.window.createWebviewPanel(
      "ax.session",
      name ?? "Session",
      column,
      this.options()
    )
    this.attach(panel, { screen: "session", provider, id })
  }

  /** A tab VS Code kept from before a restart, back on its session. */
  restore(panel: vscode.WebviewPanel, state: unknown) {
    const { provider, id } = (state ?? {}) as { provider?: unknown; id?: unknown }
    if (!isProvider(provider) || typeof id !== "string") return panel.dispose()
    panel.webview.options = this.options()
    this.attach(panel, { screen: "session", provider, id })
  }

  /** The new-session form, offering the workspace's folders, the active file's first. */
  newSession() {
    const active = vscode.window.activeTextEditor?.document.uri
    const here = active && vscode.workspace.getWorkspaceFolder(active)
    const folders = [here, ...(vscode.workspace.workspaceFolders ?? [])]
      .filter((f): f is vscode.WorkspaceFolder => Boolean(f))
      .map((f) => f.uri.fsPath)
    const panel = vscode.window.createWebviewPanel(
      "ax.newSession",
      "New session",
      vscode.ViewColumn.Active,
      this.options()
    )
    this.attach(panel, { screen: "new", folders: [...new Set(folders)] })
  }

  /** Keep each open tab named as ax names its session. */
  retitle(listing: Listing) {
    for (const s of listing.sessions) {
      const panel = this.open.get(`${s.provider}:${s.id}`)
      if (panel && panel.title !== s.name) panel.title = s.name
    }
  }

  private attach(panel: vscode.WebviewPanel, view: View) {
    const media = vscode.Uri.joinPath(this.context.extensionUri, "media")
    const file = (name: string) =>
      panel.webview.asWebviewUri(vscode.Uri.joinPath(media, "webview", name)).toString()
    panel.iconPath = vscode.Uri.joinPath(media, "tab.svg")
    panel.webview.html = pageHtml({
      cspSource: panel.webview.cspSource,
      nonce: randomBytes(16).toString("hex"),
      script: file("webview.js"),
      style: file("webview.css"),
      server: server(),
      view,
    })
    if (view.screen === "session") {
      const key = `${view.provider}:${view.id}`
      this.open.set(key, panel)
      panel.onDidDispose(() => this.open.get(key) === panel && this.open.delete(key))
    }
    panel.webview.onDidReceiveMessage((message) => this.receive(panel, message))
  }

  private async receive(panel: vscode.WebviewPanel, message: unknown) {
    const m = (message ?? {}) as Record<string, unknown>
    if (m.type === "request") {
      const reply = await forward(server(), m as BridgeRequest)
      await panel.webview.postMessage(reply)
    } else if (m.type === "open" && typeof m.href === "string") {
      const target = linkTarget(m.href, server())
      if (target) await vscode.env.openExternal(vscode.Uri.parse(target))
    } else if (m.type === "started" && isProvider(m.provider) && typeof m.id === "string") {
      // The form's tab becomes the session's.
      const column = panel.viewColumn
      panel.dispose()
      this.session(m.provider, m.id, typeof m.name === "string" ? m.name : undefined, column)
      this.started()
    } else if (m.type === "close") panel.dispose()
  }
}

export function activate(context: vscode.ExtensionContext) {
  const tree = new SessionsTree()
  const view = vscode.window.createTreeView("ax.sessions", { treeDataProvider: tree })
  const refresh = async () => {
    const listing = await tree.read()
    const waiting = listing ? waitingCount(listing) : 0
    view.badge = waiting
      ? {
          value: waiting,
          tooltip: waiting === 1 ? "1 session waits for you" : `${waiting} sessions wait for you`,
        }
      : undefined
    if (listing) tabs.retitle(listing)
  }
  const tabs = new Tabs(context, () => void refresh())

  // Every 5 seconds while the sidebar shows, every 20 otherwise: the badge still counts.
  let timer: ReturnType<typeof setTimeout> | undefined
  const tick = () => {
    clearTimeout(timer)
    void refresh().finally(() => {
      timer = setTimeout(tick, view.visible ? 5_000 : 20_000)
    })
  }
  tick()

  context.subscriptions.push(
    view,
    view.onDidChangeVisibility((e) => e.visible && tick()),
    { dispose: () => clearTimeout(timer) },
    vscode.commands.registerCommand("ax.refresh", tick),
    vscode.commands.registerCommand("ax.newSession", () => tabs.newSession()),
    vscode.commands.registerCommand(
      "ax.openSession",
      (provider: unknown, id: unknown, name: unknown) => {
        if (isProvider(provider) && typeof id === "string")
          tabs.session(provider, id, typeof name === "string" ? name : undefined)
      }
    ),
    vscode.window.registerWebviewPanelSerializer("ax.session", {
      deserializeWebviewPanel: async (panel, state) => tabs.restore(panel, state),
    }),
    vscode.workspace.onDidChangeConfiguration((e) => e.affectsConfiguration("ax.server") && tick())
  )
}

export function deactivate() {}

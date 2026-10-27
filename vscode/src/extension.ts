import { randomBytes } from "node:crypto"
import { homedir } from "node:os"
import * as vscode from "vscode"

import { type BridgeRequest, call, forward, linkTarget } from "./bridge"
import type { Base } from "./changes"
import { BEFORE_SCHEME, BeforeFiles, openFile, type Shown, showChanges } from "./editor"
import { pageHtml, type View } from "./html"
import { fileTarget } from "./links"
import { newlyWaiting, notice } from "./notify"
import { UsageBar } from "./status"
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
    const reply = await call(server(), "GET", "/api/sessions")
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
  private readonly open = new Map<string, { panel: vscode.WebviewPanel; shown: Shown }>()

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
    const shown = this.open.get(`${provider}:${id}`)?.panel
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
      const open = this.open.get(`${s.provider}:${s.id}`)
      if (open && open.panel.title !== s.name) open.panel.title = s.name
      if (open) open.shown.name = s.name
    }
  }

  /** The session whose tab has the focus, if one has. */
  active(): Shown | undefined {
    return [...this.open.values()].find((o) => o.panel.active)?.shown
  }

  /** Whether the user is looking at this session's tab now. */
  inFront(provider: string, id: string): boolean {
    const panel = this.open.get(`${provider}:${id}`)?.panel
    return Boolean(panel?.active && panel.visible && vscode.window.state.focused)
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
      this.open.set(key, {
        panel,
        shown: { provider: view.provider, id: view.id, name: panel.title },
      })
      panel.onDidDispose(() => this.open.get(key)?.panel === panel && this.open.delete(key))
    }
    panel.webview.onDidReceiveMessage((message) => this.receive(panel, message))
  }

  private async receive(panel: vscode.WebviewPanel, message: unknown) {
    const m = (message ?? {}) as Record<string, unknown>
    if (m.type === "request") {
      const reply = await forward(server(), m as BridgeRequest)
      await panel.webview.postMessage(reply)
    } else if (m.type === "open" && typeof m.href === "string") {
      const web = linkTarget(m.href, server())
      if (web) return void vscode.env.openExternal(vscode.Uri.parse(web))
      const file = fileTarget(m.href, typeof m.cwd === "string" ? m.cwd : null, homedir())
      if (file) await openFile(file)
    } else if (m.type === "started" && isProvider(m.provider) && typeof m.id === "string") {
      // The form's tab becomes the session's.
      const column = panel.viewColumn
      panel.dispose()
      this.session(m.provider, m.id, typeof m.name === "string" ? m.name : undefined, column)
      this.started()
    } else if (m.type === "close") panel.dispose()
  }
}

/** A notice for each session that starts waiting, unless its tab is in front of the user. */
function announce(tabs: Tabs, before: Listing | null, now: Listing) {
  if (!vscode.workspace.getConfiguration("ax").get<boolean>("notifications", true)) return
  const fresh = newlyWaiting(before, now).filter((s) => !tabs.inFront(s.provider, s.id))
  if (fresh.length > 3) {
    void vscode.window
      .showInformationMessage(`${fresh.length} sessions wait for you`, "Show them")
      .then((choice) => choice && vscode.commands.executeCommand("ax.sessions.focus"))
    return
  }
  for (const s of fresh)
    void vscode.window
      .showInformationMessage(notice(s), "Open")
      .then((choice) => choice && tabs.session(s.provider, s.id, s.name))
}

export function activate(context: vscode.ExtensionContext) {
  const tree = new SessionsTree()
  const view = vscode.window.createTreeView("ax.sessions", { treeDataProvider: tree })
  const usage = new UsageBar(server)
  const before = new BeforeFiles(server)
  let last: Listing | null = null
  const refresh = async () => {
    const listing = await tree.read()
    const waiting = listing ? waitingCount(listing) : 0
    view.badge = waiting
      ? {
          value: waiting,
          tooltip: waiting === 1 ? "1 session waits for you" : `${waiting} sessions wait for you`,
        }
      : undefined
    if (!listing) return
    tabs.retitle(listing)
    announce(tabs, last, listing)
    last = listing
  }
  const tabs = new Tabs(context, () => void refresh())

  // The session a diff command means: the sidebar's row it was run on, else the tab in front.
  const changes = (base: Base) => (node?: TreeNode) => {
    const session =
      node?.kind === "session"
        ? { provider: node.provider, id: node.id, name: node.label }
        : tabs.active()
    if (!session) return void vscode.window.showInformationMessage("Open a session's tab first.")
    return showChanges(before, server(), session, base)
  }

  // Usage moves slowly: once a minute.
  void usage.refresh()
  const usageTimer = setInterval(() => void usage.refresh(), 60_000)

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
    { dispose: () => clearInterval(usageTimer) },
    usage,
    vscode.workspace.registerTextDocumentContentProvider(BEFORE_SCHEME, before),
    vscode.commands.registerCommand("ax.changesThisTurn", changes("turn")),
    vscode.commands.registerCommand("ax.changesSinceCommit", changes("commit")),
    vscode.commands.registerCommand("ax.openUsage", () =>
      vscode.env.openExternal(vscode.Uri.parse(`${server().replace(/\/+$/, "")}/#/usage`))
    ),
    vscode.commands.registerCommand("ax.refresh", () => {
      tick()
      void usage.refresh()
    }),
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
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration("ax.server")) return
      tick()
      void usage.refresh()
    })
  )
}

export function deactivate() {}

import { createHash, randomBytes } from "node:crypto"
import { homedir } from "node:os"
import * as vscode from "vscode"

// The page's own reading of a job link, bundled from its source so both say the same.
import { jobKey } from "../../ui/src/lib/job"
import { shortPath } from "../../ui/src/lib/paths"
import { type BridgeRequest, call, forward, linkTarget } from "./bridge"
import type { Base } from "./changes"
import {
  BEFORE_SCHEME,
  BeforeFiles,
  completeFiles,
  currentContext,
  currentSelection,
  followEditors,
  followExtensions,
  openFile,
  openNotebook,
  pickFiles,
  pickFolder,
  problemsContext,
  type Shown,
  showChanges,
  terminalContext,
  workspaceFolders,
} from "./editor"
import { pageHtml, type View } from "./html"
import { fileTarget } from "./links"
import {
  type Listing,
  offScreen,
  revealIn,
  type Session,
  tabIcon,
  tabState,
  waitingCount,
} from "./listing"
import { announcement, newlyWaiting } from "./notify"
import { saveStart, unplaced } from "./opening"
import {
  focusTaken,
  type Hit,
  hitItem,
  liveItems,
  narrowing,
  type Open,
  type PickRow,
  searchUrl,
} from "./searchPick"
import { SessionFiles } from "./sessionFiles"
import { readSessionResource, sessionResource } from "./sessionUri"
import { SharedBar, UsageBar } from "./status"

const server = () =>
  vscode.workspace.getConfiguration("ax").get<string>("server", "http://127.0.0.1:8765")

const isProvider = (value: unknown): value is "claude" | "codex" =>
  value === "claude" || value === "codex"

/**
 * What a page asks of the extension whatever it is, a tab or the panel: ax's API, what
 * only the editor knows (files, the selection, a folder), and links to open. False for a
 * message that is the page's own business.
 */
const webviewServers = new Map<vscode.Webview, string>()
let extensionContext: vscode.ExtensionContext

function draftFile(key: string) {
  return vscode.Uri.joinPath(
    extensionContext.globalStorageUri,
    `draft-${createHash("sha256").update(key).digest("hex")}.json`
  )
}

async function answer(webview: vscode.Webview, message: unknown): Promise<boolean> {
  const m = (message ?? {}) as Record<string, unknown>
  if (m.type === "request") {
    await webview.postMessage(
      await forward(webviewServers.get(webview) ?? server(), m as BridgeRequest)
    )
    return true
  }
  if (m.type === "call" && typeof m.id === "number") {
    const reply = (value: unknown, error?: string) =>
      webview.postMessage({ type: "result", id: m.id, value, ...(error ? { error } : {}) })
    try {
      if (m.name === "draftRead") {
        const file = draftFile(String(m.args))
        await reply(
          await vscode.workspace.fs.readFile(file).then(
            (value) => JSON.parse(new TextDecoder().decode(value)),
            () => null
          )
        )
      } else if (m.name === "draftWrite") {
        const draft = m.args as { key: string; value: unknown }
        await vscode.workspace.fs.createDirectory(extensionContext.globalStorageUri)
        await vscode.workspace.fs.writeFile(
          draftFile(draft.key),
          new TextEncoder().encode(JSON.stringify(draft.value))
        )
        await reply(true)
      } else if (m.name === "showChanges") {
        const args = m.args as Shown & { base: Base }
        const endpoint = webviewServers.get(webview) ?? server()
        await showChanges(new BeforeFiles(() => endpoint), endpoint, args, args.base)
        await reply(true)
      } else if (m.name === "openSession") {
        const args = m.args as { provider: string; id: string }
        if (!isProvider(args.provider) || typeof args.id !== "string")
          throw new Error("Invalid session")
        await vscode.commands.executeCommand(
          "vscode.openWith",
          vscode.Uri.parse(
            sessionResource(webviewServers.get(webview) ?? server(), args.provider, args.id)
          ),
          "ax.sessionEditor",
          { preview: false }
        )
        await reply(true)
      } else if (m.name === "preferences")
        await reply(
          Object.fromEntries(
            [
              "sendKey",
              "autoContext",
              "chatFontFamily",
              "chatFontSize",
              "codeFontSize",
              "reviewMode",
            ].map((key) => [key, vscode.workspace.getConfiguration("ax").get(key)])
          )
        )
      else if (m.name === "preferencesWrite") {
        const values = m.args as Record<string, unknown>
        for (const key of [
          "sendKey",
          "autoContext",
          "chatFontFamily",
          "chatFontSize",
          "codeFontSize",
          "reviewMode",
        ]) {
          if (key in values)
            await vscode.workspace
              .getConfiguration("ax")
              .update(key, values[key], vscode.ConfigurationTarget.Global)
        }
        await reply(true)
      } else if (m.name === "completeFiles") await reply(await completeFiles(String(m.args ?? "")))
      else if (m.name === "currentContext") await reply(await currentContext())
      else if (m.name === "problems") await reply(problemsContext())
      else if (m.name === "terminal") await reply(await terminalContext())
      else if (m.name === "selection") await reply(currentSelection())
      else if (m.name === "pickFiles") await reply(await pickFiles())
      else if (m.name === "pickFolder") await reply(await pickFolder())
      else if (m.name === "openNotebook") await reply(await notebookAt(m.args))
      else if (m.name === "openMarkdown") await reply(await markdownBeside(m.args))
      else if (m.name === "saveMarkdown") await reply(await savedMarkdown(m.args))
      else if (m.name === "copy") await reply(await copied(m.args))
      else await reply(null, `the extension has no ${String(m.name)}`)
    } catch (e) {
      await reply(null, (e as Error).message)
    }
    return true
  }
  if (m.type === "open" && typeof m.href === "string") {
    // The page opens a job's card itself; it asks here only when it shows none.
    const job = jobKey(m.href)
    if (job) {
      void vscode.window.showInformationMessage(
        `This session shows no card for the job ${job}: \`ax job show ${job}\` prints it.`
      )
      return true
    }
    const web = linkTarget(m.href)
    if (web) {
      void vscode.env.openExternal(vscode.Uri.parse(web))
      return true
    }
    const cwd = typeof m.cwd === "string" ? m.cwd : null
    const file = fileTarget(m.href, cwd, homedir())
    if (file) await openFile(file)
    else {
      const why = unplaced(m.href, cwd)
      if (why) void vscode.window.showWarningMessage(why)
    }
    return true
  }
  return false
}

/** Text the page copies, onto VS Code's clipboard: a webview may not reach the system's. */
function copied(args: unknown): Promise<void> {
  const { text } = (args ?? {}) as { text?: unknown }
  if (typeof text !== "string") return Promise.reject(new Error("there is no text to copy"))
  return Promise.resolve(vscode.env.clipboard.writeText(text))
}

/** The notebook a job card names, at its cell: a full path to a notebook, and a cell. */
function notebookAt(args: unknown): Promise<void> {
  const { path, cell } = (args ?? {}) as { path?: unknown; cell?: unknown }
  if (typeof path !== "string" || !path.startsWith("/") || !path.endsWith(".ipynb"))
    return Promise.reject(new Error("that isn't a notebook's full path"))
  return openNotebook(path, typeof cell === "number" ? cell : null)
}

/** The page's Markdown, such as a plan, in an untitled tab beside the page's own. It
 * carries the file it would be saved as, so its tab is named so and Save goes there. */
async function markdownBeside(args: unknown): Promise<void> {
  const { text, name, cwd } = (args ?? {}) as { text?: unknown; name?: unknown; cwd?: unknown }
  if (typeof text !== "string") throw new Error("there is no Markdown to open")
  const uri = vscode.Uri.from({ scheme: "untitled", path: saveStart(cwd, name, homedir()) })
  const doc = await vscode.workspace.openTextDocument(uri)
  if (doc.getText() !== text) {
    const edit = new vscode.WorkspaceEdit()
    edit.replace(uri, new vscode.Range(0, 0, doc.lineCount, 0), text)
    await vscode.workspace.applyEdit(edit)
  }
  await vscode.window.showTextDocument(doc, {
    viewColumn: vscode.ViewColumn.Beside,
    preview: false,
  })
}

/** The page's Markdown saved where the user picks, starting in the session's folder; the
 * file's path, or null when the dialog was dismissed. */
async function savedMarkdown(args: unknown): Promise<string | null> {
  const { text, name, cwd } = (args ?? {}) as { text?: unknown; name?: unknown; cwd?: unknown }
  if (typeof text !== "string") throw new Error("there is no Markdown to save")
  const target = await vscode.window.showSaveDialog({
    defaultUri: vscode.Uri.file(saveStart(cwd, name, homedir())),
    filters: { Markdown: ["md"] },
  })
  if (!target) return null
  await vscode.workspace.fs.writeFile(target, new TextEncoder().encode(text))
  void vscode.window
    .showInformationMessage(`Saved ${shortPath(target.fsPath)}`, "Open")
    .then((choice) => choice && vscode.window.showTextDocument(target, { preview: false }))
  return target.fsPath
}

const pageFiles = (context: vscode.ExtensionContext, webview: vscode.Webview) => {
  const media = vscode.Uri.joinPath(context.extensionUri, "media")
  const file = (...path: string[]) =>
    webview.asWebviewUri(vscode.Uri.joinPath(media, ...path)).toString()
  return {
    script: file("webview", "webview.js"),
    style: file("webview", "webview.css"),
    icons: file("ax-icons.woff"),
  }
}

/** Show the session's tab VS Code kept from before a reload, which also brings it back to
 * the extension; false when there is none. */
/**
 * Session tabs: one webview per session, reused when it is open already, or when VS Code
 * kept it from before a reload and hasn't shown it since.
 */
class Tabs {
  private readonly open = new Map<
    string,
    {
      panel: vscode.WebviewPanel
      shown: Shown
      icon?: string
      /** The state its page last reported, and when. */
      reported?: { state: Session["state"]; at: number }
    }
  >()

  constructor(private readonly context: vscode.ExtensionContext) {}
  private key(provider: string, id: string, endpoint = server()) {
    return `${endpoint.replace(/\/+$/, "")}:${provider}:${id}`
  }

  private options(): vscode.WebviewPanelOptions & vscode.WebviewOptions {
    return {
      enableScripts: true,
      enableFindWidget: true,
      // Switching tabs keeps the conversation where it was instead of reading it again.
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "media")],
    }
  }

  async session(
    provider: "claude" | "codex",
    id: string,
    name?: string,
    column = vscode.ViewColumn.Active
  ) {
    const shown = this.open.get(this.key(provider, id))?.panel
    if (shown) {
      const to = revealIn(shown.viewColumn, column)
      shown.reveal(to)
      // A tab moved to another column arrives as a preview, which the next tab opened
      // there would replace; one being watched there stays.
      if (to === vscode.ViewColumn.Beside)
        void vscode.commands.executeCommand("workbench.action.keepEditor")
      return
    }
    const uri = vscode.Uri.parse(sessionResource(server(), provider, id))
    await vscode.commands.executeCommand("vscode.openWith", uri, "ax.sessionEditor", {
      viewColumn: column,
      preview: false,
    })
    const panel = this.open.get(this.key(provider, id))?.panel
    if (panel && name) panel.title = name
  }

  private searching: vscode.WebviewPanel | undefined

  /** The search tab: `ax find` over past sessions and the rest, the one already open if
   * there is one. */
  search() {
    if (this.searching) return this.searching.reveal(this.searching.viewColumn)
    const panel = vscode.window.createWebviewPanel(
      "ax.search",
      "Search",
      vscode.ViewColumn.Active,
      this.options()
    )
    this.searching = panel
    panel.onDidDispose(() => {
      if (this.searching === panel) this.searching = undefined
    })
    this.attach(panel, { screen: "search" })
  }

  /** A tab VS Code kept from before a restart, back on its session. */
  async restore(panel: vscode.WebviewPanel, state: unknown) {
    const legacy = (state ?? {}) as {
      provider?: unknown
      id?: unknown
      server?: string
      draft?: unknown
    }
    const { provider, id } = legacy
    if (!isProvider(provider) || typeof id !== "string") return panel.dispose()
    const endpoint = legacy.server ?? server()
    if (legacy.draft && typeof legacy.draft === "object") {
      const file = draftFile(`${endpoint.replace(/\/+$/, "")}:${provider}:${id}`)
      try {
        await vscode.workspace.fs.stat(file)
      } catch {
        await vscode.workspace.fs.createDirectory(this.context.globalStorageUri)
        await vscode.workspace.fs.writeFile(file, Buffer.from(JSON.stringify(legacy.draft)))
      }
    }
    await vscode.commands.executeCommand(
      "vscode.openWith",
      vscode.Uri.parse(sessionResource(endpoint, provider, id)),
      "ax.sessionEditor",
      { viewColumn: panel.viewColumn, preview: false }
    )
    // A singleton editor may already be restored in another group. Reveal moves
    // that editor explicitly; openWith alone can keep its previous group.
    const migrated = this.open.get(this.key(provider, id, endpoint))?.panel
    if (migrated && panel.viewColumn !== undefined) migrated.reveal(panel.viewColumn)
    panel.dispose()
  }

  resolve(document: vscode.CustomDocument, panel: vscode.WebviewPanel) {
    const view = readSessionResource(document.uri.toString())
    panel.webview.options = this.options()
    panel.title =
      this.context.globalState.get<string>(
        `title:${this.key(view.provider, view.id, view.server)}`
      ) ?? "Loading chat…"
    this.attach(panel, { screen: "session", provider: view.provider, id: view.id }, view.server)
  }

  /** Keep each open tab named as ax names its session, its icon saying what it does. */
  retitle(listing: Listing) {
    for (const s of listing.sessions) {
      const open = this.open.get(this.key(s.provider, s.id))
      if (!open) continue
      if (open.panel.title !== s.name) open.panel.title = s.name
      open.shown.name = s.name
      open.shown.cwd = s.cwd
      this.showState(this.key(s.provider, s.id), tabState(s.state, open.reported))
    }
  }

  /** A tab's page reports its session's state as it changes: its icon follows at once. */
  reportState(key: string, state: Session["state"]) {
    const open = this.open.get(key)
    if (!open) return
    open.reported = { state, at: Date.now() }
    this.showState(key, state)
  }

  private showState(key: string, state: Session["state"]) {
    const open = this.open.get(key)
    if (!open) return
    const icon = tabIcon(state)
    if (open.icon === icon) return
    open.icon = icon
    open.panel.iconPath = vscode.Uri.joinPath(this.context.extensionUri, "media", icon)
  }

  /** The session whose tab has the focus, if one has. */
  active(): Shown | undefined {
    return [...this.open.values()].find((o) => o.panel.active)?.shown
  }

  /** Close the session tabs that aren't on screen, keeping the one in front of each
   * column; how many closed. */
  closeOffScreen(): number {
    const closing = offScreen([...this.open.values()].map((o) => o.panel))
    for (const panel of closing) panel.dispose()
    return closing.length
  }

  /** Whether any session's tab is on screen, in any column: then its icon is watched. */
  watched(): boolean {
    return [...this.open.values()].some((o) => o.panel.visible)
  }

  /** Whether the user is looking at this session's tab now. */
  inFront(provider: string, id: string): boolean {
    const panel = this.open.get(this.key(provider, id))?.panel
    return Boolean(panel?.active && panel.visible && vscode.window.state.focused)
  }

  private attach(panel: vscode.WebviewPanel, view: View, endpoint = server()) {
    const webview = panel.webview
    webviewServers.set(webview, endpoint)
    panel.onDidDispose(() => webviewServers.delete(webview))
    panel.onDidChangeViewState(
      () => void panel.webview.postMessage({ type: "visibility", visible: panel.visible })
    )
    panel.iconPath = vscode.Uri.joinPath(this.context.extensionUri, "media", "tab.svg")
    panel.webview.html = pageHtml({
      cspSource: panel.webview.cspSource,
      nonce: randomBytes(16).toString("hex"),
      ...pageFiles(this.context, panel.webview),
      server: endpoint,
      view,
    })
    if (view.screen === "session") {
      const key = this.key(view.provider, view.id, endpoint)
      this.open.set(key, {
        panel,
        shown: { provider: view.provider, id: view.id, name: panel.title, server: endpoint },
      })
      panel.onDidDispose(() => this.open.get(key)?.panel === panel && this.open.delete(key))
    }
    panel.webview.onDidReceiveMessage((message) => this.receive(panel, message))
  }

  private async receive(panel: vscode.WebviewPanel, message: unknown) {
    if (await answer(panel.webview, message)) return
    // The search tab opens what it found in a session's own tab.
    const m = (message ?? {}) as Record<string, unknown>
    if (m.type === "ready") {
      void panel.webview.postMessage({ type: "visibility", visible: panel.visible })
      return
    }
    if (m.type === "openSession" && isProvider(m.provider) && typeof m.id === "string")
      await this.session(m.provider, m.id, typeof m.name === "string" ? m.name : undefined)
    if (m.type === "state" && isProvider(m.provider) && typeof m.id === "string") {
      const key = this.key(m.provider, m.id, webviewServers.get(panel.webview))
      this.reportState(key, isState(m.state) ? m.state : null)
      if (typeof m.name === "string" && m.name) {
        panel.title = m.name
        void this.context.globalState.update(`title:${key}`, m.name)
      }
    }
  }
}

/**
 * ax in the right sidebar, where Codex and Copilot sit: every live session and a box
 * that starts a new one. A session opens in its own tab, a started one too.
 */
class Panel implements vscode.WebviewViewProvider {
  private view: vscode.WebviewView | undefined

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly tabs: Tabs,
    private readonly before: BeforeFiles,
    private readonly started: () => void
  ) {}

  resolveWebviewView(view: vscode.WebviewView) {
    this.view = view
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "media")],
    }
    view.webview.html = pageHtml({
      cspSource: view.webview.cspSource,
      nonce: randomBytes(16).toString("hex"),
      ...pageFiles(this.context, view.webview),
      server: server(),
      view: { screen: "panel", folders: workspaceFolders() },
    })
    const webview = view.webview
    webviewServers.set(webview, server())
    view.webview.onDidReceiveMessage((message) => void this.receive(message))
    view.onDidDispose(() => {
      webviewServers.delete(webview)
      if (this.view === view) this.view = undefined
    })
  }

  get visible(): boolean {
    return this.view?.visible ?? false
  }

  set badge(waiting: number) {
    if (!this.view) return
    this.view.badge = waiting
      ? {
          value: waiting,
          tooltip: waiting === 1 ? "1 session waits for you" : `${waiting} sessions wait for you`,
        }
      : undefined
  }

  /** Bring the cursor to the box that starts a session. */
  async focusComposer() {
    await vscode.commands.executeCommand("ax.panel.focus")
    await this.view?.webview.postMessage({ type: "focusComposer" })
  }

  private async receive(message: unknown) {
    if (!this.view || (await answer(this.view.webview, message))) return
    const m = (message ?? {}) as Record<string, unknown>
    if (!isProvider(m.provider) || typeof m.id !== "string") return
    const name = typeof m.name === "string" ? m.name : undefined
    if (m.type === "openSession") {
      const column = m.beside ? vscode.ViewColumn.Beside : vscode.ViewColumn.Active
      this.tabs.session(m.provider, m.id, name, column)
    } else if (m.type === "started") {
      this.tabs.session(m.provider, m.id, name)
      this.started()
    } else if (m.type === "changes") {
      const base = m.base === "commit" ? "commit" : m.base === "session" ? "session" : "turn"
      const session = { provider: m.provider, id: m.id, name: name ?? "Session" }
      await showChanges(this.before, server(), session, base)
    }
  }
}

/** One notice for the sessions that start waiting, leaving out those whose tab is in
 * front of the user: a session alone opens from it, several show the panel. */
function announce(tabs: Tabs, before: Listing | null, now: Listing) {
  if (!vscode.workspace.getConfiguration("ax").get<boolean>("notifications", true)) return
  const said = announcement(
    newlyWaiting(before, now).filter((s) => !tabs.inFront(s.provider, s.id))
  )
  if (!said) return
  const { open } = said
  void vscode.window
    .showInformationMessage(said.text, open ? "Open" : "Show them")
    .then((choice) => {
      if (!choice) return
      if (open) tabs.session(open.provider, open.id, open.name)
      else void vscode.commands.executeCommand("ax.panel.focus")
    })
}

type Shared = { shared: boolean; link: string | null }

const isState = (value: unknown): value is Session["state"] =>
  value === "working" || value === "waiting" || value === "idle" || value === null

let sharedBar: SharedBar | undefined

/** Whether ax is shared through Cloudflare, shown by the panel's share button. */
async function readShared(): Promise<Shared | null> {
  const reply = await call(server(), "GET", "/api/share")
  if (reply.status !== 200) return null
  const found = reply.body as Shared
  await vscode.commands.executeCommand("setContext", "ax.shared", found.shared)
  sharedBar?.show(found.shared)
  return found
}

const failed = (body: unknown) => (body as { error?: string } | null)?.error ?? "ax didn't answer"

/** Share ax through a Cloudflare link, copied here and sent with ntfy by ax. */
async function share() {
  const reply = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Sharing ax through Cloudflare…" },
    () => call(server(), "POST", "/api/share", { on: true })
  )
  if (reply.status !== 200) {
    void vscode.window.showErrorMessage(`ax isn't shared: ${failed(reply.body)}`)
    return
  }
  const { link } = reply.body as Shared
  if (link) await vscode.env.clipboard.writeText(link)
  await readShared()
  const choice = await vscode.window.showInformationMessage(
    "ax is shared: the link is copied, and sent with ntfy when it is set up. Anyone with it can read and act on every session until you stop sharing.",
    "Stop sharing"
  )
  if (choice) await unshare()
}

async function unshare() {
  const reply = await call(server(), "POST", "/api/share", { on: false })
  if (reply.status !== 200) {
    void vscode.window.showErrorMessage(`ax is still shared: ${failed(reply.body)}`)
    return
  }
  await readShared()
  void vscode.window.showInformationMessage("ax is no longer shared: its link stopped working.")
}

/** The share button while ax is shared: copy its link again, or stop. */
async function sharing() {
  const now = await readShared()
  if (!now?.shared) return share()
  const choice = await vscode.window.showInformationMessage(
    "ax is shared through Cloudflare.",
    "Copy the link",
    "Stop sharing"
  )
  if (choice === "Copy the link" && now.link) {
    await vscode.env.clipboard.writeText(now.link)
    void vscode.window.showInformationMessage("The link is copied.")
  } else if (choice === "Stop sharing") await unshare()
}

const SEARCH = "Search past sessions"

/**
 * ax's search where VS Code's own pickers open, at the top centre: the live sessions
 * until something is typed, then `ax find`, its keyword matches at once and the whole
 * search, by meaning and in code, when it is ready. Enter opens a conversation as its
 * session's tab, anything else in the editor at its line.
 */
function openSearch(tabs: Tabs) {
  const pick = vscode.window.createQuickPick<PickRow & vscode.QuickPickItem>()
  pick.title = SEARCH
  pick.placeholder = "Search past conversations and memories"
  let asked = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  const live = async () => {
    const mine = asked
    const listing = await readListing()
    if (mine === asked && !pick.value.trim()) pick.items = liveItems(listing?.sessions ?? [])
  }
  const rows = (body: unknown) => ((body as { hits?: Hit[] }).hits ?? []).map((hit) => hitItem(hit))
  const search = (query: string) => {
    const mine = ++asked
    let whole = false
    pick.busy = true
    pick.title = `${SEARCH}: searching…`
    void call(server(), "GET", searchUrl(query, true)).then((reply) => {
      if (mine !== asked || whole || reply.status !== 200) return
      pick.items = rows(reply.body)
      pick.title = `${SEARCH}: matches by words so far, looking by meaning and in code…`
    })
    void call(server(), "GET", searchUrl(query, false)).then((reply) => {
      if (mine !== asked) return
      whole = true
      pick.busy = false
      pick.title = SEARCH
      const found = reply.status === 200 ? rows(reply.body) : []
      pick.items = found.length
        ? found
        : [
            {
              label:
                reply.status === 200
                  ? `$(search) Nothing found for “${query}”`
                  : "$(warning) The search didn't run",
              ...(reply.status === 200 ? {} : { detail: failed(reply.body) }),
              alwaysShow: true,
            },
          ]
    })
  }
  pick.onDidChangeValue((value) => {
    clearTimeout(timer)
    const query = value.trim()
    if (!query) {
      asked++
      pick.busy = false
      pick.title = SEARCH
      void live()
      return
    }
    // Searching shows at once, and what is listed narrows to the words until the answer
    // comes; the search waits for a pause in typing, not every key.
    pick.busy = true
    pick.title = `${SEARCH}: searching…`
    pick.items = narrowing(pick.items)
    timer = setTimeout(() => search(query), 250)
  })
  let accepted = false
  let reopened = false
  let shownAt = Date.now()
  pick.onDidAccept(() => {
    const open = pick.selectedItems[0]?.open
    if (!open) return
    accepted = true
    pick.hide()
    void openFound(tabs, open)
  })
  pick.onDidHide(() => {
    if (focusTaken({ openFor: Date.now() - shownAt, accepted, reopened })) {
      reopened = true
      shownAt = Date.now()
      pick.show()
      if (!pick.value.trim()) void live() // what it listed doesn't come back with it
      return
    }
    clearTimeout(timer)
    asked++
    pick.dispose()
  })
  pick.show()
  void live()
}

async function openFound(tabs: Tabs, open: Open) {
  if ("session" in open)
    return tabs.session(open.session.provider, open.session.id, open.session.name)
  const file = fileTarget(open.file, null, homedir())
  if (file) await openFile(file)
}

/** The listing, or null while ax doesn't answer. */
async function readListing(): Promise<Listing | null> {
  const reply = await call(server(), "GET", "/api/sessions")
  return reply.status === 200 ? (reply.body as Listing) : null
}

export function activate(context: vscode.ExtensionContext) {
  const usage = new UsageBar(server)
  sharedBar = new SharedBar()
  context.subscriptions.push(sharedBar)
  const before = new BeforeFiles(server)
  let last: Listing | null = null
  const refresh = async () => {
    void readShared()
    const listing = await readListing()
    panel.badge = listing ? waitingCount(listing) : 0
    if (!listing) return
    tabs.retitle(listing)
    announce(tabs, last, listing)
    last = listing
  }
  extensionContext = context
  const tabs = new Tabs(context)
  const panel = new Panel(context, tabs, before, () => void refresh())

  // The session a diff command means: the tab in front.
  const changes = (base: Base) => () => {
    const session = tabs.active()
    if (!session) return void vscode.window.showInformationMessage("Open a session's tab first.")
    return showChanges(before, session.server ?? server(), session, base)
  }

  // Every 10 s, as often as ax asks Codex for fresh figures.
  void usage.refresh()
  const usageTimer = setInterval(() => void usage.refresh(), 10_000)

  // Every 5 seconds while the panel or a session's tab shows, every 20 otherwise: the
  // badge still counts.
  let timer: ReturnType<typeof setTimeout> | undefined
  let refreshing = false
  let refreshAgain = false
  let disposed = false
  const tick = () => {
    if (disposed) return
    clearTimeout(timer)
    if (refreshing) {
      refreshAgain = true
      return
    }
    refreshing = true
    void refresh().finally(() => {
      refreshing = false
      if (disposed) return
      const delay = refreshAgain ? 0 : panel.visible || tabs.watched() ? 5_000 : 20_000
      refreshAgain = false
      timer = setTimeout(tick, delay)
    })
  }
  tick()

  context.subscriptions.push(
    vscode.workspace.registerFileSystemProvider("ax-session", new SessionFiles(), {
      isReadonly: true,
    }),
    vscode.window.registerCustomEditorProvider(
      "ax.sessionEditor",
      {
        openCustomDocument: async (uri) => ({ uri, dispose() {} }),
        resolveCustomEditor: async (document, webviewPanel) => tabs.resolve(document, webviewPanel),
      },
      {
        supportsMultipleEditorsPerDocument: false,
        webviewOptions: { retainContextWhenHidden: true, enableFindWidget: true },
      }
    ),
    followEditors(),
    followExtensions(),
    vscode.window.registerWebviewViewProvider("ax.panel", panel, {
      // The panel keeps its list and a half-written message while it is hidden.
      webviewOptions: { retainContextWhenHidden: true },
    }),
    {
      dispose: () => {
        disposed = true
        clearTimeout(timer)
      },
    },
    { dispose: () => clearInterval(usageTimer) },
    usage,
    vscode.workspace.registerTextDocumentContentProvider(BEFORE_SCHEME, before),
    vscode.commands.registerCommand("ax.changesThisTurn", changes("turn")),
    vscode.commands.registerCommand("ax.changesSinceCommit", changes("commit")),
    vscode.commands.registerCommand("ax.openUsage", () =>
      vscode.commands.executeCommand("ax.panel.focus")
    ),
    vscode.commands.registerCommand("ax.refresh", () => {
      tick()
      void usage.refresh()
    }),
    vscode.commands.registerCommand("ax.newSession", () => panel.focusComposer()),
    vscode.commands.registerCommand("ax.search", () => openSearch(tabs)),
    vscode.commands.registerCommand("ax.searchTab", () => tabs.search()),
    vscode.commands.registerCommand("ax.closeOffScreen", () => {
      const closed = tabs.closeOffScreen()
      void vscode.window.showInformationMessage(
        closed === 1
          ? "Closed 1 session tab that wasn't on screen."
          : closed
            ? `Closed ${closed} session tabs that weren't on screen.`
            : "Every session tab is on screen."
      )
    }),
    vscode.commands.registerCommand("ax.share", () => share()),
    vscode.commands.registerCommand("ax.sharing", () => sharing()),
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
      if (e.affectsConfiguration("ax")) {
        for (const webview of webviewServers.keys())
          void webview.postMessage({ type: "preferences" })
      }
      if (!e.affectsConfiguration("ax.server")) return
      last = null // another server's waiting sessions aren't news, as at start-up
      tick()
      void usage.refresh()
    })
  )
}

export function deactivate() {}

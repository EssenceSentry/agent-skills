# ax sessions for VS Code

Every Claude Code and Codex session ax sees, in a panel in VS Code's right sidebar (the
Secondary Side Bar, where Codex and Copilot sit), each opening as an editor tab: the
app's conversation page, in VS Code's colours, with the message box, streamed replies,
approvals, pictures and job cards. The panel lists the sessions as Codex lists its
chats, those waiting for you first, each with its age, opening beside or showing its
changes on hover, and counts those waiting on its badge. The search button in its title
bar (or ⌃⌘S) opens ax's search at the top centre, where VS Code's own pickers open:
your live sessions until you type, then `ax find` over past conversations and memories,
its keyword matches at once and the rest by meaning a few seconds later; Enter opens a conversation as its session's tab and anything else in
the editor at its line ("Search in a Tab" shows the same search in a tab, by kind). The
share button beside it shares ax through a Cloudflare quick tunnel only while you want:
the link is copied and sent with ntfy, it opens every session, and it stops working
when you stop sharing from the same button. At its foot a box starts a new session, as
Codex's does: the `+` menu and modes, a model of either tool (picking one picks the
tool), and a folder picked under it from the workspace, recent sessions' folders or
anywhere; the session opens in a tab of its own.

A tab looks like the Codex panel rather than the web page: VS Code's font at its size,
one column with no frames, your words in a soft bubble with a date after a pause,
Markdown at Codex's rhythm (its full-width tables included), and the message box with
`+` and a round send button. LaTeX between `\[ … \]`, `\( … \)` or `$$` is typeset
with KaTeX; single dollars stay text. The look lives in `ui/src/vscode.css`, under the
`data-host="vscode"` mark, so the web page keeps its own.

Inside VS Code the tabs also:

- **Say what a working session is doing:** a line under the conversation, as the desktop
  app shows it ("Listing the uncommitted work · 1m 16s"), and the turn's task list with
  each step's state. Claude's come from its transcript: the running tool, its description
  turned into what it is doing, and the desktop app's `update_plan` calls or Claude
  Code's `TodoWrite`. Codex's line is what it last said it would do, or its command; its
  plan arrives only live, so it shows for threads ax holds.

- **Take a message while it works:** as in Claude Code and Codex. Claude reads it at its
  next step, or as its next turn when it was only writing; Codex steers the running turn
  with it (`turn/steer`). Stop sits beside the send button, and what was sent shows above
  the box until the turn ends. Sent while it waits on an approval or a question, the
  message refuses that and says what to do instead.
- **Keep Claude sessions in the Claude app:** a Claude session ax opens or starts joins
  the desktop app's Code sessions at once (the app lists new ones once it has
  restarted), to go on with the app's own tools, the Artifact tool among them. Opening it
  in the app makes ax let go, so two processes never write to it; ax tells its own
  processes from the app's by their ids. Hand back, and ax stopping (a restart
  included), add any session that missed it. ax writes the app's record
  (`claude_app_sessions` in `[paths]` says where) and never edits one the app wrote.

- **Add and set modes from `+`:** files and folders from the workspace (or any, by
  browsing), the code selected in an editor, pictures; plan mode, a goal it keeps
  pursuing, and approve for me. The modes that are on show as chips, a goal shows above
  the box with its progress, and the model and effort are picked beside the send button.
  Claude takes plan mode and approve for me as permission modes, its model at once and
  its effort by restarting between turns, and a goal as `/goal`; Codex takes them with
  its next turn, and a goal through `thread/goal/set`, begun at once.

- **Open files:** a link or a path in code in an answer (`src/a.ts:42`, `/abs/x.py#L3`)
  opens beside the session, at its line; a relative path starts from the session's
  folder, which a closed session's transcript still gives. A web page (`.html`) opens in
  the browser, unless the link names a line in it. Text, and whatever an installed
  editor claims (pictures, media, PDFs with a viewer extension), opens in VS Code;
  anything else in the app the system gives it, and a folder in Finder.
- **Show pictures in a gallery:** the pictures in a message, or the screenshots its tools
  took, open together: arrow keys or thumbnails step through them, and the wheel,
  buttons or a double-click zoom up to eight times, with drag to pan.
- **Answer questions:** a question an agent asks with options (Claude's
  `AskUserQuestion`, Codex's `request_user_input` and its async kind) is a card, each
  question folding to a row; past ones stay folded with their answers. One a session ax
  holds waits on shows by the message box, a question open at a time as the apps step
  through them; Codex's async ones are answered from the conversation by a reply in
  Codex's own form; any other says where to answer it.
- **Show diffs:** the tab's title bar, and each session in the panel, show what the
  session changed with its edit tools in VS Code's multi-file diff, since its latest turn
  began or since the last commit. Edits made through shell commands aren't recorded by
  either tool, so they don't show.
- **Notify:** a notification when a session starts waiting for an approval or a
  question, unless its tab is in front of you (`ax.notifications` turns them off).
- **Offer commands after a slash:** typing `/` in the message box lists, as Codex does,
  ax's own commands (a goal, plan mode, approve for me), then the tool's: Claude's
  commands and skills, or Codex's skills with their scope, filtered as you type, the
  typed letters in bold. Arrow keys move, Enter or Tab picks (`/name ` for Claude,
  `$name ` for a Codex skill), Escape closes. Each tool is asked in the session's folder,
  without a model call.
- **Show usage:** the status bar shows Claude's and Codex's weekly windows, each by its
  tool's mark, with every window and Codex's credits on hover; a click opens the panel,
  which shows each window as the app's usage tiles do, above the sessions. The marks come
  from the two tools' VS Code extensions installed on this Mac: `npm run icons` builds
  them into `media/ax-icons.woff` (packaging runs it), which stays out of the repository.
- **Open a job's card:** a link to a job's page in ax (`/jobs/<key>/`) opens that job's
  card in the conversation; with no card there, a notice says to run `ax job show <key>`.

The extension holds no logic of its own: the panel and the tabs read and act through
the local ax app (`ax serve`, at `ax.server`, by default `http://127.0.0.1:8765`).
Start it with `ax app start`, or keep it running with `ax app service --apply`.

## Install

Not published; build and install it from this folder:

```bash
npm install && npm --prefix ../ui install
npm run install-local
```

Then reload VS Code's window. Uninstall with
`code --uninstall-extension ax-local.ax-sessions`.

## Develop

`npm run verify` type-checks and runs the tests of the parts that hold logic: the
panel's listing (`src/listing.ts`), finding a kept tab (`src/kept.ts`), the tab's HTML
and policy (`src/html.ts`), the requests a tab
may make (`src/bridge.ts`), file links (`src/links.ts`), diffs (`src/changes.ts`),
notices (`src/notify.ts`) and the usage reading (`src/usage.ts`, which bundles the app's
own `ui/src/lib/usage.ts`). The tab's page is `../ui/src/vscode-main.tsx`, built
by `npm run build:page` into `media/webview/`.

## 0.2.0 migration

Version 0.2.0 adds URI-backed session editors, durable drafts/outbox, structured
requests, history/search, change review and provider-history restore. Update the ax
backend environment as well as the VSIX. See [the audit ledger and rollback
instructions](MIGRATION.md) before upgrading a live workspace.

# ax sessions for VS Code

Every Claude Code and Codex session ax sees, in a sidebar of its own, each opening as
an editor tab: the app's conversation page, in VS Code's colours, with the message
box, streamed replies, approvals, pictures and job cards. New sessions start from the
sidebar's `+` in a workspace folder.

Inside VS Code the tabs also:

- **Open files:** a link or a path in code in an answer (`src/a.ts:42`, `/abs/x.py#L3`)
  opens beside the session, at its line; a relative path starts from the session's
  folder.
- **Show diffs:** the tab's title bar, and each session in the sidebar, show what the
  session changed with its edit tools in VS Code's multi-file diff, since its latest turn
  began or since the last commit. Edits made through shell commands aren't recorded by
  either tool, so they don't show.
- **Notify:** a notification when a session starts waiting for an approval or a
  question, unless its tab is in front of you (`ax.notifications` turns them off).
- **Show usage:** the status bar carries the app's gauge, the most used window coloured by
  the most urgent, with every window and Codex's credits on hover.

The extension holds no logic of its own: the sidebar and the tabs read and act through
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
tree (`src/tree.ts`), the tab's HTML and policy (`src/html.ts`), the requests a tab
may make (`src/bridge.ts`), file links (`src/links.ts`), diffs (`src/changes.ts`),
notices (`src/notify.ts`) and the usage reading (`src/usage.ts`, which bundles the app's
own `ui/src/lib/usage.ts`). The tab's page is `../ui/src/vscode-main.tsx`, built
by `npm run build:page` into `media/webview/`.

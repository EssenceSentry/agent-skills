# ax sessions for VS Code

Every Claude Code and Codex session ax sees, in a sidebar of its own, each opening as
an editor tab: the app's conversation page, in VS Code's colours, with the message
box, streamed replies, approvals, pictures and job cards. New sessions start from the
sidebar's `+` in a workspace folder.

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
tree (`src/tree.ts`), the tab's HTML and policy (`src/html.ts`) and the requests a
tab may make (`src/bridge.ts`). The tab's page is `../ui/src/vscode-main.tsx`, built
by `npm run build:page` into `media/webview/`.

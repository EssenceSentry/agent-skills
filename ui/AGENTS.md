# The ax app: notes for coding agents

The browser side of `ax serve`, generated from atelier (monitor, instrument). The
server side is `src/ax/app.py` (state, actions, reader) and `src/ax/serve.py`
(routes, token, live stream) in the repository root.

## Where things are

- `src/App.tsx`: the shell, hash routes (`#/`, `#/notes/<dir>`, `#/read/<path>`),
  the usage band on every screen.
- `src/screens/now.tsx`, `src/screens/reader.tsx`: the two screens.
- `src/lib/ax.ts`: the state's types, `useNow` (server-sent events on `/events`,
  refetched after an action), `act`, and the reader's loaders.
- `src/lib/example.ts`: example data for `npm run dev` and the screenshot check.
  The status badge says "Example data" whenever it is on screen.
- `src/blocks/markdown.tsx`, `src/lib/callouts.ts`: notes as Markdown, Obsidian
  callouts as asides; raw HTML in notes is never rendered.

## Rules

- Every action goes through `POST /api/act`, which calls the same function as its
  CLI command. Each one asks for confirmation, and the guard says it calls Haiku.
- Links between notes are written by the server; `readHref` and `folderHref`
  escape paths exactly as Python's `quote(path, safe="/")` does.
- Colours come from theme tokens only; never edit `theme/`.
- Run `npm run verify`, `npm run build` and `npm run check`, look at the
  screenshots in `checks/`, and commit `src/ax/web/` with the sources.
- Commit messages never credit an AI assistant as an author. Stage explicit
  paths, never `git add -A` or `git add .`.

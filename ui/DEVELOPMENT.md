# Development

## Set up

```bash
npm install --ignore-scripts    # no git hooks: this folder lives inside agent-skills
npx playwright install chromium # once per machine, for the screenshot check
```

## Change it

```bash
npm run dev       # hot reload, with the example data in src/lib/example.ts
npm run verify    # Biome, strict types, theme colours only, unit tests
npm run build     # builds into ../src/ax/web and stamps BUILD
npm run check     # screenshots of Now and the reader, light and dark, desktop and phone
```

Run all four before committing, and commit `src/ax/web/` with the sources:
ax's own tests fail when `src/ax/web/BUILD` doesn't match the sources
(`ui_digest` in `src/ax/app.py`, mirrored by `scripts/stamp.mjs`).

The dev server shows example data. To see the real thing, build and run
`ax serve`; the page knows it is live from a marker `ax serve` adds.

## Theme

`theme` in `app.config.json` picks the direction. The theme package lives in
`theme/` and comes from atelier; don't edit it here.

## Template updates

```bash
uvx copier update --trust --skip-tasks
```

atelier's lefthook setup, its GitHub workflows and its commit-message check were
removed here: hooks would land in agent-skills' git, and workflows in a
subfolder never run. An update may bring them back; remove them again.

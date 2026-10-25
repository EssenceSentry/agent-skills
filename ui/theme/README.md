# @atelier/theme

Three visual directions as design tokens. Components read tokens only, so a
project changes direction without touching component code.

| Direction | Character | Fonts | Accent |
|---|---|---|---|
| `instrument` (default) | Cool white, hairline frames, dense | Instrument Sans, JetBrains Mono | Cobalt |
| `editorial` | Warm paper, serif headlines, printed rules | Newsreader, Hanken Grotesk | Terracotta |
| `console` | Graphite, lit panels, monospace figures | Chivo, Chivo Mono | Violet |

Each direction has light and dark tokens. Status colours (good, warning,
serious, critical) are fixed across directions.

## Use

`vite.config.ts`:

```ts
import { atelierTheme } from "@atelier/theme/vite"

export default defineConfig({ plugins: [react(), tailwindcss(), atelierTheme()] })
```

`src/main.tsx`, before the app's own CSS:

```ts
import "@atelier/theme/direction.css"
```

`src/index.css`, after Tailwind:

```css
@import "@atelier/theme/tailwind.css";
```

## Choosing a direction

Set `theme` in the project's `app.config.json`:

```json
{ "theme": "editorial" }
```

`THEME=<name>` overrides it for one run. Without either, the direction is
`instrument`. `all` bundles every direction so `data-direction` on `<html>` can
switch at runtime; the gallery uses it. A build bundles only the chosen
direction's fonts and tokens, and an unknown name fails the build.

Light or dark follows the viewer's system setting. `data-theme="light"` or
`data-theme="dark"` on `<html>` overrides it either way. Each colour token is a
single `light-dark()` pair, so a direction defines every colour once.

## Artifacts

`ATELIER_TARGET=artifact` builds a page for a claude.ai artifact instead of an
app: one `index.html` holding only page content (the artifact host supplies the
document), with fonts from Google Fonts and all CSS and JavaScript inlined.

## Charts

`@atelier/theme/viz` resolves chart colours from the active tokens:
`readVizTokens()` returns them and `observeTheme(callback)` reports direction or
mode changes. Categorical slots passed the dataviz validator (adjacent pairs on
every slot, all pairs on the first three, both modes). Instrument has six slots,
Console five and Editorial four; past the last slot, fold series into "Other"
or facet instead of cycling.

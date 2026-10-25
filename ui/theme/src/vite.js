import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

export const THEMES = ["instrument", "editorial", "console", "all"]
export const TARGETS = ["app", "artifact"]
export const DIRECTION_IMPORT = "@atelier/theme/direction.css"

const DIRECTIONS = ["instrument", "editorial", "console"]
const here = dirname(fileURLToPath(import.meta.url))

// Artifacts may load stylesheets only from Google Fonts, so they get the same
// families from there instead of the bundled files.
const GOOGLE_FAMILIES = {
  instrument: ["Instrument+Sans:wght@400..700", "JetBrains+Mono:wght@100..800"],
  editorial: [
    "Newsreader:ital,opsz,wght@0,6..72,200..800;1,6..72,200..800",
    "Hanken+Grotesk:wght@100..900",
    "JetBrains+Mono:wght@100..800",
  ],
  console: ["Chivo:wght@100..900", "Chivo+Mono:wght@100..900"],
}

function readConfiguredTheme(root, configFile) {
  try {
    return JSON.parse(readFileSync(resolve(root, configFile), "utf8")).theme
  } catch (error) {
    if (error.code === "ENOENT") return undefined
    throw error
  }
}

function pick(name, value, allowed) {
  if (!allowed.includes(value))
    throw new Error(`Unknown ${name} "${value}". Use one of: ${allowed.join(", ")}.`)
  return value
}

function googleFontLinks(theme) {
  const directions = theme === "all" ? DIRECTIONS : [theme]
  const families = [...new Set(directions.flatMap((d) => GOOGLE_FAMILIES[d]))]
  const href = `https://fonts.googleapis.com/css2?${families.map((f) => `family=${f}`).join("&")}&display=swap`
  return [
    '<link rel="preconnect" href="https://fonts.googleapis.com">',
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
    `<link rel="stylesheet" href="${href}">`,
  ].join("\n")
}

// An inline script ends at the first "</script" and treats "<!--" specially,
// even inside strings; both escapes keep the code's meaning.
const inlineSafe = (code) => code.replace(/<\/(script)/gi, "<\\/$1").replace(/<!--/g, "<\\!--")

/**
 * The project's direction comes from `theme` in app.config.json, THEME=<name>
 * overrides it for one run, and instrument is the default. "all" bundles
 * every direction for the gallery.
 *
 * The target is "app" unless ATELIER_TARGET=artifact. An app bundles its font
 * files. An artifact build writes one index.html holding only page content,
 * since the artifact host supplies the document: title, Google Fonts links,
 * the direction, then inlined CSS, markup and JavaScript.
 */
export function atelierTheme({ configFile = "app.config.json" } = {}) {
  let theme
  let target
  let file
  return {
    name: "atelier-theme",
    // Resolve the direction import before Vite looks for it in package exports.
    enforce: "pre",
    config(userConfig) {
      const root = resolve(userConfig.root ?? process.cwd())
      theme = pick(
        "theme",
        process.env.THEME ?? readConfiguredTheme(root, configFile) ?? "instrument",
        THEMES
      )
      target = pick("target", process.env.ATELIER_TARGET ?? "app", TARGETS)
      file = resolve(here, target === "artifact" ? "directions" : "bundles", `${theme}.css`)
      const config = { define: { __THEME__: JSON.stringify(theme) } }
      if (target === "artifact") {
        config.build = {
          assetsInlineLimit: () => true,
          cssCodeSplit: false,
          modulePreload: false,
          rolldownOptions: { output: { codeSplitting: false } },
        }
      }
      return config
    },
    resolveId(id) {
      if (id === DIRECTION_IMPORT) return file
    },
    transformIndexHtml(html) {
      const direction = theme === "all" ? "instrument" : theme
      return html.replace("<html", `<html data-direction="${direction}"`)
    },
    generateBundle: {
      order: "post",
      handler(_options, bundle) {
        if (target !== "artifact") return
        const html = bundle["index.html"]?.source
        if (typeof html !== "string")
          this.error("The artifact target needs index.html as the entry.")
        const css = []
        const js = []
        for (const [name, output] of Object.entries(bundle)) {
          if (name === "index.html") continue
          if (output.type === "chunk") js.push(output.code)
          else if (name.endsWith(".css")) css.push(String(output.source))
          else this.warn(`Dropped ${name}: artifacts take only inlined CSS and JavaScript.`)
          delete bundle[name]
        }
        const direction = theme === "all" ? "instrument" : theme
        const page = [
          html.match(/<title>[\s\S]*?<\/title>/)?.[0] ?? "",
          googleFontLinks(theme),
          `<script>document.documentElement.dataset.direction = "${direction}"</script>`,
          `<style>${css.join("\n")}</style>`,
          html
            .match(/<body>([\s\S]*?)<\/body>/)[1]
            .replace(/<script[\s\S]*?<\/script>/g, "")
            .trim(),
          `<script type="module">${inlineSafe(js.join("\n"))}</script>`,
        ]
        bundle["index.html"].source = `${page.join("\n")}\n`
      },
    },
  }
}

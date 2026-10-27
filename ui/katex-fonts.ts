import type { Plugin } from "vite"

/**
 * KaTeX's stylesheet offers each font as woff2, woff and ttf. Every browser the app and
 * VS Code run in takes woff2, so the other two are dropped before Vite copies them.
 */
export function katexWoff2Only(): Plugin {
  return {
    name: "katex-woff2-only",
    enforce: "pre",
    transform(code, id) {
      if (!/[\\/]katex[\\/].*\.css$/.test(id)) return null
      return code.replace(/,url\([^)]*\.(?:woff|ttf)\) format\("(?:woff|truetype)"\)/g, "")
    },
  }
}

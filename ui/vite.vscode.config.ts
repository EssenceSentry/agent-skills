import { resolve } from "node:path"
import { atelierTheme } from "@atelier/theme/vite"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { katexWoff2Only } from "./katex-fonts.ts"

// The conversation page for the VS Code extension's tabs: one script and one stylesheet
// with fixed names, which the extension's own HTML loads, and beside them the font files
// and the chunks it loads when needed.
export default defineConfig({
  plugins: [react(), tailwindcss(), atelierTheme(), katexWoff2Only()],
  base: "./",
  // The app's icons, manifest and service worker belong to the web app, not a tab.
  publicDir: false,
  build: {
    outDir: "../vscode/media/webview",
    emptyOutDir: true,
    cssCodeSplit: false,
    // One script, read from disk by VS Code: its size costs no download.
    chunkSizeWarningLimit: 1024,
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
    rolldownOptions: {
      input: resolve(import.meta.dirname, "src/vscode-main.tsx"),
      output: {
        // Lazily loaded code (KaTeX, Mermaid) stays in chunks of its own beside the script,
        // which the tab's policy lets load from the extension's files, so a tab without
        // math or diagrams doesn't parse them.
        entryFileNames: "webview.js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: (asset) =>
          asset.names.some((n) => n.endsWith(".css")) ? "webview.css" : "assets/[name][extname]",
      },
    },
  },
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
})

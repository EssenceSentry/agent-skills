import { resolve } from "node:path"
import { atelierTheme } from "@atelier/theme/vite"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), atelierTheme()],
  // The build ships inside the ax package, which `ax serve` hosts without Node.
  build: {
    outDir: "../src/ax/web",
    emptyOutDir: true,
    // Fonts stay files: the app's Content-Security-Policy refuses data: fonts, and Vite
    // would inline a subset under 4 KB.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
  },
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
})

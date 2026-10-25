// Fail when a component hard-codes a colour instead of using theme tokens.
//   node scripts/check-colours.mjs src
// Tokens keep every screen consistent in all three directions and both
// modes. Wrap deliberate content colours, such as an illustration's, in
// "check-colours: off" and "check-colours: on" comments that say why.
import { readdirSync, readFileSync } from "node:fs"
import { join, relative } from "node:path"

const palette =
  "red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone"
const rules = [
  [/#[0-9a-fA-F]{3,8}\b/, "hex colour"],
  [/\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(/, "colour function"],
  [new RegExp(`\\b[a-z]+(?:-[a-z]+)*-(?:${palette})-\\d{2,3}\\b`), "Tailwind palette colour"],
]

function* sourceFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    // shadcn's generated components follow their own conventions.
    if (entry.isDirectory() && path.endsWith(join("components", "ui"))) continue
    if (entry.isDirectory()) yield* sourceFiles(path)
    else if (/\.(tsx?|css)$/.test(entry.name)) yield path
  }
}

const roots = process.argv.slice(2)
const problems = []
for (const root of roots.length ? roots : ["src"]) {
  for (const file of sourceFiles(root)) {
    let skipping = false
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, index) => {
        if (line.includes("check-colours: off")) skipping = true
        if (line.includes("check-colours: on")) skipping = false
        if (skipping) return
        for (const [pattern, kind] of rules) {
          const match = line.match(pattern)
          if (match) problems.push(`${relative(".", file)}:${index + 1}: ${kind} ${match[0]}`)
        }
      })
  }
}

if (problems.length) {
  console.error(problems.join("\n"))
  console.error("Use theme tokens (bg-card, text-ink-2, var(--series-1) …) instead.")
  process.exit(1)
}

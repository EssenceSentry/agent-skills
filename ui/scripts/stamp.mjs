// Write a digest of the app's sources beside the build, so ax's tests can tell when the
// shipped build is older than the sources. Mirrors `ui_digest` in src/ax/app.py.
import { createHash } from "node:crypto"
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { join, relative, sep } from "node:path"

const SOURCES = [
  "src",
  "public",
  "theme",
  "index.html",
  "package.json",
  "package-lock.json",
  "vite.config.ts",
  "app.config.json",
  "components.json",
  "tsconfig.json",
  "tsconfig.app.json",
  "tsconfig.node.json",
]
const SKIP = new Set(["node_modules", ".DS_Store"])

function* files(path) {
  const stat = statSync(path, { throwIfNoEntry: false })
  if (stat?.isFile()) yield path
  else if (stat?.isDirectory()) {
    for (const name of readdirSync(path)) if (!SKIP.has(name)) yield* files(join(path, name))
  }
}

const found = SOURCES.flatMap((name) => [...files(name)])
  .map((path) => relative(".", path).split(sep).join("/"))
  .sort()
const digest = createHash("sha256")
for (const path of found) {
  digest.update(`${path}\0`)
  digest.update(readFileSync(path))
  digest.update("\0")
}
writeFileSync("../src/ax/web/BUILD", `${digest.digest("hex")}\n`)

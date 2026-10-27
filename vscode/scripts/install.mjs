// Install the packaged extension into VS Code: `node scripts/install.mjs ax-sessions.vsix`.
// Uses `code` from PATH, or the macOS app's own copy when the shell command isn't set up.
import { execFileSync } from "node:child_process"
import { existsSync } from "node:fs"
import { resolve } from "node:path"

const vsix = resolve(process.argv[2] ?? "ax-sessions.vsix")
const app = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
const code = process.env.VSCODE_CLI ?? (existsSync(app) ? app : "code")
execFileSync(code, ["--install-extension", vsix, "--force"], { stdio: "inherit" })
console.log("Installed. Reload VS Code's window (Developer: Reload Window) to start it.")

const vscode = require("vscode")
const fs = require("node:fs")
const assert = require("node:assert/strict")
const path = require("node:path")
const server = process.env.AX_SMOKE_SERVER || "http://127.0.0.1:8799"
const output =
  process.env.AX_SMOKE_OUTPUT || path.join(require("node:os").tmpdir(), "ax-native-smoke.json")
const pause = (ms) => new Promise((r) => setTimeout(r, ms))
const sessions = () =>
  vscode.window.tabGroups.all
    .flatMap((group) => group.tabs)
    .filter((tab) => tab.input instanceof vscode.TabInputCustom)
async function until(fn) {
  for (let n = 0; n < 80; n++) {
    if (fn()) return
    await pause(100)
  }
  throw new Error(
    "Timed out waiting for custom editor identity: " +
      JSON.stringify(sessions().map((t) => ({ label: t.label, uri: t.input.uri.toString() })))
  )
}
exports.run = async () => {
  const phase =
    process.env.AX_SMOKE_PHASE || path.join(require("node:os").tmpdir(), "ax-native-phase.json")
  const result = { restoredBeforeActivation: sessions().map((t) => t.input.uri.toString()) }
  if (fs.existsSync(phase)) {
    const expected = JSON.parse(fs.readFileSync(phase))
    await until(() => sessions().length >= 3)
    result.restoredBeforeActivation = sessions().map((t) => t.input.uri.toString())
    assert(expected.resources.every((uri) => result.restoredBeforeActivation.includes(uri)))
    await vscode.extensions.getExtension("ax-local.ax-sessions").activate()
    for (const group of vscode.window.tabGroups.all)
      for (const tab of [...group.tabs])
        if (tab.input instanceof vscode.TabInputCustom)
          await vscode.commands.executeCommand(
            "vscode.openWith",
            tab.input.uri,
            "ax.sessionEditor",
            { viewColumn: group.viewColumn, preview: false }
          )
    await until(
      () =>
        sessions().length >= 4 &&
        sessions().every((t) => !t.label.endsWith(".axsession") && t.label !== "Loading chat…")
    )
    const restored = sessions().find((t) => t.input.uri.toString() === expected.legacyUri)
    assert(restored, "Legacy serializer did not migrate by ID")
    const group = vscode.window.tabGroups.all.find((g) => g.tabs.includes(restored))
    assert.equal(group.viewColumn, 2)
    const crypto = require("node:crypto")
    const draftKey = `${server}:${expected.legacy.provider}:${expected.legacy.id}`
    const hash = crypto.createHash("sha256").update(draftKey).digest("hex")
    assert(process.env.AX_SMOKE_PROFILE, "Set AX_SMOKE_PROFILE to the disposable --user-data-dir")
    const draftPath = path.join(
      process.env.AX_SMOKE_PROFILE,
      "User/globalStorage/ax-local.ax-sessions",
      `draft-${hash}.json`
    )
    const draft = JSON.parse(fs.readFileSync(draftPath))
    assert.equal(draft.text, "Legacy draft survives migration")
    fs.writeFileSync(
      output,
      JSON.stringify(
        {
          ...expected,
          ...result,
          reload: true,
          legacyMigration: true,
          draftMigration: true,
          ok: true,
        },
        null,
        2
      )
    )
    fs.unlinkSync(phase)
    console.log("AX_NATIVE_RELOAD_OK")
    await vscode.commands.executeCommand("workbench.action.closeWindow")
    return
  }
  await vscode.extensions.getExtension("ax-local.ax-sessions").activate()
  await vscode.window.tabGroups.close(sessions())
  const rows = (await (await fetch(`${server}/api/sessions`)).json()).sessions
  assert(
    rows.length >= 4 && rows.slice(0, 4).every((row) => row.id.startsWith("de300000-")),
    "Use synthetic ax demo sessions only"
  )
  const selected = rows.slice(0, 3)
  for (const row of selected.slice(0, 2))
    await vscode.commands.executeCommand("ax.openSession", row.provider, row.id, "Same title audit")
  await until(() => sessions().length >= 2)
  const resources = selected.map((row) =>
    vscode.Uri.parse(
      `ax-session:/${row.provider}/v1-${Buffer.from(row.id, "utf8").toString("base64url")}.axsession?server=${encodeURIComponent(server)}`
    )
  )
  for (let index = 0; index < 3; index++)
    await vscode.commands.executeCommand("vscode.openWith", resources[index], "ax.sessionEditor", {
      viewColumn: index + 1,
      preview: false,
    })
  await until(() =>
    resources.every((uri) => sessions().some((t) => t.input.uri.toString() === uri.toString()))
  )
  await until(
    () =>
      sessions().length === 3 &&
      sessions().every((t) => !t.label.endsWith(".axsession") && t.label !== "Loading chat…")
  )
  result.resources = sessions().map((t) => ({ uri: t.input.uri.toString(), label: t.label }))
  assert.equal(new Set(result.resources.map((t) => t.uri)).size, 3)
  const duplicate = selected.slice(0, 2).map((r) => resources[selected.indexOf(r)].toString())
  assert(duplicate.every((uri) => result.resources.some((t) => t.uri === uri)))
  result.groups = vscode.window.tabGroups.all.map((group) => ({
    column: group.viewColumn,
    uris: group.tabs
      .filter((t) => t.input instanceof vscode.TabInputCustom)
      .map((t) => t.input.uri.toString()),
  }))
  assert(result.groups.filter((g) => g.uris.length).length >= 3)
  const first = sessions().find((t) => t.input.uri.toString() === resources[0].toString())
  await vscode.window.tabGroups.close(first)
  await vscode.commands.executeCommand("vscode.openWith", resources[0], "ax.sessionEditor", {
    viewColumn: 1,
    preview: false,
  })
  await until(() => sessions().some((t) => t.input.uri.toString() === resources[0].toString()))
  result.closeReopen = true
  const legacy = rows[3]
  // Exercise an identity already restored in a different group.
  await vscode.commands.executeCommand(
    "vscode.openWith",
    vscode.Uri.parse(
      `ax-session:/${legacy.provider}/v1-${Buffer.from(legacy.id, "utf8").toString("base64url")}.axsession?server=${encodeURIComponent(server)}`
    ),
    "ax.sessionEditor",
    { viewColumn: 1, preview: false }
  )
  const panel = vscode.window.createWebviewPanel("ax.session", "Same title audit", 2, {
    enableScripts: true,
    retainContextWhenHidden: true,
  })
  const state = {
    provider: legacy.provider,
    id: legacy.id,
    server,
    draft: { text: "Legacy draft survives migration", refs: [], pictures: [] },
  }
  panel.webview.html = `<html><body><script>acquireVsCodeApi().setState(${JSON.stringify(state)})</script>Legacy tab</body></html>`
  await pause(800)
  result.legacy = legacy
  result.legacyUri = vscode.Uri.parse(
    `ax-session:/${legacy.provider}/v1-${Buffer.from(legacy.id, "utf8").toString("base64url")}.axsession?server=${encodeURIComponent(server)}`
  ).toString()
  fs.writeFileSync(
    phase,
    JSON.stringify({ ...result, resources: result.resources.map((t) => t.uri) })
  )
  console.log("AX_NATIVE_RELOADING")
  await vscode.commands.executeCommand("workbench.action.reloadWindow")
  await new Promise(() => {})
}

exports.activate = () => {
  void exports.run().catch((error) => {
    fs.writeFileSync(output, JSON.stringify({ ok: false, error: error.stack }, null, 2))
    console.error(error)
  })
}

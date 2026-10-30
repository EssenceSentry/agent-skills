import * as vscode from "vscode"
import { readSessionResource } from "./sessionUri"

/** Session resources have identity but no editable file contents. Drafts have their own store. */
export class SessionFiles implements vscode.FileSystemProvider {
  private changes = new vscode.EventEmitter<vscode.FileChangeEvent[]>()
  readonly onDidChangeFile = this.changes.event
  watch() {
    return new vscode.Disposable(() => {})
  }
  stat(uri: vscode.Uri): vscode.FileStat {
    readSessionResource(uri.toString())
    return { type: vscode.FileType.File, ctime: 0, mtime: 0, size: 0 }
  }
  readFile(uri: vscode.Uri) {
    this.stat(uri)
    return new Uint8Array()
  }
  readDirectory(): [string, vscode.FileType][] {
    return []
  }
  createDirectory(): never {
    throw vscode.FileSystemError.NoPermissions("Session resources are read-only")
  }
  writeFile(): never {
    throw vscode.FileSystemError.NoPermissions("Drafts save automatically")
  }
  delete(): never {
    throw vscode.FileSystemError.NoPermissions("Archive the session through ax")
  }
  rename(): never {
    throw vscode.FileSystemError.NoPermissions("Rename the session through ax")
  }
  dispose() {
    this.changes.dispose()
  }
}

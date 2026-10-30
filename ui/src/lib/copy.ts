import { askExtension } from "@/lib/transport"

/** Copy text: through VS Code's own clipboard in the editor, which a webview may not
 * reach itself; the browser's elsewhere. */
export function copyText(text: string, editor: boolean): Promise<void> {
  return editor ? askExtension<void>("copy", { text }) : navigator.clipboard.writeText(text)
}

import { useState } from "react"
import { savePreferences, usePreferences } from "@/lib/preferences"

export function ChatPreferences() {
  const value = usePreferences()
  const [error, setError] = useState<string | null>(null)
  const change = (next: Partial<typeof value>) =>
    void savePreferences({ ...value, ...next }).catch((e: Error) => setError(e.message))
  return (
    <details className="text-xs">
      <summary className="cursor-pointer">Chat preferences</summary>
      <div className="my-2 grid gap-2 rounded border bg-card p-3">
        <label>
          Send with{" "}
          <select
            value={value.sendKey}
            onChange={(e) => change({ sendKey: e.target.value as typeof value.sendKey })}
          >
            <option value="enter">Enter</option>
            <option value="modEnter">⌘/Ctrl+Enter</option>
          </select>
        </label>
        <p>Shift+Enter adds a line. ⌘/Ctrl+Shift+Enter queues the next task.</p>
        <label>
          <input
            type="checkbox"
            checked={value.autoContext}
            onChange={(e) => change({ autoContext: e.target.checked })}
          />{" "}
          Include the current file and selection
        </label>
        <label>
          Chat font{" "}
          <input
            value={value.chatFontFamily}
            placeholder="Use the host font"
            onChange={(e) => change({ chatFontFamily: e.target.value })}
          />
        </label>
        <label>
          Chat size{" "}
          <input
            type="number"
            min={10}
            max={28}
            value={value.chatFontSize}
            onChange={(e) =>
              change({ chatFontSize: Math.max(10, Math.min(28, Number(e.target.value))) })
            }
          />
        </label>
        <label>
          Code size{" "}
          <input
            type="number"
            min={9}
            max={24}
            value={value.codeFontSize}
            onChange={(e) =>
              change({ codeFontSize: Math.max(9, Math.min(24, Number(e.target.value))) })
            }
          />
        </label>
        <label>
          Review display{" "}
          <select
            value={value.reviewMode}
            onChange={(e) => change({ reviewMode: e.target.value as typeof value.reviewMode })}
          >
            <option value="inline">Inline</option>
            <option value="detached">Detached diff</option>
          </select>
        </label>
        {error && <p role="alert">{error}</p>}
      </div>
    </details>
  )
}

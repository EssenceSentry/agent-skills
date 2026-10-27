import { Loader2, Play, X } from "lucide-react"
import { type KeyboardEvent, useId, useState } from "react"

import { AttachButton, ConfirmDialog, PictureTray, usePictures } from "@/blocks/message-input"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { chatAct } from "@/lib/ax"
import { sessionHref } from "@/lib/routes"
import { canStart, PROVIDERS, type Provider } from "@/lib/sessions"
import { cn } from "@/lib/utils"

type Payload = Record<string, unknown>

const HELD = {
  claude:
    "It runs in the background through ax, so the Claude app won't list it; it shows here like any other session.",
  codex: "It runs through ax and joins your Codex threads, so the Codex app can open it later.",
}

/** A session of either tool, started by ax in a folder with its first message. */
export function NewSession({ folders, onClose }: { folders: string[]; onClose: () => void }) {
  const [provider, setProvider] = useState<Provider>("claude")
  const [folder, setFolder] = useState(folders[0] ?? "")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ask, setAsk] = useState<{ question: string; payload: Payload } | null>(null)
  const pictures = usePictures(setError)
  const list = useId()
  const field = useId()

  async function run(payload: Payload) {
    setBusy(true)
    setError(null)
    try {
      const said = await chatAct(payload)
      if (said.confirm) {
        setAsk({
          question: said.question ?? "Confirm?",
          payload: { ...payload, confirm: said.confirm },
        })
        return
      }
      setAsk(null)
      const id = (said as { id?: string }).id
      if (id) window.location.hash = sessionHref(provider, id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const ready = canStart(folder, text, pictures.pictures.length) && !busy
  const start = () =>
    ready &&
    run({
      action: "start",
      provider,
      cwd: folder.trim(),
      text: text.trim(),
      images: pictures.payload(),
    })
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      start()
    }
  }

  return (
    <section className="panel space-y-4 p-4 md:p-5" aria-label="New session">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-medium">New session</h2>
        <Button size="icon-sm" variant="ghost" aria-label="Close" onClick={onClose}>
          <X />
        </Button>
      </div>

      <fieldset className="flex flex-wrap gap-1.5">
        <legend className="sr-only">Tool</legend>
        {PROVIDERS.map((p) => (
          <button
            key={p.provider}
            type="button"
            aria-pressed={provider === p.provider}
            onClick={() => setProvider(p.provider)}
            className={cn(
              "rounded-full px-3 py-1 text-[13px] transition-colors",
              provider === p.provider
                ? "bg-primary-soft font-medium text-primary-ink"
                : "bg-muted text-ink-2 hover:text-foreground"
            )}
          >
            {p.label}
          </button>
        ))}
      </fieldset>

      <div className="space-y-1.5">
        <label htmlFor={field} className="block text-xs text-muted-foreground">
          Folder
        </label>
        <Input
          id={field}
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          list={list}
          placeholder="/Users/me/Repos/project"
          className="label-mono"
          spellCheck={false}
        />
        <datalist id={list}>
          {folders.map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>
      </div>

      <div className="rounded-xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring/40">
        <PictureTray pictures={pictures.pictures} onRemove={pictures.remove} />
        <div className="flex items-end gap-2">
          <AttachButton onFiles={(files) => void pictures.attach(files)} disabled={busy} />
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onPaste={pictures.onPaste}
            onKeyDown={onKey}
            placeholder="What should it do first?"
            aria-label="First message"
            rows={3}
            className="max-h-60 min-h-16 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 text-[11.5px] text-muted-foreground">{HELD[provider]}</p>
        <Button onClick={start} disabled={!ready}>
          {busy ? <Loader2 className="animate-spin" /> : <Play />}
          Start
        </Button>
      </div>
      {error && <p className="text-xs text-critical">{error}</p>}

      <ConfirmDialog
        question={ask?.question ?? null}
        busy={busy}
        onCancel={() => setAsk(null)}
        onYes={() => ask && run(ask.payload)}
      />
    </section>
  )
}

import { Loader2, Play, X } from "lucide-react"
import { type KeyboardEvent, useId, useState } from "react"
import { ReferenceTray } from "@/blocks/composer-tools"
import { ContextPicker } from "@/blocks/context-picker"
import { AttachButton, PictureTray, usePictures } from "@/blocks/message-input"
import { ModelEffortPicker } from "@/blocks/model-picker"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { chatAct, useModels } from "@/lib/ax"
import { useDraft } from "@/lib/drafts"
import { type ModelPick, startingPick } from "@/lib/models"
import { mergeReferences, type Reference, withReferences } from "@/lib/plus"
import { sessionHref } from "@/lib/routes"
import { canStart, PROVIDERS, type Provider } from "@/lib/sessions"
import { cn } from "@/lib/utils"

type Payload = Record<string, unknown>

const HELD = {
  claude:
    "It runs in the background through ax, so the Claude app won't list it; it shows here like any other session.",
  codex: "It runs through ax and joins your Codex threads, so the Codex app can open it later.",
}

/**
 * A session of either tool, started by ax in a folder with its first message, on the
 * model and effort picked from both tools' lists: picking a model picks the tool. Once it
 * starts, its page opens; in VS Code `onStarted` opens its tab instead.
 */
export function NewSession({
  folders,
  onClose,
  onStarted,
}: {
  folders: string[]
  onClose: () => void
  onStarted?: (provider: Provider, id: string, name: string) => void
}) {
  const groups = useModels()
  const [chosenPick, setPick] = useState<ModelPick | null>(null)
  const pick = chosenPick ?? startingPick(groups)
  const provider = pick.provider
  const setProvider = (p: Provider) => setPick({ provider: p, model: null, effort: null })
  const [folder, setFolder] = useState(folders[0] ?? "")
  const [draft, setDraft, draftError] = useDraft(`new:card:${folder}`)
  const text = draft.text
  const setText = (text: string) => setDraft((was) => ({ ...was, text }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pictures = usePictures(setError, {
    pictures: draft.pictures,
    set: (change) =>
      setDraft((was) => ({
        ...was,
        pictures: typeof change === "function" ? change(was.pictures) : change,
      })),
  })
  const list = useId()
  const field = useId()

  async function run(payload: Payload) {
    setBusy(true)
    setError(null)
    try {
      const signature = JSON.stringify(payload)
      const start =
        draft.start?.signature === signature ? draft.start : { signature, id: crypto.randomUUID() }
      setDraft((was) => ({ ...was, start }))
      const said = await chatAct({ ...payload, client_message_id: start.id })
      setDraft((was) =>
        was.text === text ? { ...was, text: "", refs: [], pictures: [], start: undefined } : was
      )
      const id = (said as { id?: string }).id
      // ax names it by its first line; the tab can show that before the listing does.
      const name = text.trim().split("\n")[0]?.slice(0, 60) || "New session"
      if (id && onStarted) onStarted(provider, id, name)
      else if (id) window.location.hash = sessionHref(provider, id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const ready = canStart(folder, text, pictures.pictures.length + draft.refs.length) && !busy
  const start = () =>
    ready &&
    run({
      action: "start",
      provider,
      cwd: folder.trim(),
      text: withReferences(text, draft.refs),
      images: pictures.payload(),
      model: pick.model,
      effort: pick.effort,
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

      {/* Until both tools have listed their models, the tool alone. */}
      {groups.length === 0 && (
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
      )}

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
        <ReferenceTray
          refs={draft.refs}
          onRemove={(index) =>
            setDraft((was) => ({ ...was, refs: was.refs.filter((_, n) => n !== index) }))
          }
        />
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
        {groups.length > 0 && (
          <div className="flex justify-end">
            <ModelEffortPicker groups={groups} pick={pick} onPick={setPick} disabled={busy} />
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 text-[11.5px] text-muted-foreground">{HELD[provider]}</p>
        <Button onClick={start} disabled={!ready}>
          {busy ? <Loader2 className="animate-spin" /> : <Play />}
          Start
        </Button>
      </div>
      <ContextPicker
        text={text}
        setText={setText}
        cwd={folder}
        add={(found: Reference[]) =>
          setDraft((was) => ({
            ...was,
            refs: mergeReferences(was.refs, found),
          }))
        }
      />
      {draftError && <p className="text-xs text-critical">{draftError}</p>}
      {error && <p className="text-xs text-critical">{error}</p>}
      {error?.includes("already starting") && (
        <button
          type="button"
          className="text-xs underline"
          onClick={() => {
            setDraft((was) => ({ ...was, start: undefined }))
            setError(null)
          }}
        >
          Use a new start ID (may create a duplicate chat)
        </button>
      )}
    </section>
  )
}

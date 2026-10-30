import { ImagePlus, Plus, X } from "lucide-react"
import { type ClipboardEvent, useContext, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { EditorLook } from "@/lib/host"
import { type Pasted, prepare } from "@/lib/images"

/** Pictures for a message: pasted or attached, shrunk to send, removable before sending. */
export function usePictures(
  onError: (message: string) => void,
  controlled?: {
    pictures: Pasted[]
    set: (change: Pasted[] | ((was: Pasted[]) => Pasted[])) => void
  }
) {
  const [local, setLocal] = useState<Pasted[]>([])
  const pictures = controlled?.pictures ?? local
  const setPictures = controlled?.set ?? setLocal

  async function attach(files: File[]) {
    const images = files.filter((f) => f.type.startsWith("image/"))
    if (!images.length) return
    try {
      const ready = await Promise.all(images.map(prepare))
      setPictures((was) => [...was, ...ready].slice(0, 10))
    } catch (e) {
      onError((e as Error).message)
    }
  }

  // Pasting a picture attaches it; pasting text stays text.
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files)
    if (files.some((f) => f.type.startsWith("image/"))) {
      e.preventDefault()
      void attach(files)
    }
  }

  return {
    pictures,
    attach,
    onPaste,
    remove: (i: number) => setPictures((was) => was.filter((_, j) => j !== i)),
    clear: () => setPictures([]),
    /** What the server takes: each picture's type and data. */
    payload: () => pictures.map(({ media, data }) => ({ media, data })),
  }
}

export function PictureTray({
  pictures,
  onRemove,
}: {
  pictures: Pasted[]
  onRemove: (i: number) => void
}) {
  if (!pictures.length) return null
  return (
    <ul className="flex flex-wrap gap-2 px-1 pt-1 pb-2" aria-label="Pictures to send">
      {pictures.map((picture, i) => (
        <li key={picture.preview} className="relative">
          <img
            src={picture.preview}
            alt=""
            className="h-16 w-auto rounded-md border object-cover"
          />
          <button
            type="button"
            aria-label={`Remove picture ${i + 1}`}
            onClick={() => onRemove(i)}
            className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full border bg-card text-muted-foreground shadow-sm hover:text-foreground"
          >
            <X className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  )
}

/** A button that opens the file picker for pictures; handy on a phone, where nothing pastes. */
export function AttachButton({
  onFiles,
  disabled,
}: {
  onFiles: (files: File[]) => void
  disabled?: boolean
}) {
  const picker = useRef<HTMLInputElement>(null)
  const AttachIcon = useContext(EditorLook) ? Plus : ImagePlus
  return (
    <>
      <Button
        size="icon"
        variant="ghost"
        aria-label="Attach pictures"
        className="chat-attach"
        title="Attach pictures (or paste them)"
        onClick={() => picker.current?.click()}
        disabled={disabled}
      >
        <AttachIcon />
      </Button>
      <input
        ref={picker}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => {
          onFiles(Array.from(e.target.files ?? []))
          e.target.value = ""
        }}
      />
    </>
  )
}

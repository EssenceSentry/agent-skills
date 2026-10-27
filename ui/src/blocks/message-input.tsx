import { ImagePlus, Loader2, Plus, X } from "lucide-react"
import { type ClipboardEvent, useContext, useRef, useState } from "react"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { EditorHost } from "@/lib/host"
import { type Pasted, prepare } from "@/lib/images"

/** Pictures for a message: pasted or attached, shrunk to send, removable before sending. */
export function usePictures(onError: (message: string) => void) {
  const [pictures, setPictures] = useState<Pasted[]>([])

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
  const AttachIcon = useContext(EditorHost) ? Plus : ImagePlus
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

/** The second yes a shared link asks for, with the server's own question. */
export function ConfirmDialog({
  question,
  busy,
  onCancel,
  onYes,
}: {
  question: string | null
  busy: boolean
  onCancel: () => void
  onYes: () => void
}) {
  return (
    <AlertDialog open={question !== null} onOpenChange={(open) => !open && !busy && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Confirm from the shared link</AlertDialogTitle>
          <AlertDialogDescription className="whitespace-pre-wrap">
            {question}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <Button onClick={onYes} disabled={busy}>
            {busy && <Loader2 className="animate-spin" />}
            Yes, do it
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

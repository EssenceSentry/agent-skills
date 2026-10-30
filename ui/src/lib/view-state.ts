import { type RefObject, useEffect } from "react"
import { type Draft, readDraft, writeDraft } from "./drafts"
import { transportIdentity } from "./transport"

/** Navigation state stays separate from the composer so neither overwrites the other. */
export function useViewState(
  root: RefObject<HTMLElement | null>,
  identity: string,
  ready: boolean
) {
  useEffect(() => {
    const element = root.current
    if (!element || !ready) return
    const key = `${transportIdentity()}:view:${identity}`
    let saved: Draft = { text: "", refs: [], pictures: [] }
    let active = true,
      loaded = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const save = () => {
      if (!loaded) return
      const opened = [
        ...element.querySelectorAll<HTMLDetailsElement>("details[data-view-key][open]"),
      ].map((node) => node.dataset.viewKey)
      saved = {
        ...saved,
        ui: { ...saved.ui, scroll: String(window.scrollY), opened: JSON.stringify(opened) },
      }
      void writeDraft(key, saved).catch(() => {})
    }
    const changed = () => {
      clearTimeout(timer)
      timer = setTimeout(save, 200)
    }
    void readDraft(key)
      .then((draft) => {
        if (!active) return
        saved = draft
        const opened = new Set<string>(JSON.parse(String(draft.ui?.opened ?? "[]")))
        for (const node of element.querySelectorAll<HTMLDetailsElement>("details[data-view-key]"))
          node.open = opened.has(node.dataset.viewKey ?? "")
        if (draft.ui?.scroll) window.scrollTo(0, Number(draft.ui.scroll))
        loaded = true
      })
      .catch(() => {
        loaded = true
      })
    window.addEventListener("scroll", changed, { passive: true })
    element.addEventListener("toggle", changed, true)
    return () => {
      active = false
      clearTimeout(timer)
      save()
      window.removeEventListener("scroll", changed)
      element.removeEventListener("toggle", changed, true)
    }
  }, [root, identity, ready])
}

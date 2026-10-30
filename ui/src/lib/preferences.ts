import { useEffect, useState } from "react"
import { askExtension, inExtension } from "./transport"

export type Preferences = {
  sendKey: "enter" | "modEnter"
  autoContext: boolean
  chatFontFamily: string
  chatFontSize: number
  codeFontSize: number
  reviewMode: "inline" | "detached"
}
export const defaults: Preferences = {
  sendKey: "enter",
  autoContext: true,
  chatFontFamily: "",
  chatFontSize: 14,
  codeFontSize: 12,
  reviewMode: "inline",
}
let current = defaults

export async function savePreferences(value: Preferences) {
  if (inExtension()) await askExtension("preferencesWrite", value)
  else localStorage.setItem("ax.preferences", JSON.stringify(value))
  current = value
  window.dispatchEvent(new Event("ax:preferences"))
}

export function usePreferences() {
  const [value, setValue] = useState(current)
  useEffect(() => {
    let active = true
    const apply = (found: Preferences) => {
      if (!active) return
      current = { ...defaults, ...found }
      setValue(current)
      document.documentElement.style.setProperty("--ax-chat-font-size", `${current.chatFontSize}px`)
      document.documentElement.style.setProperty("--ax-code-font-size", `${current.codeFontSize}px`)
      if (current.chatFontFamily)
        document.documentElement.style.setProperty("--ax-chat-font-family", current.chatFontFamily)
      else document.documentElement.style.removeProperty("--ax-chat-font-family")
    }
    if (inExtension()) void askExtension<Preferences>("preferences").then(apply, () => {})
    else {
      try {
        apply(JSON.parse(localStorage.getItem("ax.preferences") ?? "{}"))
      } catch {
        apply(defaults)
      }
    }
    const changed = () => {
      if (inExtension()) void askExtension<Preferences>("preferences").then(apply, () => {})
      else apply(current)
    }
    window.addEventListener("ax:preferences", changed)
    return () => {
      active = false
      window.removeEventListener("ax:preferences", changed)
    }
  }, [])
  return value
}

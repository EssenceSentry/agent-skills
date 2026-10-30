import { createContext } from "react"

/** True when the page runs in an editor's tab, which can open the files answers name. */
export const EditorHost = createContext(false)

/** True when the conversation is drawn in the editor's manner, as Codex's panel draws it:
 * the + menu, the modes and the model in the message box, a round send, a date over a
 * message after a pause. The web page draws it so too, without an editor behind it. */
export const EditorLook = createContext(false)

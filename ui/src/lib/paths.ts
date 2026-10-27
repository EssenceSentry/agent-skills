// A path: optionally rooted (/, ~/, ./, ../), then segments of name characters, with an
// optional :line or :line:col at the end.
const PATH = /^(?:~\/|\.{1,2}\/|\/)?(?:[\w.@-]+\/)*[\w.@-]*(?::\d+){0,2}$/
const EXTENSION = /\.[A-Za-z][\w-]{0,9}(?::\d+){0,2}$/

/**
 * Whether inline code names a file or folder: a path with a slash, or a file name with an
 * extension. Commands, addresses, versions and import aliases don't.
 */
export function looksLikePath(text: string): boolean {
  if (!text || !PATH.test(text) || text.startsWith("@/") || text.startsWith("-")) return false
  const bare = text.replace(/(?::\d+){1,2}$/, "")
  const segments = bare.split("/").filter((s) => s && s !== "." && s !== "..")
  if (!segments.length || segments.every((s) => /^[\d.]+$/.test(s))) return false
  if (bare.includes("/")) return segments.some((s) => /[A-Za-z]/.test(s))
  return EXTENSION.test(bare) && !/^v?\d/.test(bare) && /[A-Za-z]{2}/.test(bare.split(".")[0] ?? "")
}

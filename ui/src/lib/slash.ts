/** The / menu of a session's message box: what is typed after the slash, and how well
 * each command or skill matches it. */

export type SlashItem = {
  action?: string
  name: string
  title: string
  description: string
  /** What the command takes after its name, as its tool words it. */
  hint: string
  /** What picking it puts in the box: `/name ` for Claude, `$name ` for a Codex skill. */
  insert: string
  /** Where a skill comes from: Personal, Project. */
  scope: string | null
}

export type Ranked<T> = { item: T; marks: number[] }

/** What the menu looks for: the word after a slash that starts the box, until a space. */
export function slashQuery(text: string): string | null {
  return /^\/(\S*)$/.exec(text)?.[1] ?? null
}

const span = (from: number, length: number) => Array.from({ length }, (_, k) => from + k)

/** How well `text` matches `query`: 0 it starts with it, 1 a word does, 2 it holds it,
 * 3 its letters come in order; with the places matched. */
function match(text: string, query: string): { score: number; at: number; marks: number[] } | null {
  const lower = text.toLowerCase()
  const index = lower.indexOf(query)
  if (index === 0) return { score: 0, at: 0, marks: span(0, query.length) }
  for (let i = 1; i < lower.length; i++)
    if (" -_:/".includes(lower[i - 1] ?? "") && lower.startsWith(query, i))
      return { score: 1, at: i, marks: span(i, query.length) }
  if (index > 0) return { score: 2, at: index, marks: span(index, query.length) }
  const marks: number[] = []
  let from = 0
  for (const letter of query) {
    const found = lower.indexOf(letter, from)
    if (found < 0) return null
    marks.push(found)
    from = found + 1
  }
  return { score: 3, at: marks[0] ?? 0, marks }
}

/**
 * The items that match what is typed, best first: a title that starts with it, then one
 * with a word that does, then one holding it, then one with its letters in order, and
 * last one whose name matches though its title doesn't. Ties keep the earlier match,
 * then the tool's order. Nothing typed lists everything.
 */
export function rankSlash<T extends { title: string; name: string }>(
  items: T[],
  query: string
): Ranked<T>[] {
  const wanted = query.toLowerCase()
  if (!wanted) return items.map((item) => ({ item, marks: [] }))
  const scored: { item: T; marks: number[]; score: number; at: number; order: number }[] = []
  items.forEach((item, order) => {
    if (item.name.toLowerCase() === wanted) {
      scored.push({ item, marks: [], score: -1, at: 0, order })
      return
    }
    const titled = match(item.title, wanted)
    const named = titled ? null : match(item.name, wanted)
    if (titled)
      scored.push({ item, marks: titled.marks, score: titled.score, at: titled.at, order })
    else if (named) scored.push({ item, marks: [], score: 4, at: named.at, order })
  })
  scored.sort((a, b) => a.score - b.score || a.at - b.at || a.order - b.order)
  return scored.map(({ item, marks }) => ({ item, marks }))
}

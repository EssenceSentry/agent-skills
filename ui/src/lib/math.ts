// Code as written stays as written: fenced blocks and inline code spans.
const CODE = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g

function convert(text: string): string {
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, tex: string) => `\n$$\n${tex.trim()}\n$$\n`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, tex: string) => `$$${tex.trim()}$$`)
}

/**
 * Agents write LaTeX between `\[ … \]` and `\( … \)`, which Markdown would read as
 * escaped brackets; the math parser reads `$$`, on its own lines for a display and within
 * a line for inline math. Single dollars stay text, since answers quote amounts.
 */
export function mathDelimiters(text: string): string {
  return text
    .split(CODE)
    .map((part, i) => (i % 2 ? part : convert(part)))
    .join("")
}

import type { Blockquote, Paragraph, PhrasingContent, Root } from "mdast"

// `> [!type]` opens an Obsidian callout; `+` or `-` after it marks one that folds.
const MARKER = /^\[!([A-Za-z][\w-]*)\][+-]?[ \t]*/

type Parent = { type: string; children?: Parent[] }

/** A remark plugin: Obsidian callouts become `<aside class="callout">` with a title. */
export function remarkCallouts() {
  return (tree: Root) => walk(tree as unknown as Parent)
}

function walk(node: Parent) {
  for (const child of node.children ?? []) {
    if (child.type === "blockquote") convert(child as unknown as Blockquote)
    walk(child)
  }
}

function convert(quote: Blockquote) {
  const first = quote.children[0]
  if (first?.type !== "paragraph") return
  const lead = first.children[0]
  if (lead?.type !== "text") return
  const match = MARKER.exec(lead.value)
  if (!match) return
  const type = match[1].toLowerCase()
  lead.value = lead.value.slice(match[0].length)

  // The rest of the marker's line is the title; what follows is the body.
  const title: PhrasingContent[] = []
  const body: PhrasingContent[] = []
  let inBody = false
  for (const node of first.children) {
    if (inBody) body.push(node)
    else if (node.type === "break") inBody = true
    else if (node.type === "text" && node.value.includes("\n")) {
      const at = node.value.indexOf("\n")
      if (node.value.slice(0, at)) title.push({ type: "text", value: node.value.slice(0, at) })
      if (node.value.slice(at + 1)) body.push({ type: "text", value: node.value.slice(at + 1) })
      inBody = true
    } else title.push(node)
  }
  const last = title[title.length - 1]
  if (last?.type === "text") last.value = last.value.trimEnd()
  const named = title.some((n) => n.type !== "text" || n.value.trim())
  const heading: Paragraph = {
    type: "paragraph",
    children: named ? title : [{ type: "text", value: type[0].toUpperCase() + type.slice(1) }],
    data: { hName: "div", hProperties: { className: ["callout-title"] } },
  }
  const opening: Paragraph[] = body.length ? [{ type: "paragraph", children: body }] : []
  quote.children = [heading, ...opening, ...quote.children.slice(1)]
  quote.data = {
    ...quote.data,
    hName: "aside",
    hProperties: { className: ["callout"], "data-callout": type },
  }
}

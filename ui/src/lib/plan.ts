import { askExtension } from "@/lib/transport"

const HEADING = /^#{1,6}\s+(.+?)\s*#*\s*$/m
const LONGEST = 57 // characters of a name before ".md"

/** A plan's file name, from its first heading: "## Plan: themed charts" is
 * plan-themed-charts.md; a plan without a heading is plan.md. */
export function planFile(plan: string): string {
  const heading = HEADING.exec(plan)?.[1] ?? ""
  const words = heading.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []
  if (words[0] === "plan") words.shift()
  let name = ["plan", ...words].join("-")
  while (name.length > LONGEST) name = name.slice(0, name.lastIndexOf("-"))
  return `${name}.md`
}

/** The plan in a Markdown tab of its own, beside the session's, named as saving it would
 * name it, in the session's folder. */
export function openPlanBeside(plan: string, cwd?: string | null): Promise<void> {
  return askExtension<void>("openMarkdown", { text: plan, name: planFile(plan), cwd })
}

/**
 * Save the plan as a Markdown file: in VS Code through its save dialog, from the session's
 * folder, and on the web as a download. Where it went, or null when the dialog was
 * dismissed.
 */
export async function savePlan(
  plan: string,
  { editor, cwd }: { editor: boolean; cwd?: string | null }
): Promise<string | null> {
  const name = planFile(plan)
  if (editor) return askExtension<string | null>("saveMarkdown", { text: plan, name, cwd })
  const url = URL.createObjectURL(new Blob([plan], { type: "text/markdown" }))
  const link = Object.assign(document.createElement("a"), { href: url, download: name })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
  return name
}

/** A job's details, as its page reads them from `/jobs/<key>/api/job`. No imports, so the
 * VS Code extension can bundle this file as it is. */

export type JobEvent = { ts: string; type: string; data: Record<string, unknown> }

export type JobDetail = {
  key: string
  label: string | null
  kind: string
  ref: string | null
  status: string
  stage: string | null
  message: string | null
  check_error: string | null
  created: string
  updated: string
  finished: string | null
  done: number | null
  total: number | null
  unit: string | null
  progress_text: string
  console_url: string | null
  eta: { text: string; basis?: string } | null
  events: JobEvent[]
  looks: { at: string; summary: string; problem?: string | null }[]
  check_every: number | null
  /** The output's last lines, when the job shares them. */
  log?: string
}

/** What an event says, in the words the job's page uses. */
export function describeJobEvent(event: JobEvent): string {
  const d = event.data ?? {}
  const said = (key: string) => String(d[key] ?? "")
  switch (event.type) {
    case "created":
      return "registered"
    case "status":
      return `status: ${said("status")}${d.message ? ` (${said("message")})` : ""}`
    case "stage":
      return `stage: ${said("stage")}`
    case "message":
      return said("message")
    case "check_error":
      return `check failed: ${said("error")}`
    case "notified":
      return `sent: ${said("title")}`
    case "notify_failed":
      return `not sent: ${said("title")}`
    case "woke":
      return `woke the ${said("agent")} session`
    case "wake_failed":
      return `could not wake: ${said("error")}`
    default:
      return `${event.type} ${JSON.stringify(d)}`
  }
}

/** Where a card's job keeps its details: beside its page. */
export const detailPath = (page: string) => `${page.replace(/\/?$/, "/")}api/job`

/** The job a link to its page in the ax app names, `/jobs/<key>/`: its card shows it. */
export function jobKey(href: string): string | null {
  const found = href.match(/^\/jobs\/([^/?#]+)\/?$/)
  if (!found?.[1]) return null
  try {
    return decodeURIComponent(found[1])
  } catch {
    return null
  }
}

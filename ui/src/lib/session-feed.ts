import { mergePage, openQuestions, type SessionView } from "./sessions"

export type FeedState = { data?: SessionView; error?: string; at?: string }
type Load = (query: string) => Promise<SessionView>

/** One request and one timer per observed session, including refreshes during a load. */
export class SessionFeed {
  state: FeedState = {}
  private listeners = new Set<(state: FeedState) => void>()
  private timer: ReturnType<typeof setTimeout> | undefined
  private loading = false
  private urgent = false
  private idleWaiters: (() => void)[] = []
  visible = true

  private load: Load
  private idle: number
  private busy: number
  constructor(load: Load, idle = 3000, busy = 1000) {
    this.load = load
    this.idle = idle
    this.busy = busy
  }

  subscribe(listener: (state: FeedState) => void) {
    this.listeners.add(listener)
    listener(this.state)
    void this.refresh()
    return () => {
      this.listeners.delete(listener)
      if (!this.listeners.size) clearTimeout(this.timer)
    }
  }

  private publish(state: FeedState) {
    this.state = state
    for (const listener of this.listeners) listener(state)
  }

  async refresh() {
    clearTimeout(this.timer)
    if (!this.listeners.size || !this.visible) return
    if (this.loading) {
      this.urgent = true
      return
    }
    this.loading = true
    try {
      const shown = this.state.data
      const questions = shown
        ? [
            ...new Set([
              ...openQuestions(shown),
              ...shown.events
                .filter((event) => event.kind === "tool" && event.ok === null)
                .map((event) => event.i),
            ]),
          ]
        : []
      const page = await this.load(
        `tools=1&after=${shown?.next ?? 0}${shown?.cursor ? `&cursor=${encodeURIComponent(shown.cursor)}` : ""}${questions.length ? `&again=${questions.join(",")}` : ""}`
      )
      const merged = shown && !page.reset ? mergePage(shown, page) : page
      this.publish({
        data: {
          ...page,
          events: merged.events,
          running: merged.running,
          shots: merged.shots,
          next: merged.next,
          first: shown && !page.reset ? shown.first : page.first,
          earlier: shown && !page.reset ? shown.earlier : page.earlier,
        },
        at: new Date().toISOString(),
      })
    } catch (error) {
      this.publish({ ...this.state, error: (error as Error).message })
    } finally {
      this.loading = false
      for (const done of this.idleWaiters.splice(0)) done()
      if (this.listeners.size && this.visible) {
        const delay = this.urgent ? 0 : this.state.data?.chat?.busy ? this.busy : this.idle
        this.urgent = false
        this.timer = setTimeout(() => void this.refresh(), delay)
      }
    }
  }

  visibility(visible: boolean) {
    if (this.visible === visible) return
    this.visible = visible
    clearTimeout(this.timer)
    if (visible) void this.refresh()
  }

  async earlier() {
    while (this.loading) await new Promise<void>((done) => this.idleWaiters.push(done))
    const shown = this.state.data
    if (!shown?.earlier || !this.listeners.size) return
    clearTimeout(this.timer)
    this.loading = true
    try {
      const page = await this.load(`tools=1&before=${shown.first}`)
      const current = this.state.data ?? shown
      const events = [...page.events, ...current.events].filter(
        (e, i, all) => all.findIndex((v) => v.i === e.i) === i
      )
      this.publish({
        ...this.state,
        data: { ...current, events, first: page.first, earlier: page.earlier },
      })
    } catch (error) {
      this.publish({ ...this.state, error: (error as Error).message })
    } finally {
      this.loading = false
      for (const done of this.idleWaiters.splice(0)) done()
      if (this.listeners.size && this.visible) {
        this.urgent = false
        this.timer = setTimeout(() => void this.refresh(), 0)
      }
    }
  }
}

import { describe, expect, it } from "vitest"

import { parseRoute, sessionHref } from "@/lib/routes"
import {
  type Card,
  type ChatState,
  canSend,
  composerMode,
  groupSessions,
  mergePage,
  runningNow,
  type Session,
  shownCards,
  stateBadge,
  type TranscriptEvent,
  type TranscriptPage,
} from "@/lib/sessions"

const session = (over: Partial<Session> = {}): Session => ({
  provider: "claude",
  id: "s-1",
  name: "fetch",
  cwd: "/Users/me/Repos/demo",
  project: "demo",
  state: "idle",
  waiting_for: null,
  kind: "interactive",
  started: null,
  updated: null,
  last: null,
  jobs: 0,
  ...over,
})

const card = (key: string): Card => ({
  key,
  label: key,
  kind: "run",
  status: "running",
  stage: null,
  message: null,
  progress: { done: null, total: null, unit: null, percent: null, text: "-" },
  eta: null,
  look: null,
  notebook: null,
  attention: null,
  page: `/jobs/${key}/`,
  updated: "2026-10-26T20:00:00+00:00",
})

describe("sessions", () => {
  it("routes to the list and to one session", () => {
    expect(parseRoute("#/sessions")).toEqual({ screen: "sessions" })
    expect(parseRoute("#/sessions/claude/2e065b04-622e")).toEqual({
      screen: "session",
      provider: "claude",
      id: "2e065b04-622e",
    })
    expect(sessionHref("codex", "01a1 79d2")).toBe("#/sessions/codex/01a1%2079d2")
    expect(parseRoute(sessionHref("codex", "01a1 79d2"))).toEqual({
      screen: "session",
      provider: "codex",
      id: "01a1 79d2",
    })
  })

  it("shows a session's job cards only while it isn't thinking", () => {
    const cards = [card("score")]
    expect(shownCards(session({ state: "working" }), cards)).toEqual([])
    expect(shownCards(session({ state: "idle" }), cards)).toEqual(cards)
    expect(shownCards(session({ state: "waiting" }), cards)).toEqual(cards)
    expect(shownCards(null, cards)).toEqual(cards)
  })

  it("keeps a card whose agent never heard of its failure, even while it works", () => {
    const lost = { ...card("lost"), status: "failed", attention: "ax couldn't reach the agent" }
    expect(shownCards(session({ state: "working" }), [card("score"), lost])).toEqual([lost])
  })

  it("groups sessions by tool, in the order the server sorted them", () => {
    const groups = groupSessions([
      session({ id: "a" }),
      session({ provider: "codex", id: "b" }),
      session({ id: "c" }),
    ])
    expect(groups.map((g) => [g.label, g.sessions.map((s) => s.id)])).toEqual([
      ["Claude Code", ["a", "c"]],
      ["Codex", ["b"]],
    ])
    expect(groupSessions([session()]).map((g) => g.provider)).toEqual(["claude"])
  })

  it("names each state in words, with what a waiting session needs", () => {
    expect(stateBadge(session({ state: "working" }))).toEqual({
      status: "running",
      label: "Working",
    })
    expect(stateBadge(session({ state: "waiting", waiting_for: "approval" }))).toEqual({
      status: "warning",
      label: "Needs approval",
    })
    expect(stateBadge(session({ state: "waiting", waiting_for: "input needed" }))).toEqual({
      status: "warning",
      label: "Waiting for you",
    })
    expect(stateBadge(session({ state: "idle" }))).toEqual({ status: "paused", label: "Idle" })
  })

  it("adds new transcript events to the ones on screen", () => {
    const event = (i: number) => ({
      i,
      kind: "assistant",
      text: `e${i}`,
      tool: null,
      ok: null,
      output: "",
      ts: null,
    })
    const page = (events: TranscriptEvent[], next: number, first: number): TranscriptPage => ({
      events,
      next,
      first,
      running: [],
      earlier: 0,
    })
    const first = page([event(8), event(9)], 10, 8)
    const more = page([event(12)], 13, 10) // 10 and 11 were commands, left out
    expect(mergePage(first, more).events.map((e) => e.i)).toEqual([8, 9, 12])
    expect(mergePage(first, more).next).toBe(13)
    expect(mergePage(first, page([], 10, 10))).toBe(first)
    const restarted = page([event(0)], 1, 0)
    expect(mergePage(first, restarted)).toEqual(restarted) // the file was replaced
  })

  it("shows the command running now only while the session works, and only the latest", () => {
    const tool = {
      i: 11,
      kind: "tool",
      text: "ran `make lint`",
      tool: "Bash",
      ok: null,
      output: "",
      ts: null,
    }
    const shown: TranscriptPage = { events: [], next: 12, first: 0, running: [], earlier: 0 }
    const now: TranscriptPage = { ...shown, running: [tool] }
    expect(mergePage(shown, now).running).toEqual([tool])
    expect(mergePage(now, { ...shown, next: 13, first: 12 }).running).toEqual([]) // it finished
    expect(runningNow(session({ state: "working" }), now)).toEqual(tool)
    expect(runningNow(session({ state: "idle" }), now)).toBeNull()
  })
})

describe("the composer", () => {
  const chat = (over: Partial<ChatState> = {}): ChatState => ({
    holder: null,
    can_send: true,
    take_over: false,
    pending: false,
    busy: false,
    partial: "",
    approval: null,
    error: null,
    note: "",
    ...over,
  })

  it("offers what the session allows now", () => {
    expect(composerMode(chat())).toBe("send")
    expect(composerMode(chat({ holder: "ax", busy: true, can_send: false }))).toBe("busy")
    expect(composerMode(chat({ holder: "elsewhere", can_send: false, take_over: true }))).toBe(
      "take-over"
    )
    expect(
      composerMode(chat({ holder: "elsewhere", can_send: false, take_over: true, pending: true }))
    ).toBe("waiting")
  })

  it("sends words or pictures, and only when it may", () => {
    expect(canSend(chat(), "  hi ")).toBe(true)
    expect(canSend(chat(), "   ")).toBe(false)
    expect(canSend(chat(), "", 1)).toBe(true) // a picture alone is a message
    expect(canSend(chat({ busy: true, can_send: false }), "hi")).toBe(false)
  })

  it("keeps the latest screenshots still waiting for an answer", () => {
    const shot = { url: "/api/session/image?line=3&n=0", media: "image/png", line: 3, n: 0 }
    const shown: TranscriptPage = { events: [], next: 4, first: 0, running: [], earlier: 0 }
    expect(mergePage(shown, { ...shown, shots: [shot] }).shots).toEqual([shot])
    expect(mergePage({ ...shown, shots: [shot] }, { ...shown, next: 6, first: 4 }).shots).toEqual(
      []
    )
  })
})

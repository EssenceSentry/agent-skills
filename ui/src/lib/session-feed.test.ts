import { afterEach, describe, expect, it, vi } from "vitest"
import { exampleSession } from "./example"
import { SessionFeed } from "./session-feed"

afterEach(() => vi.useRealTimers())

describe("session polling", () => {
  it("coalesces refreshes during an in-flight read and leaves no timer after disposal", async () => {
    vi.useFakeTimers()
    let resolve: (page: ReturnType<typeof exampleSession>) => void = () => {}
    const load = vi.fn(
      () =>
        new Promise<ReturnType<typeof exampleSession>>((done) => {
          resolve = done
        })
    )
    const feed = new SessionFeed(load)
    const unsubscribe = feed.subscribe(() => {})
    for (let i = 0; i < 10; i++) void feed.refresh()
    expect(load).toHaveBeenCalledTimes(1)
    resolve(exampleSession("claude", "one"))
    await Promise.resolve()
    await Promise.resolve()
    expect(vi.getTimerCount()).toBe(1)
    unsubscribe()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("pauses hidden transcript reads and refreshes when shown again", async () => {
    vi.useFakeTimers()
    const load = vi.fn(async () => exampleSession("claude", "one"))
    const feed = new SessionFeed(load)
    const unsubscribe = feed.subscribe(() => {})
    await Promise.resolve()
    await Promise.resolve()
    feed.visibility(false)
    await vi.advanceTimersByTimeAsync(20000)
    expect(load).toHaveBeenCalledTimes(1)
    feed.visibility(true)
    await Promise.resolve()
    expect(load).toHaveBeenCalledTimes(2)
    unsubscribe()
  })

  it("updates runtime state even when the transcript has not grown", async () => {
    vi.useFakeTimers()
    const page = exampleSession("claude", "one")
    const load = vi.fn(async () => page)
    const feed = new SessionFeed(load)
    const unsubscribe = feed.subscribe(() => {})
    await Promise.resolve()
    await Promise.resolve()
    if (!page.chat) throw new Error("Fixture needs chat state")
    const changed = {
      ...page,
      chat: { ...page.chat, busy: !page.chat?.busy },
      cursor: "new-cursor",
    }
    load.mockResolvedValueOnce(changed)
    await feed.refresh()
    expect(feed.state.data?.chat?.busy).toBe(changed.chat.busy)
    expect(feed.state.data?.cursor).toBe("new-cursor")
    unsubscribe()
  })
})

it("serializes backward paging with a delayed refresh and coalesces later refreshes", async () => {
  vi.useFakeTimers()
  const page = { ...exampleSession("claude", "one"), earlier: 300, first: 300 }
  let finish: (value: typeof page) => void = () => {}
  const load = vi.fn(
    () =>
      new Promise<typeof page>((done) => {
        finish = done
      })
  )
  const feed = new SessionFeed(load)
  const stop = feed.subscribe(() => {})
  const older = feed.earlier()
  expect(load).toHaveBeenCalledTimes(1)
  finish(page)
  await Promise.resolve()
  await Promise.resolve()
  expect(load).toHaveBeenCalledTimes(2)
  void feed.refresh()
  void feed.refresh()
  expect(load).toHaveBeenCalledTimes(2)
  finish({ ...page, earlier: 0, first: 0 })
  await older
  stop()
  expect(vi.getTimerCount()).toBe(0)
})

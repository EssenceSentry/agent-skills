// @vitest-environment jsdom
import { writeDraft } from "@/lib/drafts"
import { transportIdentity } from "@/lib/transport"
import "fake-indexeddb/auto"
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import { chatAct } from "@/lib/ax"
import type { ChatState, Session } from "@/lib/sessions"
import { Composer } from "./composer"

vi.mock("@/lib/ax", async (original) => ({
  ...(await original<Record<string, unknown>>()),
  chatAct: vi.fn(),
  hurry: vi.fn(),
}))
afterEach(() => {
  cleanup()
  vi.mocked(chatAct).mockReset()
})

const chat: ChatState = {
  holder: "ax",
  can_send: true,
  take_over: false,
  pending: false,
  busy: false,
  partial: "",
  approval: null,
  error: null,
  note: "",
}
const session = (id: string): Session => ({
  provider: "claude",
  id,
  name: "Same title",
  cwd: "/repo",
  project: "repo",
  state: "idle",
  waiting_for: null,
  kind: null,
  started: null,
  updated: null,
  last: null,
  jobs: 0,
})

describe("draft and delivery behavior", () => {
  it("retains new typing when a prior send is acknowledged, then recovers it after reopening", async () => {
    const user = userEvent.setup()
    let acknowledge: (value: { ok: boolean }) => void = () => {}
    vi.mocked(chatAct).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve
        })
    )
    const current = session(crypto.randomUUID())
    const first = render(<Composer session={current} chat={chat} />)
    await user.type(screen.getByRole("textbox", { name: "Message" }), "First instruction")
    await user.click(screen.getByRole("button", { name: /^Send$/ }))
    await user.type(screen.getByRole("textbox", { name: "Message" }), "New unsent work")
    await act(async () => acknowledge({ ok: true }))
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe(
      "New unsent work"
    )
    first.unmount()
    render(<Composer session={current} chat={chat} />)
    await waitFor(() =>
      expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe(
        "New unsent work"
      )
    )
    expect(vi.mocked(chatAct).mock.calls[0]?.[0].text).toBe("First instruction")
  })

  it("keeps a rejected submission retryable without replacing the next draft", async () => {
    const user = userEvent.setup()
    vi.mocked(chatAct).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ ok: true })
    render(<Composer session={session(crypto.randomUUID())} chat={chat} />)
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Keep this instruction")
    await user.click(screen.getByRole("button", { name: /^Send$/ }))
    await screen.findByText("offline")
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Separate next draft")
    await user.click(screen.getByRole("button", { name: "Retry delivery" }))
    expect(vi.mocked(chatAct).mock.calls[1]?.[0].client_message_id).toBe(
      vi.mocked(chatAct).mock.calls[0]?.[0].client_message_id
    )
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe(
      "Separate next draft"
    )
  })

  it("uses explicit queue delivery while preserving steer as normal Send", async () => {
    const user = userEvent.setup()
    vi.mocked(chatAct).mockResolvedValue({ ok: true })
    render(<Composer session={session(crypto.randomUUID())} chat={{ ...chat, busy: true }} />)
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Feedback now")
    await user.click(screen.getByRole("button", { name: /^Send$/ }))
    expect(vi.mocked(chatAct).mock.calls[0]?.[0].delivery).toBe("steer")
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Later task")
    await user.click(screen.getByRole("button", { name: /Queue next task/ }))
    expect(vi.mocked(chatAct).mock.calls[1]?.[0].delivery).toBe("queue")
  })
})

it("recovers a failed draft with its references and pictures intact", async () => {
  const user = userEvent.setup(),
    current = session(crypto.randomUUID())
  await writeDraft(`${transportIdentity()}:claude:${current.id}`, {
    text: "With attachments",
    refs: [{ kind: "file", path: "/repo/src/config.py" }],
    pictures: [{ media: "image/png", data: "YQ==", preview: "data:image/png;base64,YQ==" }],
  })
  vi.mocked(chatAct).mockRejectedValueOnce(new Error("offline"))
  render(<Composer session={current} chat={chat} />)
  await screen.findByRole("button", { name: "Remove picture 1" })
  await user.click(screen.getByRole("button", { name: /^Send$/ }))
  await screen.findByText("offline")
  await user.click(screen.getByRole("button", { name: "Recover draft and attachments" }))
  expect(screen.getByRole("button", { name: "Remove picture 1" })).toBeTruthy()
  expect(screen.getByText("src/config.py")).toBeTruthy()
  expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toBe(
    "With attachments"
  )
})

it("offers a provider-specific sign-in action for authentication failures", async () => {
  const user = userEvent.setup()
  render(
    <Composer
      session={session(crypto.randomUUID())}
      chat={{ ...chat, error: "Authentication expired" }}
    />
  )
  await user.click(screen.getByText("Sign-in help"))
  expect(screen.getByText("claude auth login")).toBeTruthy()
  await user.click(screen.getByRole("button", { name: "Copy sign-in command" }))
  expect(await navigator.clipboard.readText()).toBe("claude auth login")
})

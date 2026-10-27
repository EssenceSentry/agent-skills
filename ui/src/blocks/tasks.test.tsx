import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TaskList } from "@/blocks/tasks"

describe("the task list card", () => {
  it("shows each step with its state, the one in progress marked", () => {
    const html = renderToStaticMarkup(
      <TaskList
        tasks={{
          items: [
            { text: "Look at the records", status: "completed" },
            { text: "Write the tests", status: "in_progress" },
            { text: "Build it", status: "pending" },
          ],
          explanation: "Three steps",
        }}
      />
    )
    expect(html).toContain('aria-label="Tasks: 1 of 3 done"')
    expect(html).toContain('data-status="completed"')
    expect(html).toContain('aria-current="step"')
    expect(html).toContain("Write the tests")
    expect(html).toContain("Three steps")
  })

  it("folds away once every step is done", () => {
    const html = renderToStaticMarkup(
      <TaskList
        tasks={{
          items: [
            { text: "a", status: "completed" },
            { text: "b", status: "completed" },
          ],
          explanation: null,
        }}
      />
    )
    expect(html).toContain("<details")
    expect(html).not.toContain("<details open")
    expect(html).toContain("2 of 2 done")
  })
})

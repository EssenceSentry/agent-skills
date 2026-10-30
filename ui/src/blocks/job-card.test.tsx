import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { JobCard } from "@/blocks/job-card"
import { EditorHost } from "@/lib/host"
import { describeJobEvent, type JobDetail, jobKey } from "@/lib/job"
import type { Card } from "@/lib/sessions"

const card: Card = {
  key: "demo-scoring",
  label: "Score the testing videos",
  kind: "events",
  status: "running",
  stage: "scoring",
  message: null,
  progress: { done: 132, total: 200, unit: "shards", percent: 66, text: "132/200 shards (66%)" },
  eta: "about 3 min",
  look: { summary: "Steady.", at: "2026-10-27T12:00:00Z" },
  notebook: null,
  attention: null,
  page: "/jobs/demo-scoring/",
  updated: "2026-10-27T12:00:00Z",
}

const detail: JobDetail = {
  key: "demo-scoring",
  label: "Score the testing videos",
  kind: "events",
  ref: null,
  status: "running",
  stage: "scoring",
  message: "shard 132 of 200 written",
  check_error: null,
  created: "2026-10-27T11:50:00Z",
  updated: "2026-10-27T12:00:00Z",
  finished: null,
  done: 132,
  total: 200,
  unit: "shards",
  progress_text: "132/200 shards (66%)",
  console_url: "https://us-east-1.console.aws.amazon.com/sagemaker/home",
  eta: null,
  events: [
    { ts: "2026-10-27T11:50:00Z", type: "created", data: {} },
    { ts: "2026-10-27T11:55:00Z", type: "stage", data: { stage: "scoring" } },
  ],
  looks: [
    { at: "2026-10-27T12:00:00Z", summary: "Steady at 26 shards a minute.", problem: null },
    { at: "2026-10-27T11:55:00Z", summary: "Started well.", problem: "Slower than last run" },
  ],
  check_every: 300,
  log: "shard 131 done\nshard 132 done",
}

describe("a job its session waits on", () => {
  it("opens in place instead of linking to the job's page", () => {
    const out = renderToStaticMarkup(<JobCard card={card} />)
    expect(out).not.toContain("The job's page")
    expect(out).toContain('aria-expanded="false"')
    expect(out).toContain("Score the testing videos")
  })

  it("says which job it is, so a link to the job's page can open it", () => {
    expect(renderToStaticMarkup(<JobCard card={card} />)).toContain('data-job="demo-scoring"')
  })

  it("shows the job's details when open, in an area that scrolls", () => {
    const out = renderToStaticMarkup(<JobCard card={card} open detail={detail} />)
    expect(out).toContain('aria-expanded="true"')
    expect(out).toContain("chat-card-details")
    expect(out).toContain("shard 132 of 200 written")
    expect(out).toContain("registered")
    expect(out).toContain("stage: scoring")
    expect(out).toContain("Started well.")
    expect(out).toContain("Slower than last run")
    expect(out).toContain("shard 131 done")
    expect(out).toContain("AWS console")
  })
})

describe("a job's events, as its page words them", () => {
  it("says what happened", () => {
    const at = "2026-10-27T12:00:00Z"
    expect(describeJobEvent({ ts: at, type: "created", data: {} })).toBe("registered")
    expect(describeJobEvent({ ts: at, type: "status", data: { status: "done" } })).toBe(
      "status: done"
    )
    expect(describeJobEvent({ ts: at, type: "wake_failed", data: { error: "closed" } })).toBe(
      "could not wake: closed"
    )
    expect(describeJobEvent({ ts: at, type: "woke", data: { agent: "claude" } })).toBe(
      "woke the claude session"
    )
    expect(describeJobEvent({ ts: at, type: "odd", data: { a: 1 } })).toBe('odd {"a":1}')
  })
})

describe("a notebook run's card", () => {
  const notebook: Card = {
    ...card,
    kind: "runwatch",
    notebook: {
      path: "/runs/r1/source.ipynb",
      cell: { index: 7, label: "Train the view-rate model" },
      cells: { done: 7, total: 10 },
      resources: [],
    },
  }

  it("opens the notebook at its cell from the editor", () => {
    const out = renderToStaticMarkup(
      <EditorHost.Provider value={true}>
        <JobCard card={notebook} />
      </EditorHost.Provider>
    )
    expect(out).toContain('aria-label="Open the notebook at cell 7, Train the view-rate model"')
  })

  it("names the cell without opening anything on the web page", () => {
    const out = renderToStaticMarkup(<JobCard card={notebook} />)
    expect(out).toContain("Train the view-rate model")
    expect(out).not.toContain("Open the notebook")
  })
})

describe("a link to a job's page in the ax app", () => {
  it("names the job, its card shows it", () => {
    expect(jobKey("/jobs/build-42/")).toBe("build-42")
    expect(jobKey("/jobs/score%20v5")).toBe("score v5")
  })

  it("names nothing else", () => {
    for (const href of [
      "/jobs/a/api/job",
      "/jobsite/x",
      "/jobs/",
      "/jobs/%E0%A4%A/",
      "https://x/jobs/a/",
    ])
      expect(jobKey(href), href).toBeNull()
  })
})

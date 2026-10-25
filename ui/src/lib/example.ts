// Example state, shown when no ax is behind the page (`npm run dev`, `npm run check`).
// The status in the bar says "Example data" whenever these are on screen.
import type { Folder, Found, Note, NowState } from "@/lib/ax"

const MINUTE = 60_000
const at = (minutes: number) => new Date(Date.now() + minutes * MINUTE).toISOString()

const SESSION = "Sessions/2026/10/2026-10-25 Build the ax app 48402546.md"
const RULE = "Profile/rules/run-tests-before-claims.md"
const BOOTSTRAP = "Profile/rules/bootstrap-not-uv-sync.md"
const T1 = "Todos/T1 Approve the start hook in Codex.md"
const T2 = "Todos/T2 Write twenty eval questions.md"

export const exampleNow: NowState = {
  generated: at(0),
  last_sync: at(-6),
  usage: [
    {
      provider: "claude",
      window: "session",
      used: 44,
      status: "fresh",
      resets_at: at(118),
      lasts: true,
      projected_high: 71,
      runs_out_at: null,
    },
    {
      provider: "claude",
      window: "weekly",
      used: 83,
      status: "fresh",
      resets_at: at(1830),
      lasts: false,
      projected_high: 112,
      runs_out_at: at(1210),
    },
    {
      provider: "claude",
      window: "weekly_fable",
      used: 12,
      status: "fresh",
      resets_at: at(1830),
      lasts: true,
      projected_high: 20,
      runs_out_at: null,
    },
    {
      provider: "codex",
      window: "weekly",
      used: 31,
      status: "fresh",
      resets_at: at(8460),
      lasts: true,
      projected_high: 64,
      runs_out_at: null,
    },
  ],
  credits: [
    {
      provider: "codex",
      balance: 4820.5,
      unlimited: false,
      has_credits: true,
      observed_at: at(-9),
      status: "fresh",
    },
  ],
  waiting: [
    {
      kind: "job",
      id: "review-leakage",
      title: "Opus review: holdout and provenance safeguards",
      detail: "no progress in 40 min",
      status: "running",
      updated: at(-41),
      actions: [],
    },
    {
      kind: "usage",
      id: "claude-weekly",
      title: "Claude weekly: 83% used",
      detail: "13% a day left for 1.3 days",
      resets_at: at(1830),
      actions: [],
    },
    {
      kind: "proposal",
      id: "run-tests-before-claims",
      title: "Run the tests before saying they pass.",
      detail:
        "You corrected this four times in three projects, twice with frustration: claims of passing tests that had not run.",
      scope: "global",
      note: RULE,
      actions: ["accept", "reject"],
    },
    {
      kind: "review",
      id: "bootstrap-not-uv-sync",
      title: "Refresh the environment with the bootstrap script, never a plain uv sync.",
      detail: "Restated twice since you adopted it: guard it or rewrite it.",
      scope: "repo:ds-models",
      maturity: "established",
      note: BOOTSTRAP,
      actions: ["keep", "retire", "guard"],
    },
    {
      kind: "budget",
      id: "translation",
      title: "translation is over its limit: 11.2 of 10 usd",
      detail: 'Passed with "the last language the user asked for".',
      origin: "ax:71a2e3eb",
      note: null,
      actions: [],
    },
    {
      kind: "todo",
      id: "T1",
      title: "Approve the start hook in Codex with /hooks",
      detail: "",
      scope: "global",
      origin: "ax:48402546",
      created: "2026-10-25",
      note: T1,
      actions: ["done", "drop"],
    },
    {
      kind: "todo",
      id: "T2",
      title: "Write twenty eval questions for ax find",
      detail: "Questions with known answers.",
      scope: "project:agent-skills",
      origin: null,
      created: "2026-10-25",
      note: T2,
      actions: ["done", "drop"],
    },
  ],
  budgets: [
    {
      name: "annotations",
      cap: 40,
      unit: "usd",
      why: "Luna labels for the News research",
      owner: "ax:48402546",
      owner_note: SESSION,
      scope: "session:6942b4a0-7d35-4d5e-91a2-460a48402546",
      project: "ds-models",
      path: null,
      created: at(-300),
      spent: 21.4,
      reserved: 6,
      left: 12.6,
      state: "ok",
      passes: 0,
      entries: [
        {
          ticket: "R7",
          kind: "hold",
          amount: 6,
          note: "batch 4",
          agent: "ax:48402546",
          intent: null,
          at: at(-3),
          state: "open",
          actual: null,
        },
        {
          ticket: null,
          kind: "add",
          amount: 8.9,
          note: "batch 3",
          agent: "ax:48402546",
          intent: null,
          at: at(-40),
          state: null,
          actual: null,
        },
        {
          ticket: null,
          kind: "add",
          amount: 12.5,
          note: "batches 1 and 2",
          agent: "ax:48402546",
          intent: null,
          at: at(-130),
          state: null,
          actual: null,
        },
      ],
    },
    {
      name: "downloads",
      cap: 4,
      unit: "GB",
      why: "Thumbnails for the audit",
      owner: "ax:9fe6d7e6",
      owner_note: null,
      scope: "project:ds-models",
      project: "ds-models",
      path: "/Users/me/Repos/ds-models/models/news/data/raw",
      created: at(-900),
      spent: 3.41,
      reserved: 0,
      left: 0.59,
      state: "near",
      passes: 0,
      entries: [],
    },
    {
      name: "translation",
      cap: 10,
      unit: "usd",
      why: null,
      owner: "ax:71a2e3eb",
      owner_note: null,
      scope: "project:ds-models",
      project: "ds-models",
      path: null,
      created: at(-1400),
      spent: 11.2,
      reserved: 0,
      left: -1.2,
      state: "over",
      passes: 1,
      entries: [
        {
          ticket: null,
          kind: "add",
          amount: 2.4,
          note: "Portuguese titles",
          agent: "ax:71a2e3eb",
          intent: "the last language the user asked for",
          at: at(-200),
          state: null,
          actual: null,
        },
        {
          ticket: null,
          kind: "add",
          amount: 8.8,
          note: "Spanish and German",
          agent: "ax:71a2e3eb",
          intent: null,
          at: at(-600),
          state: null,
          actual: null,
        },
      ],
    },
  ],
  jobs: [
    {
      key: "embed-thumbnails",
      label: "Embed 3,120 thumbnails with SigLIP",
      status: "running",
      stage: "embedding",
      progress: "2,000/3,120 files",
      percent: 64,
      eta: "~12 min (8–19)",
      check_error: null,
      updated: at(-1),
      link: null,
    },
    {
      key: "review-leakage",
      label: "Opus review: holdout and provenance safeguards",
      status: "running",
      stage: null,
      progress: "-",
      percent: null,
      eta: null,
      check_error: "no progress in 40 min",
      updated: at(-41),
      link: null,
    },
  ],
  conversations: [
    {
      handle: "ax:48402546",
      title: "Build the ax app",
      provider: "claude",
      project: "agent-skills",
      ended: at(-2),
      note: SESSION,
    },
    {
      handle: "ax:8bb461fd",
      title: "Review news model predictions",
      provider: "codex",
      project: "ds-models",
      ended: at(-35),
      note: SESSION,
    },
    {
      handle: "ax:99b06c0c",
      title: "Opinionated dashboard starter generator",
      provider: "claude",
      project: "atelier",
      ended: at(-190),
      note: SESSION,
    },
    {
      handle: "ax:fd079ec8",
      title: "Read validation handoff",
      provider: "codex",
      project: "ds-models",
      ended: at(-260),
      note: SESSION,
    },
    {
      handle: "ax:c99b78fd",
      title: "News queries coherence with label definitions",
      provider: "claude",
      project: "ds-models",
      ended: at(-1500),
      note: SESSION,
    },
  ],
  errors: [],
}

const notes: Record<string, Note> = {
  [SESSION]: {
    path: SESSION,
    title: "Build the ax app",
    properties: [
      { key: "tool", value: "claude" },
      { key: "project", value: "agent-skills" },
      { key: "model", value: "claude-opus-5-5" },
      {
        key: "builds_on",
        value:
          "[Opinionated dashboard starter generator](#/read/Sessions/2026/10/2026-10-25%20Build%20the%20ax%20app%2048402546.md)",
      },
    ],
    markdown: [
      "## Where it ended",
      "",
      "The API is green and the app is generated from atelier. Next: the Now screen.",
      "",
      "> [!note] Example note",
      "> The reader shows notes from your vault; this one is example data.",
      "",
      "| Step | State |",
      "|---|---|",
      "| API | done |",
      "| Now screen | in progress |",
      "",
      "See [Run the tests before saying they pass](#/read/Profile/rules/run-tests-before-claims.md) and [an old note](#/missing/an%20old%20note).",
      "",
      "```bash",
      "ax serve --open",
      "```",
    ].join("\n"),
    modified: at(-2),
  },
  [RULE]: {
    path: RULE,
    title: "run-tests-before-claims",
    properties: [
      { key: "rule", value: "Run the tests before saying they pass." },
      { key: "status", value: "proposed" },
      { key: "scope", value: "global" },
    ],
    markdown:
      "You corrected this four times in three projects.\n\n> [!warning] Evidence\n> Two of the four came with frustration.",
    modified: at(-30),
  },
}

const listing: Record<string, Folder> = {
  "": {
    path: "",
    parent: null,
    notes: [],
    folders: ["Profile", "Sessions", "Todos"].map((name) => ({ name, path: name })),
  },
  Profile: {
    path: "Profile",
    parent: "",
    notes: [],
    folders: [{ name: "rules", path: "Profile/rules" }],
  },
  "Profile/rules": {
    path: "Profile/rules",
    parent: "Profile",
    folders: [],
    notes: [RULE, BOOTSTRAP].map((path, i) => ({
      path,
      title: path.split("/").pop()?.replace(/\.md$/, "") ?? path,
      modified: at(-30 - i * 600),
    })),
  },
  Sessions: {
    path: "Sessions",
    parent: "",
    notes: [],
    folders: [{ name: "2026", path: "Sessions/2026" }],
  },
  "Sessions/2026": {
    path: "Sessions/2026",
    parent: "Sessions",
    notes: [],
    folders: [{ name: "10", path: "Sessions/2026/10" }],
  },
  "Sessions/2026/10": {
    path: "Sessions/2026/10",
    parent: "Sessions/2026",
    folders: [],
    notes: exampleNow.conversations.map((c, i) => ({
      path: i ? `Sessions/2026/10/2026-10-25 ${c.title} ${c.handle.slice(3)}.md` : SESSION,
      title: i
        ? `2026-10-25 ${c.title} ${c.handle.slice(3)}`
        : "2026-10-25 Build the ax app 48402546",
      modified: c.ended ?? at(0),
    })),
  },
  Todos: {
    path: "Todos",
    parent: "",
    folders: [],
    notes: [T1, T2].map((path) => ({ path, title: path.slice(6, -3), modified: at(-60) })),
  },
}

export function exampleFolder(dir: string): Folder {
  return (
    listing[dir] ?? {
      path: dir,
      parent: dir.includes("/") ? dir.slice(0, dir.lastIndexOf("/")) : "",
      folders: [],
      notes: [],
    }
  )
}

export function exampleNote(path: string): Note {
  return (
    notes[path] ?? {
      path,
      title: path.split("/").pop()?.replace(/\.md$/, "") ?? path,
      properties: [],
      markdown: "Example data: with `ax serve` behind the page, this is the note from your vault.",
      modified: at(-60),
    }
  )
}

export function exampleFind(query: string): Found {
  return {
    query,
    hits: [
      {
        source: "conversation",
        path: `/vault/${SESSION}`,
        note: SESSION,
        title: "Build the ax app",
        handle: "ax:48402546",
        provider: "claude",
        project: "agent-skills",
        date: "2026-10-25",
        snippet:
          "Reserve holds an amount before an expensive call and settle replaces it with the real cost, so parallel workers can't overshoot together.",
      },
      {
        source: "note",
        path: `/vault/${RULE}`,
        note: RULE,
        title: "run-tests-before-claims",
        snippet: "Run the tests before saying they pass, and say which ones ran.",
      },
      {
        source: "memory",
        path: "/Users/me/.claude/projects/demo/memory/budgets.md",
        note: null,
        title: "budgets",
        snippet: "Annotation spend is capped per research run; ask before raising the cap.",
      },
      {
        source: "doc",
        path: "/Users/me/Repos/agent-skills/PLAN.md",
        note: null,
        title: "PLAN.md",
        project: "agent-skills",
        snippet: "Budgets agents register, add to and ask about, with reserve then settle.",
      },
      {
        source: "code",
        path: "/Users/me/Repos/agent-skills/src/ax/budget.py",
        note: null,
        title: "agent-skills/src/ax/budget.py:212-230",
        project: "agent-skills",
        line: 212,
        snippet:
          'def reserve(data, name, amount, *, note=None):\n    """Hold an amount before spending it; returns the ticket."""',
      },
    ],
  }
}

// What ax does, for the Help screen. A test in tests/test_app.py fails when a top-level
// `ax` command is missing from `commands`, so this stays complete as ax grows.

export type Area = {
  id: string
  area: string
  title: string
  body: string
  commands: string[]
  proof?: string
}

export const intro =
  "ax archives everything you do in Claude Code and Codex, makes it searchable and easy to " +
  "build on, gives both tools one set of working rules, wakes a conversation when its job " +
  "ends, and shows what waits for you here."

export const flow = [
  {
    title: "Comes in",
    items: [
      "Claude Code and Codex transcripts",
      "Both tools' memories",
      "Your repositories' docs and code",
      "Jobs: SageMaker, Seamless, Runwatch, any command",
      "Your corrections and approvals",
    ],
  },
  {
    title: "ax keeps",
    items: [
      "A SQLite archive and compressed backups",
      "A Markdown vault in git",
      "A search index over all of it",
      "Rules with their evidence",
      "Jobs with their estimates",
    ],
  },
  {
    title: "Shows up",
    items: [
      "A digest at the start of each conversation",
      "find, recall and here, also over MCP",
      "Both tools' instructions, guard and workers",
      "Wake-up notes and ntfy messages",
      "This app, on this Mac or your phone",
    ],
  },
]

export const areas: Area[] = [
  {
    id: "remember",
    area: "Remember",
    title: "Every conversation, archived and built on",
    body: "ax sync copies each Claude Code and Codex transcript into a compressed backup, indexes it in SQLite and writes one readable Markdown note per conversation, with secrets redacted. Each conversation has a handle such as ax:48402546. Recall it from either tool and the two notes link to each other.",
    commands: ["ax sync", "ax search", "ax here", "ax recall"],
    proof: "1,916 session notes; rebuilding them found 1,084 links between conversations.",
  },
  {
    id: "find",
    area: "Find",
    title: "One search over everything you've worked on",
    body: "ax find asks qmd and Semble at once: past conversations, both tools' memories, vault notes, every repository's docs and its code, by meaning as well as words. A small daemon keeps the models loaded. The search box in this app's Notes runs it when you press Enter.",
    commands: ["ax find", "ax index"],
    proof: "The first search took 34 s; it now takes about 5 s.",
  },
  {
    id: "start",
    area: "Start informed",
    title: "Each conversation starts knowing last week",
    body: "A start hook in both tools lists the last seven days' conversations with their handles, your open to-dos and the jobs still running. Claude's memories are copied into Codex, Codex's memory summary reaches Claude, and an MCP server gives agents find, recall and here.",
    commands: ["ax hooks", "ax mcp"],
    proof: "57 Claude memories shared with Codex.",
  },
  {
    id: "rules",
    area: "Rules",
    title: "One set of working rules for both tools",
    body: "Rules are vault notes, compiled into Claude's and Codex's instructions and into the definitions of delegated workers. A stop check sends Claude back when it says tests pass without having run them.",
    commands: ["ax profile"],
  },
  {
    id: "learn",
    area: "Learn",
    title: "Rules proposed from your own corrections",
    body: "ax learn reads what you wrote in both tools: corrections, requests to remember, praise, refused tool calls, and moments of frustration with the episode behind them. Haiku labels them and proposals wait for you on the Now screen, where accepting or setting a proposal aside (Not now) takes one click and Decided keeps every decision for you to reverse. Each accepted rule keeps its own evidence, confidence and maturity, and asks for review when it keeps being restated or passed.",
    commands: ["ax learn"],
    proof: "It rediscovered 9 of the 11 rules written by hand.",
  },
  {
    id: "workshop",
    area: "Workshop",
    title: "Spare allowance, spent on the rules",
    body: "On the last day of a weekly window with allowance to spare, the scheduled sync starts Opus 5.5 or Sol 6.1 agents, as many as the rule work and the allowance above a 3% floor allow. They propose only rules that recur across sessions and that no skill or instruction file already states, and a final agent settles one list: every waiting proposal kept, replaced or withdrawn. Their warnings about instruction files that look wrong arrive here too, with a report in the vault's Workshops folder. Codex credits are never spent.",
    commands: ["ax workshop"],
  },
  {
    id: "friction",
    area: "Pauses, not walls",
    title: "A pause before what can't be undone",
    body: 'Before a command, the guard pauses the main agent, the one you talk to, once before something it can\'t undo: a reset or clean that would lose work, a force push, a cloud delete, a dropped table. It says what is at stake; run again with AX_INTENT="why" in front, the command goes through and the reason is logged. Nothing pauses when nothing would be lost.',
    commands: ["ax-guard", "ax policy"],
  },
  {
    id: "delegation",
    area: "Delegation",
    title: "Workers that know your rules and their limits",
    body: "ax brief writes a worker's brief with your rules and the limits it works under. The main agent sets those limits with ax policy; subagents and workers are stopped by them, and by irreversible actions, and report back instead. ax runs lists delegated and background runs from both tools.",
    commands: ["ax brief", "ax policy", "ax runs"],
  },
  {
    id: "jobs",
    area: "Long jobs",
    title: "Jobs that wake the conversation that started them",
    body: "Register anything that runs longer than a few minutes. ax estimates when it ends, follows it with ntfy messages, has Haiku read its log every 30 minutes, and brings a note on how it ended back into the conversation that started it.",
    commands: ["ax job"],
    proof: "Its 80% finish interval covered 84% of steady simulated runs.",
  },
  {
    id: "usage",
    area: "Usage",
    title: "Both tools' allowance at a glance",
    body: "Every window of Claude and Codex, Codex's credit balance, and what each weekly window leaves per day until it resets, at the top of every screen here. Scripts can call ax usage guard to stop before they run a tool dry.",
    commands: ["ax usage"],
  },
  {
    id: "app",
    area: "This app",
    title: "What waits for you, on this Mac or your phone",
    body: "Proposals, flagged rules and jobs and to-dos to act on, each action confirmed first; jobs running now; recent conversations by handle; and every note in the vault. launchd keeps it served at 127.0.0.1:8765, where it installs as an app from the browser, and keeps a Cloudflare link for your phone, sending each new one by ntfy.",
    commands: ["ax app", "ax serve"],
  },
  {
    id: "measure",
    area: "Measure",
    title: "A weekly scorecard, and evals of the rules",
    body: "ax scorecard counts corrections, frustration, guard pauses and reasons given, worker denials, recurring errors and cost by week. ax lab replays recorded cases with the rules and without them.",
    commands: ["ax scorecard", "ax lab"],
  },
  {
    id: "research",
    area: "Research",
    title: "Experiments that have to earn their run",
    body: "ax exp keeps research campaigns. Every experiment names the decision it could change and passes a value gate before it starts; results that change nothing say to rethink the direction.",
    commands: ["ax exp"],
  },
  {
    id: "budgets",
    area: "Budgets",
    title: "Caps agents keep, and you can watch",
    body: 'Tell an agent "no more than $40 on annotations and 4 GB of downloads" and it registers both. Agents add what they spend, or reserve before an expensive call and settle after, so parallel workers can\'t overshoot together; a download budget measures its folder by itself. Going over pauses the main agent until it gives a reason, which is logged on the budget; subagents report back instead. Each budget shows on the Now screen.',
    commands: ["ax budget"],
  },
  {
    id: "todos",
    area: "To-dos",
    title: "Follow-ups every conversation sees",
    body: "Keep a to-do global or for one project. It links to the conversation that raised it and shows in every new conversation's digest and here, until you close it as done or dropped.",
    commands: ["ax todo"],
  },
]

export const commands: [string, string][] = [
  ["ax sync", "Archive new and changed conversations into the vault"],
  ["ax find", "One search over conversations, memories, notes, docs and code"],
  ["ax search", "Exact words said in past conversations"],
  ["ax here · ax recall", "This conversation's handle; an earlier one brought into this one"],
  ["ax todo", "To-dos, global or per project, in every digest"],
  ["ax budget", "Caps agents register, add to, reserve against and check"],
  ["ax job", "Long jobs any agent can register, wait on and be woken by"],
  ["ax usage", "Allowance per tool and window, Codex credits, a guard for scripts"],
  ["ax app", "This app in the background: start, stop, status, open, launchd service"],
  ["ax serve", "Serve this app in the foreground, or share it through Cloudflare"],
  ["ax profile", "One set of rules, compiled into both tools, their guard and workers"],
  ["ax learn", "Rule proposals from your corrections, and each rule's lifecycle"],
  ["ax workshop", "The rules workshop: status, a run or a dry run, stop"],
  ["ax policy", "Limits the main agent sets for its subagents and workers"],
  ["ax brief", "A brief for a delegated worker that carries your rules and limits"],
  ["ax runs", "Delegated, background and subagent runs in one list"],
  ["ax scorecard", "Corrections, pauses, denials, errors and cost by week"],
  ["ax lab", "Replays that test the rules with and without them"],
  ["ax exp", "Research campaigns behind a value gate"],
  ["ax index", "Build, refresh and score the search index"],
  ["ax mcp", "find, recall and here for agents over MCP"],
  ["ax hooks · ax schedule", "Sync and the digest in both tools; a sync every 30 minutes"],
  ["ax skills", "Link this repository's skills into both tools"],
  ["ax vault", "A scanned commit, and a push only to a private repository"],
  ["ax doctor", "Archive health, retention and format drift"],
]

export const alone = [
  "search, find, recall an outline, here",
  "wait on a job and show it",
  "list to-dos, and add or close one you asked for",
  "read the scorecard, usage, runs and rules",
  "start, check and open this app",
  "set limits for their own subagents",
  "keep budgets: set, add, reserve, check, show",
]

export const askFirst = [
  "anything that spends: labelling, lab runs, model-read recalls",
  "accepting, rejecting, keeping or retiring a rule",
  "installing hooks, services or skills",
  "publishing: a vault push, a shared app link",
  "removing a job or dropping a to-do",
]

---
name: ax
description: The map of ax, the user's agent layer for Claude Code and Codex, and what an agent may run with it alone. Use when the user mentions ax, asks what ax can do, or a task touches their past conversations, memories, working rules, long jobs, usage limits, research campaigns, the Obsidian vault or their to-dos; then follow the focused skill this map points to (session-recall, jobs, delegation, research-director) for the details.
---

# ax

`ax` archives every Claude Code and Codex conversation into the user's Obsidian
vault, makes it searchable and buildable-on, keeps one set of working rules for
both tools, runs long jobs that wake you when they end, and keeps to-dos. Every
command has `--help`; most take `--json` for agents.

## Find and build on past work (skill: session-recall)

- `ax find "question"`: one search over past conversations, both tools' memories,
  the vault's notes, the repos' docs (README, plans, `docs/`) and their code. Use it
  before redoing an investigation or decision. `--in conversations|memories|notes|docs|code|subagents`,
  `--project`, `--provider`, `--since`, `--fast`.
- `ax search "exact words"`: exact words in archived messages (error text, ids).
- `ax recall ax:9fe6d7e6`: bring an earlier conversation in by its handle, as an
  outline with the note's path. `--for "task"` (a model read) and `--card` cost money.
- `ax here`: this conversation's handle, when the user asks for "the id".
- `ax index` (`setup`, `refresh`, `serve`, `eval`): the search index behind find.
  The user runs setup and serve; `eval` scores questions with known answers.
- Every conversation starts with a digest of the last week's conversations, open
  to-dos and running jobs: use it, and recall a conversation before relying on it.

## Long work (skill: jobs)

- `ax job` (`run`, `watch`, `new`, `wait`, `show`, `describe`, `follow`, …):
  register anything longer than a couple of minutes, always with `--label` saying
  what it does and what you'll do when it ends; wait without polling; `--wake auto`
  brings a note into this conversation when it ends.

## Delegating (skill: delegation)

- `ax brief implement|review|scout|continue`: a worker brief carrying the user's
  rules, and its launch plan. It launches nothing; the user approves workers.
- `ax runs` (`watch`, `show`, `stop`): delegated, background and subagent runs.

## Working rules

- `ax profile` (`list`, `add`, `compile`, `check`, `seed`): the user's rules, kept as
  vault notes and compiled into both tools' instruction files; a Claude stop check
  questions "tests pass" claims made without running tests.
- **Pauses:** before a shell command, `ax-guard` pauses the main agent (the one the
  user talks to) once before something it can't undo, or that a `block` rule names,
  and says what is at stake. If you mean it, run the same command again with your
  reason in front: `AX_INTENT="why" <command>`. The reason is logged. Nothing
  pauses when nothing would be lost, and ordinary work never pauses.
- `ax policy` (`add`, `list`, `remove`): limits you set for your subagents and
  workers, such as `ax policy add '\bgit\s+push\b' --why "I push, not you"`. They
  stop the subagent (it is told to report back to you) and never bind you; `--all`
  reaches every subagent and worker, Codex's too. Subagents and workers are also
  stopped before irreversible actions and the user's `block` rules.
- `ax learn` (`scan`, `label`, `propose`, `tidy`, `guards`, `fixes`, `list`,
  `review`, `accept`, `reject`, `keep`, `retire`, `guard`): proposes rules from the
  user's corrections and tracks each rule's evidence. Accepting, rejecting, keeping
  or retiring is the user's decision.
- `ax workshop` (`status`, `run`, `stop`): the rules workshop. On a weekly window's
  last day with spare allowance, the scheduled sync starts it by itself: Opus 5.5 or
  Sol 6.1 agents, sized by the rule work and the allowance left, consolidate and
  design the rules, and their work lands as proposals. `status` and `run --dry-run`
  show what it would do.

## Measuring

- `ax scorecard` (`--note`): corrections, frustration moments, guard blocks, worker
  denials, recurring errors and cost, by week.
- `ax usage` (and `ax usage guard`): allowance left per tool and window, and
  Codex's credits. Check it
  before proposing agents or long model work.
- `ax lab` (`build`, `cut`, `run`): evals of the profile as a plugin.

## Research campaigns (skill: research-director)

- `ax exp` (`init`, `propose`, `list`, `start`, `finish`, `abandon`): experiments
  that must pass a value gate before they run.

## To-dos

- `ax todo add "text"`: keep a follow-up, tied to this project and conversation
  (`--global` for none, `--detail` for context). Add one only when the user asks to
  keep something for later; never on your own initiative.
- `ax todo list` (this project's and the global ones; `--all`), `ax todo done T3`,
  `ax todo drop T3`. Close a to-do when its work is done in this conversation.

## Budgets

- `ax budget set NAME LIMIT --unit usd` (`--why`, `--project`, `--path DIR`): when
  the user gives a cap ("no more than $40 on annotations", "don't download more than
  4 GB"), register it. It belongs to this conversation and its subagents, or to the
  repository with `--project`; with `--path` it measures that folder's size (B, KB,
  MB, GB or TB) instead of taking additions.
- `ax budget add NAME AMOUNT --note "..."` after spending. Before an expensive step,
  `ax budget reserve NAME AMOUNT` prints a ticket such as R3; afterwards `ax budget
  settle R3 ACTUAL`, or `release R3` if nothing was spent. A hold never settled keeps
  counting, so parallel workers can't overshoot together.
- `ax budget check NAME AMOUNT` exits 0 when the amount fits; `show [NAME]` gives
  spent, reserved, left and the ledger; `close NAME` ends it. All take `--json`.
- **Going over pauses:** the command says what is spent and left. If you mean it, run
  it again with `AX_INTENT="why"` in front; the reason is logged on the budget. A
  subagent or worker never passes a budget: it reports back to the agent that
  started it.

## Plumbing the user runs

- `ax sync`: archive new conversations (hooks and a schedule run it).
- `ax hooks install`, `ax schedule install`, `ax skills link NAME`,
  `ax mcp install`: wire ax into both tools and launchd; each prints its plan and
  changes nothing without `--apply`. `ax mcp` is the MCP server they launch.
- `ax vault` (`init`, `commit`, `push`): the vault's views, a scanned commit, and a
  push only to a private GitHub repo.
- `ax doctor`: archive health. `ax serve`: the ax app for the user (what waits,
  usage and credits, jobs, conversations, a vault reader); `--share cloudflare
  --notify` reaches their phone.
- `ax app` (`start`, `stop`, `status`, `open`, `service`): the app served in the
  background at http://127.0.0.1:8765/, where the user can install it. Start it when
  the user wants the app; `service --apply` keeps it running from login.

## What you may run alone, and what needs the user

- **Alone:** find, search, recall (outline), here, job show and wait, todo list,
  todo add or done when the user asked, scorecard, usage, runs, profile list and
  check, learn list and review, doctor, app start, status and open, workshop status,
  policy add, list and remove for your own subagents, every `budget` command, any
  `--help` or `--dry-run`.
- **Ask first:** anything that spends (`learn label`, `lab run`, `recall --for` or
  `--card`, briefs that launch workers, `index setup`), changes the user's rules or
  tools (`learn accept|reject|keep|retire|guard`, `profile add` or `compile
  --apply`, any `install --apply`, `skills link --apply`), publishes (`vault
  push`, `serve --share` or `--notify`) or removes something (`job forget`,
  `todo drop`).

# Agent skills

Reusable skills for working with Claude Code, Codex, and ChatGPT.

## Available skills

| Skill | What it provides |
| --- | --- |
| [ax](skills/ax/SKILL.md) | The map of every `ax` command for agents in both tools: what each is for, which focused skill has the details, and what an agent may run alone or must ask about. A test keeps it complete. |
| [delegation](skills/delegation/SKILL.md) | Authorized Claude/Codex workers, usage and lifecycle helpers, ChatGPT Pro consultation, native conversation messaging and history retrieval, and technical infographics. |
| [research-director](skills/research-director/SKILL.md) | How agents run research campaigns through `ax exp`: weigh each experiment by the decision it can change, re-rank after every result, stop when results change nothing. |
| [session-recall](skills/session-recall/SKILL.md) | How agents find and build on past conversations, memories, notes and code with `ax find`, `ax recall`, `ax here` and `ax search`, and how to cite what they find. |
| [jobs](skills/jobs/SKILL.md) | How agents register long work with `ax job`, wait on it without polling, and wake when it ends. |

Each skill's references and Python helpers are part of that skill, not
separate skills.

## ax: archive agent sessions

`ax` copies every Claude Code and Codex transcript into a compressed raw backup,
indexes it in SQLite and writes one readable Markdown note per session into an
Obsidian vault. It only reads the tools' own session folders. See
[PLAN.md](PLAN.md) for the design and what comes next.

Install it once with `uv tool install --editable .` from this checkout. Code changes
take effect at once; after a change to the dependencies, run the same command with
`--reinstall`, or the installed `ax` (which hooks and launchd call) keeps the old ones.

| Command | What it does |
| --- | --- |
| `ax sync` | Archive new and changed sessions into the vault |
| `ax doctor` | Check retention, the vault, the last sync and format drift |
| `ax search "words" [--json]` | Find past sessions by the exact words said in them |
| `ax find "question" [--in …] [--json]` | One search over conversations, memories, vault notes, the repos' docs and their code (qmd and Semble) |
| `ax index` (`setup`, `refresh`, `eval`) | Build and refresh the index behind `ax find`, and score it on questions with known answers |
| `ax here` / `ax recall <handle>` | This conversation's handle; an earlier conversation brought into this one, linked in both notes |
| `ax todo` (`add`, `list`, `done`, `drop`) | To-dos, global or per project, linked to the conversation that raised them and shown in every new conversation's digest |
| `ax mcp` / `ax mcp install` | `find`, `recall` and `here` for agents over MCP, and their registration in both tools |
| `ax runs` (`watch`, `show`, `stop`) | Delegated, background and subagent runs from both tools in one list |
| `ax exp` (`init`, `propose`, `list`, `start`, `finish`, `abandon`) | Research campaigns whose experiments must pass a value gate |
| `ax usage` / `ax usage guard` | Allowance left per tool and window, Codex's credit balance, a forecast to reset, and a guard for scripts (exit 0 safe, 1 below, 69 unknown) |
| `ax serve [--open] [--share cloudflare] [--notify]` | The ax app: what waits for you with its actions, both tools' usage and credits, jobs, conversations, and a reader for the vault ([ui/](ui/README.md)); the old page is at `/classic` |
| `ax app` (`start`, `stop`, `status`, `open`, `service`) | The app served in the background at http://127.0.0.1:8765/, where a browser can install it; `service --apply` keeps it running from login with launchd |
| `ax vault init` / `commit` / `push` | Starter Obsidian views; a commit gitleaks has scanned; a push only to a private GitHub repo |
| `ax hooks install` | Hooks in Claude Code and Codex: sync when a session ends, and a digest of the last week's work when one starts |
| `ax schedule install` | A launchd job that syncs every 30 minutes |
| `ax skills link NAME…` | Link this repository's skills into both tools |
| `ax job` (`new`, `watch`, `run`, `describe`, `ls`, `show`, `wait`, `follow`, `unfollow`, `wake`, `poll`, `service`, `eta-report`, `forget`) | Long jobs any agent can register and wait on; see below |
| `ax profile` (`seed`, `list`, `add`, `compile`, `check`) | One set of working rules, compiled into both tools, their guard and their workers |
| `ax brief KIND` | A brief for a delegated worker that carries those rules, and its launch plan |
| `ax policy` (`add`, `list`, `remove`) | Limits the main agent sets for its subagents and workers, for this conversation or all; they never bind the main agent |
| `ax learn` (`scan`, `label`, `propose`, `fixes`, `tidy`, `guards`, `list`, `accept`, `reject`, `review`, `keep`, `retire`, `guard`, `recall`) | Rule proposals from your own corrections, for your approval, and each rule's lifecycle |
| `ax scorecard` | Corrections, nudges, guard blocks, worker denials, recurring errors and cost, by week |
| `ax workshop` (`status`, `run [--dry-run]`, `stop`) | The rules workshop: on a weekly window's spare last day, the scheduled sync starts Opus 5.5 or Sol 6.1 agents, sized by the rule work and the allowance above a 3% floor, to consolidate and design the rules; their work lands as proposals and a report in `Workshops/` |
| `ax lab` (`build`, `cut`, `run`) | Replay evals that test the profile as a plugin, with and without it |

`hooks install`, `schedule install` and `skills link` print what they would change
and do nothing without `--apply`.

### Jobs

`ax job` tracks long work wherever it was started, with nothing to import in the
job's own environment.

- **Register:**
  - `ax job new KEY` prints an events file. A producer appends JSON lines to it: `{"done": 10, "total": 40}`, `{"stage": "scoring"}`, `{"status": "done"}`, `{"exit": 0}`.
  - `ax job watch file|pid|sagemaker|seamless|runwatch|tools REF` lets ax check the job itself. `runwatch` takes a Runwatch run folder, read through `runwatch status` and `events`; a paused run ends the ax job as failed, so whoever waits on it wakes up to repair it. `tools` takes a Tools MCP job id and reads the job.json its worker keeps; Snowflake jobs there move only when the MCP refreshes them.
  - `ax job run -- CMD` starts a command detached and records its exit code. A heredoc piped in is replayed to the command, and the command finds its events file in `$AX_JOB_FILE`. Until the command reports progress there itself, a tqdm-style bar in its output counts as progress, with the bar's label as the stage.
- **Wait:** `ax job wait KEY` blocks without polling an agent. Exit codes:
  - 0: done;
  - 1: failed;
  - 2: stopped or ended;
  - 3: stalled;
  - 4: the source check kept failing for `--error-after` seconds (10 minutes by default), as with a mistyped SageMaker name or expired credentials;
  - 124: timed out;
  - 69: no such job.
- **Estimate:** `ax job show` and `ls` give the median time left and an 80% interval. The estimate comes from the job's own progress, plus finished runs of the same family (kind, unit, key without its numbers). `ax job eta-report` checks stored estimates against real finishes.
- **Wake:** `--wake auto|claude|codex` on `new`, `watch`, `run` or `follow` brings a short note on how the job ended into the conversation that registered it, with the description the agent gave (`--label`, or `ax job describe KEY --label` afterwards). A Codex thread open in the app gets it through `codex queue`, since the app holds the thread's only writer lock and refuses `codex exec resume`; a closed thread is resumed. Claude Code resumes through `claude --bg --resume`, which runs the note in a copy when the session is still running; the copy's id is reported. `ax job wake KEY --dry-run` shows the route. For a Claude session that is still open, `ax job wait KEY` as a background command is better: its exit wakes that session.
- **Checks and alerts:** with `--wake`, Haiku reads the end of a failed job's log and the note starts with its diagnosis, and every 30 minutes (`--check-every`, 0 for none) it reads a running job's log and wakes the agent once per problem it sees. When a note can't reach the conversation, or lands in a Claude copy, the ntfy topic gets a push whatever `--notify` says.
- **Background:** `ax job service --apply` loads a launchd agent (`com.ax.jobs`) that runs `ax job poll --background` every minute. It refreshes jobs nobody follows, leaves followed jobs to their followers, and restarts a follower that died from the options in its `follower.json`, at most three times per job, without repeating messages or wake-ups already sent. It checks AWS sources only for jobs registered with `--profile`, since launchd can't see credentials exported in an agent's shell. `--remove` unloads it.
- **Follow:** `ax job follow KEY --share none|lan|cloudflare --notify --detach`, or `--share` and `--notify` on `new`, `watch` and `run`.
  - It serves a token-protected, read-only page for the job, optionally through a Cloudflare quick tunnel.
  - It sends ntfy messages for the start, progress, new stages, stalls and the end.
  - It stops two minutes after the job ends.
  - Set the ntfy topic in `[notify] topic` in `config.toml`, or in `AX_NTFY_TOPIC`. On ntfy.sh the topic name is the only password, and messages carry the dashboard link.

### Profile and guard

Each rule is a note in the vault's `Profile/rules/`: the rule, its scope (global or
`repo:NAME`), the tools it applies to (`claude`, `codex`, and `workers` when delegated
workers need it too), its level (advice, check or block) and its evidence.

- `ax profile compile --apply` writes the rules into a marked block of
  `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, per-repo rules into a git-excluded
  `CLAUDE.local.md`, and the worker definitions: Claude agents `~/.claude/agents/ax-*.md`
  and Codex profiles `~/.codex/ax-*.config.toml` (`codex exec --profile ax-review`).
- `ax profile check` finds instructions elsewhere (skills, plugins, memories) that
  contradict a rule, and feedback memories no rule covers.
- `ax-guard` runs before every shell command in both tools. It tells the main agent
  (the conversation the user is in) from subagents and workers: Claude marks a
  subagent's calls with `agent_id`, and a Codex transcript's first line names an
  `exec` worker or a subagent.
  - **The main agent pauses** once before what it can't undo (a reset or clean
    that would lose work, a force push, a remote or cloud delete, a recursive `rm`
    outside disposable folders, a dropped table) or what a `block` rule names, and is
    told what is at stake. Run again with `AX_INTENT="why"` in front, the command goes
    through and the reason is logged. Nothing pauses when nothing would be lost.
  - **Subagents and workers are stopped** by the same, and by the limits the main
    agent sets with `ax policy add`, and are told to report back. Headless Claude
    workers run without hooks, so their runner's tool list and brief carry them.
  - **Only what runs counts:** heredoc bodies and quoted text are skipped, so a
    command that merely mentions something passes. A guard error lets the command
    through and logs itself. The scorecard counts pauses, stops and reasons given,
    and a rule the agent keeps passing is flagged for review.
  - **The stop check:** as Claude's Stop hook it also keeps Claude working, once,
    when a reply says tests pass but no test ran in that turn.

### Delegated work

`ax brief implement|review|scout|continue --repo R --task "…"` writes a brief under
`~/.local/share/ax/briefs/`: the task, owned paths, acceptance criteria, the rules marked
for workers in that repo, the repo's `AGENTS.md`/`CLAUDE.md` as required reads, a
permission profile and a budget halved when a Claude window is at 80% or more. It
prints the runner command and launches nothing; the delegation skill keeps the
approval step.

### Learning from corrections

`ax learn scan` collects, without a model, what you wrote in human sessions of both
tools that may state a rule: correction phrases, the message after an interruption,
explicit "remember"/"from now on" requests, praise for what the agent had just done
(not praise that only moves on), frustration markers with the episode that led to
them, the reasons you gave when refusing a Claude tool call, and the preference
signals Codex wrote into its raw memories. `label` has Claude Haiku (through
`claude -p`, redacted first) name each one's kind, rule and scope; a frustration
moment is labelled from its whole episode, which confirms the frustration and names
the lesson. `propose` writes rule notes with status `proposed` once a rule has a
support of two, where a session counts once, an explicit request twice and a
confirmed frustration moment three times (two projects for a global rule).

`fixes` proposes a rule for each error that recurs across sessions; `tidy` folds
near-duplicate proposals into one and notes contradictions; `guards` gives a "never"
proposal a block-level guard pattern when one catches the commands behind its
evidence and none of the last 30 days' other commands, tested on whole commands from
the transcripts (Codex's `exec` code included). `accept` and `reject` settle
proposals, and a rejected one returns only when its support doubles. At most 20
proposals wait at once (`--max-pending`), strongest support first.

After accepting, `ax sync` keeps each active rule's evidence in its note: support,
guard blocks, recurrences (the correction came back) and overrides (you set it
aside). Confidence halves every 90 days without new evidence and counts what goes
against a rule four times; maturity goes new, established, proven, or doubtful.
`ax learn review` lists them; a flag asks for a decision: `guard` after two
recurrences, a narrower scope after an override, `retire` or `keep` after 90 silent
days. Sync labels up to 40 new candidates with Haiku itself; `[learn] label_on_sync =
false` turns that off.
`recall` reports how many active rules the labels rediscover.

### Conversations you can build on

Every conversation has a handle: the last eight characters of its session id,
written `ax:9fe6d7e6`, the same short id its note's file name ends with. Ask an
agent for "the id" and it runs `ax here`. In another conversation, in either
tool, `ax recall ax:9fe6d7e6` brings it in as an outline with no model call (the
user's turns, where it ended, the files it changed and the note's path);
`--card` adds a summary Haiku writes once per conversation, and `--for "task"`
has a model return only what that task needs. Recalling from inside a
conversation links the two, and so does mentioning `ax:<handle>` or a full
session id: sync writes the links into the notes as `builds_on`, and Obsidian
shows the backlinks and the graph.

### Every conversation starts with recent work

`ax hooks install` adds a start hook to both tools (`ax hooks start`). Each new
conversation gets the user's own conversations of the last seven days, newest first
and the current project's first, with their handles, plus the jobs still running,
so "the pricing work" is something the agent recognizes and recalls. It reads the
archive only. Claude conversations also get Codex's memory summary. In the other
direction, sync copies each Claude memory into Codex's ad-hoc memory notes, which
Codex merges when it consolidates (`[memory] share = false` turns this off). Codex
runs a changed hook only after the user approves it with `/hooks`.

### One search

`ax find` asks qmd (conversation notes, Claude's and Codex's memories and the
vault's own notes, on a qmd index named `ax`) and Semble (every git checkout
under `~/Repos` plus `[find] extra_repos`) and interleaves their rankings. Each
hit is labelled conversation, memory, note or code; conversation hits carry
their handle, and `--project`, `--provider` and `--since` filter them. `--fast`
uses keywords only. `ax index setup` builds the indexes once (qmd downloads
about 2 GB of local models); sync refreshes them whenever it writes notes.
`ax index serve` keeps qmd's models loaded in a daemon, so a search takes about
five seconds instead of fifteen to thirty (`--stop` stops it).
`ax index eval questions.yml` reports how many questions with known answers
(`{query, expect}`, where `expect` is a handle or part of a path) come back in
the top five. Agents get the same through the session-recall skill or `ax mcp`.

### Measuring it

`ax scorecard` (and `/scorecard` in `ax serve`) counts per week the corrections,
"I said"/"again" repeats, progress nudges, confirmed frustration moments, guard
blocks and worker denials, with cost by model and effort, and lists each rule's
maturity and review flag, errors that recur across sessions, and skills nobody
used. `ax lab build` packages the profile as a plugin for `claude plugin eval`, with
starter cases; `ax lab cut` turns a past Claude session into a case; `ax lab run`
compares both arms under a cost ceiling.

Paths default to `~/.claude`, `~/.codex`, `~/Vaults/agents` and
`~/.local/share/ax`; override them in `~/.config/ax/config.toml` (`[paths]`),
and list working directories that must never be archived under
`[sync] exclude`. Tests use synthetic fixtures only: this repository is public,
so real transcripts never belong in it.

## Install in Codex

Ask Codex's skill installer:

```text
Use $skill-installer to install the delegation skill from
https://github.com/EssenceSentry/agent-skills/tree/main/skills/delegation
```

Alternatively, clone this repository and copy `skills/delegation` into your
Codex skills directory, usually `~/.codex/skills/delegation`. If a skill with
that name is already installed, compare the versions before replacing it.
Keep the whole folder so its relative references and helper imports work.

## How delegation works

- The parent keeps task ownership, consequential decisions, integration, and
  final verification. Worker count, provider, model, and reasoning effort must
  be authorized before launch; user and repository instructions take precedence.
- Claude and Codex workers receive bounded assignments, explicit write ownership,
  and a result that the parent can verify. The helpers support status, stopping
  owned processes, and exact-session follow-up.
- Pro consultations require approval of each concrete submission. Native app
  messaging is preferred for an existing ChatGPT conversation with Pro selected.
  Retrieval happens on the user's signal; Pro is not polled for completion.
- Older ChatGPT conversations can be read without sending a new prompt.
  [The app-tools guide](skills/delegation/references/chatgpt-app-tools.md)
  explains active/archived lookup, pagination, Markdown export, stale reads, and
  the boundaries between native tools, the web interface, and the CLI.

## Requirements and limits

The Python runtime helpers use the standard library and require Python 3.10+
on macOS or Linux/POSIX. Install and authenticate the actual Claude Code or
Codex CLI separately. They do not install provider tools, supply credentials,
or silently switch subscription work to API billing.

The usage helper reads Claude allowance information; Codex allowance is a
separate surface. Token counts, cost estimates, and subscription allowance
percentages are different measurements.

Native ChatGPT features require the desktop app to expose the corresponding
tools. They are not a public ChatGPT API and are not guaranteed to work from
an independent terminal process. Ordinary ChatGPT chat creation/deletion and
model selection may still need supported UI interaction.

Model IDs, CLI options, entitlements, and app capabilities change. Dated
observations in the guides are compatibility evidence, not guarantees about a
current installation. Inspect the selected runtime and account before use.

## Validate the helpers

The included tests use fake CLI executables and mocks. They do not call models,
require provider credentials, or consume subscription allowance.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install pytest
python -m unittest discover -s skills/delegation/scripts -p 'test_helpers.py'
python -m pytest skills/delegation/scripts/test_codex_worker.py
```

## Repository scope

This repository contains reusable instructions, references, helpers, and their
tests. Private dataset links and local account details have been replaced with
generic examples. Runtime briefs, worker logs, conversation exports, and
credentials belong outside the repository and are ignored by default.

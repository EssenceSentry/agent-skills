# Agent workbench: weekend plan

Plan written 2026-10-24. Build window: Saturday 24 and Sunday 25 October 2026.

## Status

- **Step 1 (setup and archive) done 2026-10-24.**
  - Obsidian is installed, and `~/Vaults/agents` is pushed to the private `agent-vault` repo (skeleton only).
  - `ax sync` and `ax doctor` work: 3,130 transcripts became 1,887 notes.
  - 1,243 Codex guardian reviews are indexed but get no notes.
  - The first full run takes about 60 seconds; later runs take under a second.
- **Learned while building:**
  - A Codex subagent rollout starts with its own `session_meta`, then copies the parent's metadata and history up to `subagent_history_start_ordinal`. Records below that ordinal are skipped.
  - A rollout's own id is the last UUID in its file name.
  - Codex ids are time-ordered, so note names use the id's tail.
  - Agent-to-agent `agent_message` items are rendered as quoted messages.
- **Steps 2–5 built 2026-10-24.**
  - `ax search` and the `session-recall` skill.
  - `ax vault init/commit/push`:
    - The first real scan of 1,887 notes found 3 false positives, all content hashes; a narrow allowlist covers them.
    - The vault commit is local only, not pushed yet.
  - `ax usage` and `ax usage guard`. On a Team seat, Claude's allowance comes from `/usage`; Codex's comes from rollout logs.
  - `ax hooks install`, `ax schedule install` and `ax skills link` are dry-run-first.
- **Live 2026-10-24:**
  - The vault is pushed to the private `agent-vault` repo.
  - Hooks are in Claude Code and Codex. Codex needs `/hooks` once to trust them.
  - A launchd job (`com.ax.sync`) syncs every 30 minutes.
  - `session-recall` is linked into both tools.
  - The vault is committed and pushed by hand (`ax vault commit && ax vault push`) until the schedule gets `--with-vault`.
- **Steps 6–8 built 2026-10-24.**
  - `ax runs`: delegation helper runs found through Spotlight, Claude background sessions, and subagents of both tools; 1,403 runs on this Mac.
  - `ax exp` and the `research-director` skill:
    - Each experiment is a vault note that has passed the value gate.
    - Open proposals are ranked by value × P(change) per hour.
    - Replaying the youtube-optimization studies ranks the two gating studies (0.62 and 0.50) far above the long shot (0.02).
  - `ax serve`: a localhost dashboard (standard library only; it refuses foreign Host names).
- **Step 9 core built 2026-10-24** (component 9):
  - `ax job new`, `watch`, `run`, `ls`, `show`, `wait`, `poll` and `forget`, with file, pid, SageMaker and Seamless sources. 232 tests pass.
  - Checked end to end with the installed `ax`:
    - a real zsh heredoc through `ax job run`;
    - an idle stdin pipe, which returns in 0.36 s;
    - the file protocol from bash.
  - SageMaker and Seamless have been tested only against recorded AWS responses so far, not yet against a real job.
- **Follower built 2026-10-24:**
  - `ax job follow` with the dashboard, LAN or Cloudflare sharing, and ntfy. 258 tests pass.
  - A live run on a phone-sized screen:
    - a synthetic heredoc job shared through a real quick tunnel;
    - 401 without the token; the link set a Secure, HttpOnly cookie; a foreign host name got 403;
    - seven ntfy messages reached a local stand-in server, each opening the public link;
    - the follower and cloudflared exited after the linger.
  - Not yet sent to a real ntfy topic.
- **The finished product built 2026-10-24** (the "Your agent layer" doc; 383 tests pass):
  - **Profile:** ten rules in the vault, compiled into both tools; `ax profile check` found the pixability-dev trailer conflict. A rule reaches delegated workers only when it names `workers`.
  - **Guards:** `ax-guard` in both tools, cc-safety-net, and a Claude Stop check for "tests pass" claims without a test run. Claude's commit attribution is off. A live false positive (a heredoc that only mentioned a forbidden command) led to `where: command` guards that ignore heredoc bodies and quoted text.
  - **Jobs:** finish estimates (a Gamma rate posterior with change detection, a history prior and a calibration report; on simulated jobs the 80% interval covered 84% of steady runs, 55% of predictions made before an undetected rate change). Wake-ups through `codex exec resume` and `claude --bg --resume`, both live-tested. Also `ax job service`, Runwatch and Tools MCP sources, tqdm bars from `run`, a Jobs panel in `ax serve` and the `jobs` skill. In Runwatch, the stale-attention fix and an `ax job wait` section in its skill (branch `fix/stale-attention-after-retry`).
  - **Briefs:** `ax brief` and generated worker definitions; a live probe confirmed Codex applies a profile file's `developer_instructions`. The drifted `~/.codex/skills/delegation` copy is in `~/.local/share/ax/backups/`, and the repo skill is linked into both tools.
  - **Learner:** 1,489 candidates (1,210 phrase matches, 6 after interruptions, 273 Codex preference signals) labelled by Haiku. It rediscovered 8 of the 10 rules (missed: no-green-ui, ds-models-uv) and proposed 12, waiting for review in `ax learn list`.
  - **Trials:** claude-reflect (heuristic dry run, read-only) proposed nothing in ds-models or auto-classifier: it reads only Claude sessions, and most corrections are in Codex. cass-memory was not run: its license grants no rights to Anthropic or anyone acting for it, and its reflection needs API keys. SkillOpt-Sleep was not installed, as decided.
  - **Scorecard and lab:** `ax scorecard` and `/scorecard`. Baselines for the last six weeks: corrections 9–17% of messages; worker denials 150 in W41, 41 in W43; the pyright warning in 44 sessions. Also `ax lab` with five starter cases and one cut from a real session.
  - **Live checks 2026-10-25:**
    - **Delegated review:** one Opus worker reviewed `guard.py` and `job_wake.py` through `ax brief review`. It finished with zero permission denials in 9 turns for $0.64, and found ten defects, all fixed test-first the same day: quoting and heredoc gaps in `where: command` guards, crashes on malformed input, repo rules missing worktrees and renamed clones, a loose stop check, `clean_env` dropping credentials such as `CLAUDE_CODE_OAUTH_TOKEN`, flag-like session ids reaching a wake's command line, and a stale line in wake errors. Two limits stay by design: a command run through `bash -c "…"` or a heredoc fed to a shell isn't checked, and a host variable missing from the deny-list reaches a woken agent.
    - **First `ax lab run`:** Sonnet, one run per case, $1.18. Evals that grant Bash can't run on this Mac, because Docker Desktop keeps plugin links inside `~/.docker`; `--no-shell` runs the four cases that need no shell. With the plugin, agents-within-limits went from 0.00 to 1.00: without it, Sonnet launched agents at once. The other three scored 1.00 in both arms.
  - **Not yet run live:** a real SageMaker or Seamless job, and `ax job service --apply`.
- **The learner's next version built 2026-10-25** (component 10, phases 1 and 2; 497 tests pass):
  - **Scan:** 1,758 candidates: 1,213 correction phrases, 210 praise, 99 frustration markers, 13 explicit requests, 6 after interruptions, 2 refused tool calls, 273 Codex preference signals. Haiku confirmed 62 of the 99 frustration markers from their episodes; the scorecard's weekly count peaks at 10 in W42 (the 24-hour autonomous run) and 8 in W40.
  - **Calibration on the real archive:** the first `propose` wrote 88 proposals, because "in the future" counted phrasing like "for future use" as a request to remember. It now counts only at the start of a sentence, and at most 20 proposals wait at once, strongest first: 19 wait now and 54 more queue behind them. The first `fixes` prompt turned 17 of 37 recurring errors into generic advice; a fix must now name a command, tool or path, and 2 remain (macOS `timeout`, the IAM scripts path).
  - **Tidy and guards:** the tidy pass merged `no-multilabel-compat` into `no-backward-compatibility`. No guard passed: three "never" proposals aren't about commands, and one pattern missed its own evidence.
  - **Lifecycle:** `ax sync` writes each active rule's evidence, confidence and maturity; all eleven are new (adopted 2026-10-24); `stage-explicit-paths` leads with 9 restating sessions and 5 guard blocks. Recall: 10 of 11 active rules rediscovered (missed: `ds-models-uv`).
  - **Not built:** the "Later" items, which wait for the profile to outgrow its always-loaded block. `[learn] label_on_sync` is off, so sync counts recurrences only among labelled messages until `ax learn label` runs.
- **Deferred:**
  - Rules matched per prompt (UserPromptSubmit): the ten rules fit in the always-loaded block, so retrieval waits until the profile grows.
  - The stop check for Codex, whose transcript has another format.
  - Run notes in `Runs/`.
  - Cheap handoffs and supervisor agents.
  - `ax mcp`.
  - Linking `research-director` into both tools (needs `ax skills link research-director --apply`).

## Goal

One local toolkit that makes working with Claude Code and Codex easier:

- Every session from both tools becomes a readable, searchable Markdown note in a private vault.
- One command shows remaining allowance, reset times and whether the allowance will last.
- Every delegated run, started from either tool, appears in one list you can watch and stop.
- Long research campaigns keep a ledger and pass a value gate before expensive work.

You look at it three ways: Obsidian (notes and tables), the terminal (`ax`), and a localhost page.

## Decisions already made

| Topic | Decision |
| --- | --- |
| Sources | Claude Code (CLI and the desktop Code tab) and Codex (CLI and desktop). ChatGPT and Claude.ai chats are out of scope for now. |
| Vault | The private repo `agent-vault`, created private on 2026-10-24. Transcripts go only there, never to this public repo. A secret scan gates every commit, and `ax` refuses to push the vault to any remote that isn't private. |
| Detail | Readable transcripts: messages in full, tool calls as one-line summaries, long outputs trimmed. Raw JSONL stays on this Mac, outside Git. |
| Code home | This repo: the `ax` CLI plus the skills it serves. The repo is public, so no work data goes in it, test fixtures included. |
| Research ledger | In the vault, one folder per project. |
| Recall | On demand. Agents search when a skill or question calls for it; nothing is injected at session start. |
| Retention | Claude Code `cleanupPeriodDays` set to 3650 on 2026-10-24. |
| Time | Saturday afternoon and all of Sunday. |

## What already exists

Reuse these rather than rebuilding them:

- **Delegation helpers** (`skills/delegation/scripts/worker.py`, `codex_worker.py`): run, status, stop and exact resume of Claude and Codex workers. Each run gets one directory (`run.json`, `events.jsonl`, `answer.md`). There is no shared registry yet.
- **Claude allowance** (`skills/delegation/scripts/usage.py`): reads Claude's allowance through headless `/usage` with zero inference. It works on the Team plan with Claude Code 2.1.283.
- **Claude Code**:
  - `claude agents --json --all` lists background sessions with state `working`, `blocked`, `done`, `failed` or `stopped`.
  - It has 33 hook events.
  - Skills load from `~/.claude/skills`, including symlinked folders (already in use on this Mac).
- **Codex 0.163**:
  - The app-server has `account/rateLimits/read`, `thread/list` and `thread/read`.
  - `token_count` events in session logs carry `rate_limits` (used %, window, reset time), readable offline.
  - It has 12 hook events; each hook must be trusted once via `/hooks`.
  - Skills load from `~/.agents/skills`; `~/.codex/skills` is the deprecated location.
- **qmd** ([tobi/qmd](https://github.com/tobi/qmd)): local BM25, vector and reranked search over Markdown, with a CLI and an MCP server. Node 24 and Homebrew sqlite are already installed.
- **Obsidian 1.12**:
  - Bases gives tables over frontmatter.
  - The official CLI needs the app running, so agents search files on disk instead of going through Obsidian.

## Facts that shape the design

1. **Transcripts were being deleted.** Until today Claude Code deleted CLI transcripts older than 30 days; desktop-app sessions are kept. Archive the raw JSONL first and render it second.
2. **Size.** Claude holds 1.6 GB (209 main sessions plus 589 subagent files). Codex holds 2.0 GB (about 2,190 rollouts, 93% of them already `.jsonl.zst`), plus 164 archived sessions.
3. **Formats are unstable.** Both vendors say their transcript format is not a stable interface. Codex compresses files after 7 days and is migrating sessions into SQLite. Parsers must tolerate unknown records and count them.
4. **Subagents dominate.** They are 74% of Claude transcript files. Fold them into the parent note as linked one-liners and keep their own notes in `_subagents/`, out of the default views.
5. **Transcripts carry secrets.** They are plaintext and contain whatever passed through tools, credentials included. Since the vault leaves the machine, redaction plus gitleaks before every commit is mandatory.
6. **Claude Team allowance.** Headless `/usage` is the only verified source of remaining allowance. Statusline `rate_limits` is documented for Pro and Max only: test it, don't rely on it.
7. **Hooks are constrained.** Claude's SessionEnd hooks share a 1.5-second budget, and Codex's SessionEnd doesn't fire for subagents. Hooks only enqueue work; a scheduled sweep catches anything missed.

## Architecture

```text
~/.claude/projects/**.jsonl ──┐                         ┌─> Vault (Markdown, Git, private) ─> Obsidian + Bases
~/.codex/{sessions,archived} ─┤                         ├─> ax CLI: search, usage, runs, exp ─> you and agents (via skills)
delegation run directories ───┼─> ax sync ─> ax.db ─────┼─> ax serve (localhost page)
claude agents / codex threads ┤   (SQLite + FTS5)       └─> qmd index (semantic search, MCP)   [stretch]
usage: /usage, Codex limits ──┘
hooks in both tools ─> queue ─> ax sync --queue
```

Rules:

- `ax` only reads the native session stores; it never writes to them.
- Code does capture, rendering, indexing and usage. Models are used only for judgment: handoffs and the research gate.
- One SQLite store feeds all three views. Markdown notes are generated and can be rebuilt at any time.

### Where things live

| Path | Contents | In Git? |
| --- | --- | --- |
| `~/Documents/Codex/agent-skills/` | `ax` source, skills, hooks, synthetic fixtures | Public repo |
| `~/Vaults/agents/` | The vault | Private repo `agent-vault` |
| `~/.local/share/ax/ax.db` | SQLite tables: sessions, messages (FTS5), runs, usage, experiments | No |
| `~/.local/share/ax/raw/` | zstd copy of every raw transcript | No (Time Machine covers it) |
| `~/.local/share/ax/runs/` | Delegation run directories (new default location) | No |
| `~/.config/ax/config.toml` | Paths, exclusions, budgets, redaction rules | No |

### Vault layout

```text
Home.md                                   dashboard note embedding the bases below
Sessions/2026/10/2026-10-24 claude my-repo - <title>.md
Sessions/2026/10/_subagents/...
Runs/<run-id>.md
Projects/<project>/Overview.md            your notes: goal, current state, links
Projects/<project>/Decisions.md
Projects/<project>/Handoffs/
Projects/<project>/Research/<campaign>/   Campaign.md, ledger.jsonl, Dead ends.md, Insights.md
Bases/Sessions.base, Runs.base, Experiments.base
```

`Sessions/` and `Runs/` are generated: never edit them by hand, because regenerating overwrites them. Your own writing goes in `Projects/`, which `ax` never overwrites.

### Session note

Frontmatter:

```yaml
type: session
provider: claude            # or codex
session_id: 2e065b04-...
title: Plan agent workbench
project: my-repo            # name of the cwd's git root
cwd: ~/Repos/my-repo
branch: main
model: claude-opus-5-5
started: 2026-10-24T13:32:00-03:00
ended: 2026-10-24T16:10:00-03:00
user_turns: 9
tokens_in: 812345
tokens_out: 40211
parent_session:             # set for subagents and delegated runs
run_id:
raw: ~/.local/share/ax/raw/claude/<project>/<session>.jsonl.zst
tags: [session, claude, my-repo]
```

The body has:

- your messages and the agent's replies in full;
- one line per tool call, for example `ran uv run pytest → exit 0` or `edited code/x.py +12 −3`;
- outputs over 40 lines trimmed, with a pointer to the raw file;
- a linked list of the session's subagents.

## Components

### 1. Archive: `ax sync` (must)

- **Parsing.** Claude `*.jsonl` plus `subagents/`; Codex `*.jsonl`, `*.jsonl.zst` and `archived_sessions`, read with the `zstandard` package.
- **Incremental.** Record path, size, mtime and hash, and reparse only changed files. A rerun with no changes does nothing.
- **Raw first.** Copy raw files to `raw/` before rendering.
- **Redaction.**
  - Mask known secret shapes during rendering.
  - `ax vault commit` runs gitleaks on staged files and refuses to commit on any hit.
  - `ax vault push` checks the remote with `gh repo view --json visibility` and refuses unless it is `PRIVATE`.
  - `exclude` globs in `config.toml` list projects that must never leave the machine.
- **`ax doctor`.** Count unknown record types per provider and version, so a format change shows up as a number, not as silent loss.

Done when:

- every current session renders;
- a rerun is a no-op;
- three hand-picked sessions read correctly in Obsidian;
- gitleaks passes and the vault is pushed.

### 2. Search: `ax search` (must)

- **Full-text search.** SQLite FTS5 over message text, with filters `--project`, `--provider`, `--since` and `--role`, and `--json` output for agents.
- **`session-recall` skill.** It tells agents when to search (before re-deriving a decision, or when you say "we discussed…") and how to cite the session note.
- **Stretch: semantic search** from both agents, via `qmd collection add ~/Vaults/agents --name agents` and then `qmd mcp`.

Done when:

- `ax search "cleanupPeriodDays"` finds this planning session;
- a Claude agent and a Codex agent each answer "what did we decide about the vault repo?" through the skill.

### 3. Usage: `ax usage` (must)

- **Sources.**
  - Claude: reuse the `usage.py` logic (headless `/usage`, no inference).
  - Codex: the latest `rate_limits` from session logs, refreshed with app-server `account/rateLimits/read` when stale.
- **Display.** `ax usage` stores each snapshot and shows used %, remaining, reset time, countdown and freshness for every window.
- **Forecast.** A burn rate from recent snapshots gives projected use at reset and "lasts" or "runs out at HH:MM", shown as a range.
- **Guard.** `ax usage guard --provider claude --window weekly --min-remaining 20` exits 0 when safe, 1 when below the threshold and 69 when unknown, the same codes as CodexBar.
- **Budgets.** Set in config, for example keep 25% of Claude's weekly window for interactive work; the guard applies them.
- **Schedule.** A launchd job takes a snapshot every 30 minutes.

Done when:

- the numbers match `/usage` and the Codex app;
- the guard exits correctly at a test threshold.

### 4. Runs: `ax runs` (should)

- **Registry sources:**
  - delegation run directories (move the default `--run-dir` under `~/.local/share/ax/runs/` and record `parent_session`);
  - `claude agents --json --all`;
  - Codex app-server `thread/list` or the session logs;
  - SubagentStart and SubagentStop hook events from both tools.
- **Commands:**
  - `ax runs`: a table of provider, model, effort, state, parent, elapsed time and last activity.
  - `ax runs watch` and `ax runs show <id>`.
  - `ax runs stop <id>`, only for runs `ax` owns; it writes `stop.request`.
  - `ax runs follow-up <id> --brief <file>`.
- **Run notes.** One note per run in `Runs/`, linked to its parent session.
- **Approval rule unchanged.** Agents may request a launch, but the count, model and effort need your approval.

Done when:

- a Claude worker started from Codex and a Codex worker started from Claude both appear within seconds and can be watched;
- one of them can be stopped.

### 5. Research ledger: `ax exp` plus the `research-director` skill (should)

- **`Campaign.md`.** The objective, the decisions it serves, the budget (hours, allowance %, $), stop rules, and the current answer in plain language.
- **`ledger.jsonl`.** One record per experiment:
  - the question and the decision it informs;
  - possible outcomes and the action each would trigger;
  - the cheaper alternative considered;
  - estimated cost, status and actual cost;
  - the result, whether the decision changed, and links.
- **Commands:**
  - `ax exp propose` rejects a proposal that lacks the decision informed, the outcome-to-action mapping or a stop rule.
  - `ax exp start`, `finish` and `abandon`.
  - `ax exp rank` orders open proposals by (decision importance × chance the result changes it) ÷ cost, using your weights.
  - `ax exp stall` flags a run of finished experiments that changed no decision.
- **Obsidian files.** `Dead ends.md` and `Insights.md` are append-only, and `Experiments.base` shows the ledger.
- **The skill** carries the Research Director policy: gate first, use the cheapest adequate evidence, re-rank after each result, and stop when the marginal value is low.

Done when: replaying a past campaign whose agents chased low-value studies, the gate ranks the studies that gated the real decision first.

### 6. Dashboard: `ax serve` (could)

- **One localhost page** showing:
  - live runs;
  - usage gauges with reset countdowns and the forecast;
  - recent sessions, linked into Obsidian through `obsidian://` URLs;
  - active campaigns.
- **Stack.** Server-rendered with FastAPI, Jinja and HTMX polling every 5 seconds; no JavaScript build.
- **Cut first** if Sunday runs late: Obsidian Bases and `ax runs watch` cover the same need.

### 7. Glue (must)

- **One hook script for both tools** (`hooks/ax-hook`):
  - SessionEnd and Stop enqueue the session for sync; SubagentStart and SubagentStop record run events.
  - It returns in under 100 ms, and a detached `ax sync --queue` does the work.
  - Codex needs the hook trusted once via `/hooks`. Codex's `notify` slot stays with Computer Use.
- **launchd jobs:** `ax sync` and `ax usage snapshot` every 30 minutes; `ax vault commit --push` hourly.
- **`ax skills link`:**
  - Symlinks each skill in this repo into `~/.claude/skills/` and `~/.agents/skills/`.
  - Deletes the old copy in `~/.codex/skills/delegation`, a deprecated folder whose copy would show up twice.
  - Work skills stay where their own installers put them and never enter this public repo.

### 9. Jobs: `ax job` (after the weekend)

Any long job an agent starts gets one key that both tools can register, read and wait on. That covers a heredoc, a script, Seamless or a notebook, and nothing has to be imported in the job's own environment. This step builds the core. Wake-ups, phone pushes, the background service and the ETA come next.

- **Commands.**
  - `ax job new KEY [--total N] [--unit U]` registers a job fed only through its events file, and prints that file's path.
  - `ax job watch file|pid|sagemaker|seamless REF` registers a job that a source can check, and returns at once.
  - `ax job run [--key K] -- CMD …` starts CMD detached and records its exit code. Piped stdin, such as a heredoc, is saved and replayed. Output goes to the job's `output.log`.
  - `ax job ls` and `ax job show KEY` refresh active jobs and print them, with `--json` for agents.
  - `ax job wait KEY [--until …] [--timeout S] [--stall-after S]` blocks without spending tokens. Exit codes:
    - 0: done;
    - 1: failed;
    - 2: stopped or ended;
    - 3: stalled;
    - 4: the source check kept failing for `--error-after` seconds (10 minutes by default);
    - 124: timed out;
    - 69: no such job.
  - `ax job poll` refreshes every active job once, for a scheduler later. `ax job forget KEY` drops one.
- **File protocol.** Each job has `~/.local/share/ax/jobs/<key>/events.jsonl`. A producer appends one JSON object per line, from any language and with no ax import (`echo '{"done": 10}' >> "$F"`):
  - `{"done": 120, "total": 500, "unit": "rows"}` reports progress; either count alone is fine.
  - `{"stage": "scoring"}` and `{"message": "…"}` record a stage or a note.
  - `{"status": "done" | "failed" | "stopped", "message": "…"}` ends the job. `{"exit": 0}` ends it as done; any other code ends it as failed.
  - Other keys are kept as event data. A line still missing its newline is left for the next read.
- **Storage.** `~/.local/share/ax/jobs.db`, kept apart from `ax.db` because a parser change rebuilds that.
  - Table `jobs`: key, kind, ref, source options, status, stage, done, total, unit, message, timestamps, the last check error, and the events-file offset. It also records the launching agent session (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`) for wake-ups later.
  - Table `events`: one row per change, numbered globally, so later work can wait on "anything after N" and fit ETAs.
- **Statuses.**
  - The five: running, done, failed, stopped, and ended (a process vanished without a known result).
  - A failed check keeps the last status and records `check_error`.
  - "Stalled" is derived: running, but unchanged for `--stall-after` seconds.
- **First sources.**
  - **`file`:**
    - a `.jsonl` file is read as protocol lines from its last offset;
    - a `.json` file is reread at each check, using `--done-key`, `--total-key`, `--status-key` and `--stage-key` as dotted paths;
    - with `--done-when PATH`, the appearance of that file means done.
  - **`pid`:** alive or gone. The process start time guards against PID reuse.
  - **`sagemaker`:**
    - processing, training or transform jobs, read through `aws sagemaker describe-*` (no boto3);
    - InProgress, Completed, Failed, Stopping and Stopped are mapped;
    - missing or expired credentials become a check error.
  - **`seamless`:**
    - the processing job's status, plus progress;
    - progress comes from Seamless's `/api/state` when `--state-url` is given, or else from the `SEAMLESS_PROGRESS` lines in CloudWatch;
    - progress is summed across workers for the active stream, the way Seamless does;
    - the dashboard stays Seamless's.
- **Following a job: a mini dashboard and ntfy.** A simplified Runwatch for one job.
  - `ax job follow KEY` runs a small follower in the foreground. With `--detach` it runs in the background and prints the dashboard link.
  - `--share` and `--notify` on `new`, `watch` and `run` start a detached follower. Its link goes to stderr, so the key or path on stdout can still be captured.
  - There is one follower per job. Its address is kept in the job's `follower.json`, so a second `follow` prints the running one's link instead of starting another. The follower exits when the job ends and `--linger` has passed (120 s by default), or on SIGTERM.
  - **Dashboard:**
    - one page, built with the standard library, showing:
      - status, a progress bar with percent and counts;
      - stage, message and any check error;
      - elapsed time, last update and recent events;
      - the tail of `output.log`, but only with `--show-log`;
    - JSON at `/api/job`, refreshed every 5 s;
    - no actions.
    - Every request needs a random token. The link carries it once, and an HttpOnly cookie keeps it after that. Only localhost names, the LAN address and the tunnel's host are served.
    - Only the job's state is exposed, never the archive.
  - **Sharing:** `--share none|lan|cloudflare`.
    - Cloudflare runs `cloudflared tunnel --url … --no-autoupdate` and reads the `trycloudflare.com` link from its output.
    - It keeps draining that output, because a full pipe stalls cloudflared.
    - It checks the public link every 30 s and replaces the tunnel after three failures. The new link goes to ntfy.
  - **ntfy:** server and topic come from `[notify]` in `config.toml`, or from `AX_NTFY_SERVER` and `AX_NTFY_TOPIC`. A protected server also takes `AX_NTFY_TOKEN`. Messages:
    - started, with the dashboard as the click target;
    - progress every `--every` minutes (15 by default; 0 turns it off);
    - stage changes, with `--notify-stages`;
    - stalled, with `--stall-after`;
    - done, failed, stopped or ended;
    - a replaced link.
    - Each send is retried three times with backoff and recorded as a job event.
    - On ntfy.sh the topic name is the only password, so the dashboard link goes to ntfy only because the topic is yours.
- **Next:**
  - a shared "jobs" skill;
  - `--wake`;
  - a background service that holds the AWS session;
  - the ETA, with priors and calibration;
  - a Jobs panel in `ax serve`;
  - Runwatch and Tools MCP sources;
  - tqdm parsing for `run`.

Done when:

- a heredoc job started with `ax job run`, and a job fed through its events file, each reach done or failed, and `ax job wait` returns the matching exit code;
- tests show `ax job watch sagemaker` and `ax job watch seamless` reporting status and progress from recorded AWS responses, and one real job confirms it;
- no source needs ax installed in the job's environment.

### 10. Learner, next version (agreed and built 2026-10-25)

Our own design, inspired by claude-reflect (MIT; its code was read) and cass-memory (its published README only; its license excludes Anthropic, so no code was read or run). Neither is reused.

- **Taken from claude-reflect:** an explicit "remember" fast path; praise kept as an approach to repeat, with a forward-pivot filter; guardrail phrasings; structural filters for questions and task requests; tool-rejection reasons; recurring errors turned into fixes; a pass that merges duplicates and flags contradictions.
- **Taken from cass-memory:** rules live on after acceptance. Evidence counts for and against, the against side weighted 4×; confidence halves every 90 days without new evidence; maturity goes from active to established to proven; a rule that keeps failing becomes a warning or a guard; task-scoped retrieval, later.
- **Left out:** agents grading their own rules; rules adopted without the user; a session diary (the results ledger was dropped); per-project queues; Claude-only reading.
- **What the history holds:** 95% of the user's 9,462 messages are in Codex. 93 use "remember", "from now on", "going forward" or "always" (40 once "always" is left to the correction phrases); about 480 open with praise (210 once praise that only moves on is dropped); 2 Claude tool rejections on disk carry a reason (the earlier count of about 20 was wrong).
- **Frustration moments:** about 14 clear ones, all in Codex and mostly in auto-classifier (August–October), most after a long autonomous run went wrong. The current learner scanned 4 and turned 1 into a rule, because frustration rarely states a rule: the lesson is in the turns before it.

**Phase 1, about a day:**

- **New signals:** explicit "remember" messages, where one session is enough; praise, kept with what the agent had just done; tool-rejection reasons.
- **Frustration moments:**
  - **Detect** them with cheap markers (disappointment and frustration words, exasperated phrasing, capitals, `!!` or `?!`), then have Haiku confirm with the session context, so polite but firm messages count too.
  - **Analyze** the episode before each one (the turns since the run or request started) and extract the lesson as a proposal.
  - **Weigh** one as strong evidence, worth several ordinary corrections.
  - **Count** them per week in the scorecard.
- **Tidy pass:** merge near-duplicate proposals and flag contradictions before review (today: `no-backward-compatibility` and `no-multilabel-compat`).
- **Guard proposals:** a checkable "never" rule comes with a generated pattern, tested against the archive. It must catch the commands from its evidence and stay quiet on recent harmless ones.
- **Fix proposals** from the scorecard's recurring errors.

**Phase 2, about a day:** the rule lifecycle.

- `ax sync` updates each rule's support, recurrences, guard blocks and overrides.
- Confidence decays with a 90-day half-life, and recurrences count 4×.
- Two recurrences escalate a rule to a guard or a rewrite; stale rules are put up for retirement; overrides propose a narrower scope.
- Maturity shows in Obsidian's Rules view and in the scorecard.

**Later, when the profile outgrows its always-loaded block:** task-scoped retrieval through a prompt hook; in-session capture with a "learning captured" note; skill candidates at six or more sessions.

## Schedule

### Saturday, afternoon and evening

1. **Setup (30 min).**
   - `brew install --cask obsidian`.
   - Create `~/Vaults/agents` and its private repo.
   - Set up the uv project for `ax` in this repo.
   - Write synthetic fixtures for both providers.
2. **Archive (3–4 h).** Parsers, store, renderer, raw backup, `ax sync` and `ax doctor`.
3. **Search and vault Git (1.5 h).** FTS5 and `ax search`, redaction, the gitleaks gate, first push, `Sessions.base` and `Home.md`.

### Sunday

4. **Usage (2 h).**
5. **Glue (1 h).** Hooks, launchd jobs and `ax skills link`.
6. **Runs (2–3 h).**
7. **Research ledger and skill (2 h).**
8. **Dashboard (2 h),** only if steps 1–7 are done.

Cut line: steps 1–5 must ship, 6–7 should, and 8 and every stretch item may slip.

## How we build it

- **One context per step.** Each step is one agent session that gets this plan section and the fixtures.
- **Tests first** for the parsers, redaction, the forecast and the guard's exit codes.
- **Stack.**
  - Python 3.12 via uv; install with `uv tool install -e .`.
  - Skill scripts stay standard-library only so the skills remain portable.
  - Dependencies: typer, rich and zstandard. Dashboard extras: fastapi, uvicorn and jinja2. Dev: pytest and ruff.
- **Synthetic fixtures only,** never real transcripts, because this repo is public.

## After the weekend

- **Cheap handoffs.** `ax handoff <session>` does a deterministic extraction, compresses it with Haiku, and writes the result to `Projects/<project>/Handoffs/`.
- **Native supervisor agents.** A Haiku subagent in Claude, and a Codex counterpart, follow a run from the other tool through `ax runs wait` and relay progress and questions.
- **`ax mcp` server,** if the CLI plus skills prove awkward for agents.
- **More skills and views.** Architecture Steward and UI-design skills; Agenttrail Map over `Projects/`.
- **Chat exports.** ChatGPT and Claude.ai exports through convoviz, if wanted later.

## Risks

| Risk | Mitigation |
| --- | --- |
| Transcript formats change | Tolerant parsers, fixtures per version, and `ax doctor` counts of unknown records |
| Secrets or sensitive work data reach GitHub | Redaction, gitleaks gate, exclusions and a private repo. Work data on a personal account is a deliberate choice; revisit it if policy requires. |
| Team usage numbers unavailable | The `/usage` adapter reports freshness and shows "unknown", never a guess |
| Hooks slow or untrusted | Enqueue only, a launchd sweep as backup, and `ax doctor` checks hook install and Codex trust |
| Scope | The cut line above, with the dashboard last |

## Open items

- **CLI name.** `ax` is free on this Mac; rename it before step 1 if you prefer something else.
- **Vault names.** Path `~/Vaults/agents` and repo name `agent-vault`.
- **Team statusline.** Check whether statusline `rate_limits` appears on a Team seat (a one-line test).

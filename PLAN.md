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
- **The learner's next version built 2026-10-25** (component 10, phases 1 and 2):
  - **Scan:** 1,758 candidates: 1,213 correction phrases, 210 praise, 99 frustration markers, 13 explicit requests, 6 after interruptions, 2 refused tool calls, 273 Codex preference signals. Haiku confirmed 62 of the 99 frustration markers from their episodes; the scorecard's weekly count peaks at 10 in W42 (the 24-hour autonomous run) and 8 in W40.
  - **Calibration on the real archive:** the first `propose` wrote 88 proposals, because "in the future" counted phrasing like "for future use" as a request to remember. It now counts only at the start of a sentence, and at most 20 proposals wait at once, strongest first: 19 wait now and 54 more queue behind them. The first `fixes` prompt turned 17 of 37 recurring errors into generic advice; a fix must now name a command, tool or path, and 2 remain (macOS `timeout`, the IAM scripts path).
  - **Tidy and guards:** the tidy pass merged `no-multilabel-compat` into `no-backward-compatibility`. No guard passed: three "never" proposals aren't about commands, and one pattern missed its own evidence.
  - **Lifecycle:** `ax sync` writes each active rule's evidence, confidence and maturity; all eleven are new (adopted 2026-10-24); `stage-explicit-paths` leads with 9 restating sessions and 5 guard blocks. Recall: 10 of 11 active rules rediscovered (missed: `ds-models-uv`).
  - **Not built:** the "Later" items, which wait for the profile to outgrow its always-loaded block.
- **Independent review of the learner, 2026-10-25:** one Opus worker through `ax brief review` ($1.76, 27 turns; it could not run the tests) found 15 defects, all verified and fixed test-first the same day:
  - **Episodes:** a frustrated message of 60 characters or more became its own episode, so 68 of the 99 moments had been labelled from the message alone. Relabelled from whole episodes, 54 of 100 are confirmed (62 before); the weekly count peaks at 10 in W42.
  - **Lifecycle:** `accept` now dates the adoption, so evidence from the queue no longer counts against a rule; praise and Codex memories count as support, not recurrences; overrides count only after adoption; dates are local; guarding a rule counts as its review; a broken rule note no longer fails every sync.
  - **Vault safety:** unknown frontmatter keys (tags, aliases) survive every rewrite; refreshing a proposal replaces only the learner's own summary; tidy and guards re-read notes after the model answers.
  - **Guards:** patterns are tested on whole commands from the transcripts, including those Codex runs inside its `exec` code: 58,767 commands in 30 days, against 21,421 archived first lines. Evidence commands come from the agent's turn before the correction.
  - **Smaller:** matching through every topic in a group, fixes sharing the 20-proposal queue, markers that ignore code, SQL and acronyms, tidy ignoring non-string ids, labels merged with a concurrent run. Sync now labels up to 40 new candidates per run by default (`[learn] label_on_sync = false` turns it off).
  - **After the fixes:** 19 proposals wait (6 new ones from whole episodes) and 45 more queue, after tidy merged `test-after-refactor` into `reliable-autonomous-work` and flagged `pro-fire-and-forget` against `implement-directly`. Recall is 9 of 11 active rules (missed: `ds-models-uv`, `no-green-ui`).
- **Conversations you can build on, and one search, built 2026-10-25** (component 11):
  - **Handles and links:** `ax here` and `ax recall` (outline, card, focused import) work on the real archive; the rebuild found 1,084 mention links and 290 notes now carry `builds_on`.
  - **Search:** qmd 2.8.3 indexes 2,517 notes and memories (32,000+ chunks, about 25 minutes to embed) and Semble 0.7.0 the 17 repos. The first real search took 34 s and returned CSS for a question about a decision; with qmd and Semble in parallel, the daemon (`ax index serve`), 20 reranked candidates and code weighted down for questions that name no code, it takes about 5 s. The five starter questions in `~/.config/ax/find-questions.yml` are all found in the top 5, with or without reranking; the user's own 20–30 questions are still to be written.
  - **Agents:** `ax mcp` serves find, recall and here; it is not registered in either tool yet (`ax mcp install --apply`).
- **Job wake-ups that reach the conversation, 2026-10-25:** a Codex job's wake failed because the app held the thread open ("already has an active writer") and nothing told the user. Wakes now go through `codex queue` to an open thread (tested live: a note reached the user's open thread within seconds), report a Claude copy by its id (tested live with a throwaway session), push an alert when no route reaches the conversation, and start a failed job's note with a Haiku diagnosis; a Haiku health check reads a running job's log every 30 minutes. The live `news-research-mine-20261025-r2` job got a description and a follower running this code.
- **Recent-work digest and shared memories built 2026-10-25** (components 12 and 13): the start hook is installed in both tools. A fresh Claude conversation saw the digest's handles and Codex's memory summary without running a tool; Codex skips the hook until the user trusts it with `/hooks`. Sync copied 57 Claude memories into Codex's ad-hoc notes.
- **The ax skill and ax todo built 2026-10-25** (components 14 and 15): `skills/ax/SKILL.md` maps all 23 commands and is linked into both tools; a test fails when a command is missing from it. To-dos are vault notes in `Todos/`, shown in the start digest, in `ax recall` of the conversation that raised them and in a Todos base on Home. Live, a fresh Claude conversation listed the open to-do from its digest.
- **Moved conversations and repo docs, 2026-10-25:** a conversation moved from a scratch workspace to a repo is now filed under that repo (the atelier conversation that also built lathe had been filed under its scratch folder, so neither project's digest showed it). `ax find` also searches each repository's docs (README, plans, `docs/`): about 430 documents across 18 repos. Sync refreshes the index at least hourly. A generic question can still rank a large docs repo above the right one; `--project` or the user's own evaluation questions are the remedy.
- **The ax app's first screens built 2026-10-25** (component 16, screens 1 and 2): generated from atelier into `ui/`, built into `src/ax/web/` and served by `ax serve` (the old page moved to `/classic`).
  - **Now:** what waits for you (proposals, review flags, to-dos, failed or flagged jobs, usage nearly used or running out within a day), with accept, reject, keep, retire, guard (marked as a Haiku call), done, drop and add, each confirmed first and run through the same functions as the CLI; running jobs; recent conversations with copyable handles. Live, it showed 23 proposals, 4 flagged jobs and T1.
  - **Usage on every screen:** each Claude window, Codex's one window (weekly; it has no 5-hour window) and Codex's credit balance, which ax now also reads (`ax usage` prints it). The server asks Claude's `/usage` for fresh figures every five minutes in the background (a built-in command: no model call, no transcript), so the band is never a stale cache.
  - **Reader:** every vault note, read-only, with `[[wiki links]]` resolved by name (shortest path wins) or path, callouts as asides, properties as a table, and raw HTML never rendered. A 470,000-character conversation note renders.
  - **Access:** a token kept owner-only in the data folder, then a Strict, HttpOnly cookie; actions need JSON from the app's own origin. `ax serve --share cloudflare --notify` opens a quick tunnel for the phone and sends the link by ntfy; that link carries a token that dies with the run. Not yet tried live: it publishes the vault's reader through the tunnel.
- **The app installable and always served, 2026-10-25:** the app is a progressive web app (manifest, icons, a service worker that opens it from its last page while the server restarts; Chromium reports no installability errors). `ax app start|stop|status|open` runs it in the background for any agent, and `ax app service --apply` loads launchd's `com.ax.app`, which keeps `ax serve` on 127.0.0.1:8765 from login (tested: a killed server was back within a second). On this Mac the app now opens without a token, so an installed app works whatever storage its browser gives it; through the tunnel every request still needs the run's token.
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

### 11. Conversations you can build on, and one search (agreed and built 2026-10-25)

Builds on the morning's research session (`9fe6d7e6`): qmd for conversations and docs, Semble for code, PageIndex-style outlines later, LightRAG set aside. ax's session notes are already the dialogue-only, redacted markdown that research named as the first step.

- **Handles:** a conversation's handle is the last eight characters of its session id, the same short id its note's file name ends with (`ax:9fe6d7e6`). `ax here` finds the conversation it runs in from `CLAUDE_CODE_SESSION_ID` or `CODEX_THREAD_ID` (the live transcript when both are set), syncs it and prints the handle and note. `ax recall` accepts a handle, a full id, an id prefix or a note name.
- **Recall:** `ax recall <handle>` prints an outline with no model call: title, tool, project, dates, the user's turns as a table of contents, where it ended, the files it touched, its links and the note's path. `--card` adds a card Haiku writes once per conversation (goal, outcome, decisions, open items, facts), cached until the note changes. `--for "task"` has a model read the whole conversation against the task and return only what the task needs, with turn times as citations.
- **Links:** a recall run inside a conversation records "this builds on that"; sync also records mentions of another conversation's handle (`ax:<handle>`, `ax recall <handle>`) or full id. Sync renders them into the note as `builds_on` links, and Obsidian supplies the backlinks and the graph.
- **Search:** `ax find` asks qmd (conversation notes, Claude and Codex memories, the vault's own notes) and Semble (the repositories under `~/Repos` plus listed extras) and merges their rankings, labelling each hit conversation, memory, note or code. Conversation hits carry their handle; filters by project, date and tool apply through the archive. `ax find setup` registers qmd's collections and builds both indexes; `ax search` stays for exact words.
- **Agents:** `ax mcp` serves `find`, `recall` and `here` over stdio; `ax mcp install` prints the registration for both tools and applies it only with `--apply`. The session-recall skill teaches handles: give one when asked for "the id", recall one when asked to build on it.

### 12. A digest of recent work at the start of every conversation (agreed and built 2026-10-25)

Search and recall exist, but an agent searches only when it thinks to. The digest gives every new conversation a map of recent work, so "the gallery thing" or "the pricing work" is something it recognizes and recalls.

- **What it holds:** the user's own conversations of the last 7 days in both tools (no workers or subagents), newest first and at most 30: date, tool, project, title and handle; the current project's first. Then the jobs still running, with their descriptions. One line on how to use it: `ax recall <handle>` to bring one in, `ax find` to search wider.
- **How it gets there:** `ax hook start --tool claude|codex`, a `SessionStart` hook in both tools that prints the digest as `additionalContext`. It reads the archive only (no sync, no model) so it adds about a second, and it leaves out the conversation that is starting. The archive lags by up to 30 minutes (the last sync), which the digest says.
- **Installed by** `ax hooks install`, like the sync hooks; Codex asks the user to trust changed hooks (`/hooks`).

### 13. Memories shared between Claude and Codex (agreed and built 2026-10-25)

Share what each tool remembers through channels each already supports, never by mirroring files.

- **Claude to Codex:** `ax sync` writes each new or changed Claude memory (`~/.claude/projects/*/memory/*.md`) as a note in Codex's ad-hoc memory extension (`~/.codex/memories/extensions/ad_hoc/notes/`), redacted, saying which project it came from. Codex treats those notes as authoritative and merges them the next time it consolidates its memories. A changed memory edits its note; a deleted one rewrites its note to say so, since Codex's instructions forbid deleting notes.
- **Codex to Claude:** Claude's start hook adds Codex's `memory_summary.md` (about 8 KB: profile and preferences) after the digest. Codex's full `MEMORY.md` (500 KB) stays reachable through `ax find`.
- **Left out:** writing into Codex's `MEMORY.md` (Codex regenerates it) and a two-way file mirror. Working rules stay in `ax profile`, already compiled into both tools.

### 14. One ax skill that teaches every command (agreed and built 2026-10-25)

Three skills each teach a slice of ax (session-recall: find, recall, here, search; jobs: `ax job`; delegation: `ax brief`), and the rest of the 22 commands are documented only in the README, which agents don't read. One `ax` skill becomes the map; the focused skills keep their workflows.

- **What it holds:** for each command group, one or two lines on what it is for and when an agent should reach for it, grouped by need: finding past work (find, recall, here, search, index), long work (job), delegating (brief), working rules (profile, learn, the guard and stop check), measuring (scorecard, lab, usage, runs), research campaigns (exp), plumbing the user runs (sync, hooks, schedule, skills, mcp, vault, doctor, serve), and to-dos (todo, below). Each group points to its focused skill or `ax <group> --help` for detail rather than repeating them. Under about 150 lines.
- **What an agent may do alone:** read-only and reversible commands (find, recall, here, job show and wait, todo add when asked). It asks first for anything that spends (label, lab run, `recall --for`, briefs that launch workers), changes the user's rules or tools (learn accept or reject, profile compile --apply, hooks or mcp install --apply) or publishes (vault push).
- **How it stays true:** a test fails when a top-level command is missing from the skill, so a new command can't ship untaught. Description triggers: the user mentions ax, asks what ax can do, or the task touches past conversations, rules, jobs, usage, the vault or to-dos.
- **Where it lives:** `skills/ax/SKILL.md`, linked into both tools with `ax skills link ax --apply`, beside the focused skills.

### 15. A to-do list in ax, global or per project and conversation (agreed and built 2026-10-25)

Follow-ups get proposed and then lost between conversations ("an umbrella skill would help", "turn on the job service"). `ax todo` keeps them where every conversation sees them.

- **Storage:** one note per to-do in the vault's `Todos/` folder, so the user reads and edits them in Obsidian: frontmatter `id` (T1, T2, …), `status` (open, done, dropped), `scope` (global or `project:<repo>`), `from` (the handle of the conversation it was raised in), `created`, `closed`, `closed_in` (the handle that closed it); the text and any detail as the body.
- **Commands:** `ax todo add "text" [--global | --project P] [--detail "…"]` (the project defaults to the current repo, and `from` to the current conversation's handle, both from the environment); `ax todo list [--project P] [--all]`; `ax todo done ID`; `ax todo drop ID`. All take `--json`.
- **Where it shows:** the start digest lists the open to-dos of this project and the global ones (at most 10) with their ids and where they came from; `ax recall` of a conversation lists the to-dos raised in it; a `Todos.base` view (Open by scope, Done) and a "To do" section on Home show them in Obsidian. A conversation's handle in `from` links back to it.
- **Who adds:** the user, or an agent when the user asks to save something for later or declines a proposed next step with "not now" and wants it kept. Agents never add to-dos on their own initiative, so the list stays the user's.
- **Left out for now:** due dates, priorities and an MCP tool (agents in both tools have a shell).

### 16. The ax app: one place for people, built with atelier (agreed 2026-10-25; screens 1 and 2 built)

Most of ax is for agents, but approvals, reviews, watching work and catching up on it are the user's. Today that is split between a plain `ax serve` page, one small dashboard per job, and Obsidian. One atelier app replaces them.

- **What it is:** an app generated from atelier (kinds monitor and review station, theme `instrument`), its code in `ui/` in this repository. Its built pages ship inside the ax package, so `ax serve` runs it without Node; CI fails when the build is out of date.
- **How it talks to ax:** `ax serve` hosts the pages plus a JSON API and a live-update stream (server-sent events), on 127.0.0.1 with a token like the job dashboards' and the Origin check qmd uses. Every endpoint calls the same Python functions as the CLI, so an action in the app does exactly what its command does.
- **Screens, built in this order, each useful alone:**
  1. **Now:**
     - waiting for you: rule proposals and review flags, to-dos, failed jobs or ones a health check flagged, usage near a limit;
     - jobs running, with progress, estimate and log;
     - recent conversations with handles.
     - Actions: accept or reject a proposal; keep, retire or guard a rule; mark a to-do done or drop it, or add one. Each asks for confirmation.
  2. **Reader:** any vault note rendered as Markdown, with `[[wiki links]]` and `> [!note]` callouts resolved to app pages. It is read-only; edit notes in VS Code.
  3. **Conversations:** one search box (`ax find`, by source), and a page per conversation with its outline, the conversations it builds on and those built on it, its to-dos and its full note in the reader. The Haiku card is fetched on request, marked as a model call.
  4. **Rules and trends:**
     - rules with maturity, confidence and the evidence behind each;
     - frustration moments with their lessons;
     - the scorecard's weeks as charts.
- **Later:** jobs fold into the app and their own dashboards go; access from the phone through the sharing jobs already use; `ax serve` as a login service.

### 17. Retire Obsidian as the interface (agreed 2026-10-25)

The vault stays: plain Markdown in a git repository, readable in VS Code and in the app's reader. Obsidian as the way to see it goes, once the app covers each part.

- **Remove:** the Bases views (Sessions, Rules, Experiments, Todos), the Home note, the starter `.obsidian` settings, and `ax vault init`'s job of writing them. `ax vault init` keeps the folder structure and git setup. The scorecard note goes when the Trends screen exists.
- **Keep:** the notes and their frontmatter, `[[wiki links]]` (the reader resolves them, and VS Code shows them as text), `ax vault commit` and `push`. Nothing in the vault is deleted without the user: removing the old views and Home from the user's vault is a step the user approves.
- **Docs:** README, skills and PLAN stop pointing at Obsidian once the app replaces each part.

### 18. A rules workshop on spare allowance (agreed 2026-10-25)

A weekly window that ends its week with allowance left resets it unused. The workshop spends that allowance on the rules: strong agents consolidate and design them, and their work waits for the user as proposals.

- **When it starts:** by itself, with no approval per run; the user's rule to agree on agents first does not apply to this job. The scheduled sync (every 30 minutes) checks Claude's and Codex's main weekly windows. A window qualifies in its last 24 hours when it is spare by the usage band's rule (more than 1.5 × 100/7 % a day left) and enough is left above the floor for one agent. After a run, it starts again only while rule work and allowance both remain.
- **Who works:** Claude's spare allowance pays for Opus 5.5 agents (`claude -p` through the delegation worker), and Codex's pays for Sol 6.1 agents (`codex exec`), all at high effort. When both windows are spare, each tool's agents critique the other's drafts.
- **How many:** sized from the load and the allowance, going all in.
  - **Load:** the rule work waiting (proposals, rules flagged for review, merge candidates, frustration lessons and recurring errors no rule covers, `ax profile check` conflicts), grouped into topic clusters.
  - **Team:** a designer per cluster, one consolidator over all rules, one critic per tool, then one synthesis pass that writes the proposals.
  - **Pacing:** a supervisor launches as many agents as the allowance and the hours before the reset allow. It measures each agent's burn from the usage readings, and keeps launching until the work is done or the window reaches its floor.
- **Floor:** all in, down to a small floor (3% by default, `[workshop] floor`), so a run never stops the user's own work at a hard limit. Codex credits are never used: a run stops as soon as Codex reports its window reached or credits being spent.
- **What the agents may change:** nothing directly. They read the rules and their evidence, frustration episodes, the scorecard and the profile check, and return structured JSON. ax validates it and writes proposals (status `proposed`, `source: workshop`) plus one report note per run. Accepting, rejecting and merging stay with the user, in the app. Agents never edit a repository, commit, publish or delegate.
- **Seeing it:** an ntfy message when a run starts and when it ends (agents, allowance spent, proposals written). The run is an `ax job`, so the app shows it under jobs, and its proposals reach the waiting list with the report linked.
- **Commands:** `ax workshop status` (whether a run would start now, with how many agents and why), `ax workshop run [--dry-run]`, `ax workshop stop`; config `[workshop]` with `enabled`, `floor` and `max_agents`.
- **Build order, test-first:** the condition and the sizing (with `status` and `--dry-run`); the supervisor, with fake runners in tests; the validated writer for proposals and the report; the schedule check; the app's view; then a live `--dry-run` on the real archive before the first real run.

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

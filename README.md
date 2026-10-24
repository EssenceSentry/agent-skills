# Agent skills

Reusable skills for working with Claude Code, Codex, and ChatGPT.

## Available skills

| Skill | What it provides |
| --- | --- |
| [delegation](skills/delegation/SKILL.md) | Authorized Claude/Codex workers, usage and lifecycle helpers, ChatGPT Pro consultation, native conversation messaging and history retrieval, and technical infographics. |
| [research-director](skills/research-director/SKILL.md) | How agents run research campaigns through `ax exp`: weigh each experiment by the decision it can change, re-rank after every result, stop when results change nothing. |
| [session-recall](skills/session-recall/SKILL.md) | When and how agents search past Claude Code and Codex sessions with `ax search`, and how to cite what they find. |

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
| `ax search "words" [--json]` | Find past sessions by what was said in them |
| `ax runs` (`watch`, `show`, `stop`) | Delegated, background and subagent runs from both tools in one list |
| `ax exp` (`init`, `propose`, `list`, `start`, `finish`, `abandon`) | Research campaigns whose experiments must pass a value gate |
| `ax usage` / `ax usage guard` | Allowance left per tool and window, a forecast to reset, and a guard for scripts (exit 0 safe, 1 below, 69 unknown) |
| `ax serve [--open]` | A local dashboard of usage, runs, campaigns and recent sessions |
| `ax vault init` / `commit` / `push` | Starter Obsidian views; a commit gitleaks has scanned; a push only to a private GitHub repo |
| `ax hooks install` | Hooks in Claude Code and Codex that sync when a session ends |
| `ax schedule install` | A launchd job that syncs every 30 minutes |
| `ax skills link NAME…` | Link this repository's skills into both tools |
| `ax job` (`new`, `watch`, `run`, `ls`, `show`, `wait`, `follow`, `unfollow`, `poll`, `forget`) | Long jobs any agent can register and wait on; see below |

`hooks install`, `schedule install` and `skills link` print what they would change
and do nothing without `--apply`.

### Jobs

`ax job` tracks long work wherever it was started, with nothing to import in the
job's own environment.

- **Register:**
  - `ax job new KEY` prints an events file. A producer appends JSON lines to it: `{"done": 10, "total": 40}`, `{"stage": "scoring"}`, `{"status": "done"}`, `{"exit": 0}`.
  - `ax job watch file|pid|sagemaker|seamless REF` lets ax check the job itself.
  - `ax job run -- CMD` starts a command detached and records its exit code. A heredoc piped in is replayed to the command, and the command finds its events file in `$AX_JOB_FILE`.
- **Wait:** `ax job wait KEY` blocks without polling an agent. Exit codes:
  - 0: done;
  - 1: failed;
  - 2: stopped or ended;
  - 3: stalled;
  - 4: the source check kept failing for `--error-after` seconds (10 minutes by default), as with a mistyped SageMaker name or expired credentials;
  - 124: timed out;
  - 69: no such job.
- **Estimate:** `ax job show` and `ls` give the median time left and an 80% interval. The estimate comes from the job's own progress, plus finished runs of the same family (kind, unit, key without its numbers). `ax job eta-report` checks stored estimates against real finishes.
- **Wake:** `--wake auto|claude|codex` on `new`, `watch`, `run` or `follow` resumes the session that registered the job once it ends, with a short note on how it ended. Codex resumes through `codex exec resume`, Claude Code through `claude --bg --resume`, and `ax job wake KEY --dry-run` shows the command. For a Claude session that is still open, run `ax job wait KEY` as a background command instead; its exit wakes that session.
- **Follow:** `ax job follow KEY --share none|lan|cloudflare --notify --detach`, or `--share` and `--notify` on `new`, `watch` and `run`.
  - It serves a token-protected, read-only page for the job, optionally through a Cloudflare quick tunnel.
  - It sends ntfy messages for the start, progress, new stages, stalls and the end.
  - It stops two minutes after the job ends.
  - Set the ntfy topic in `[notify] topic` in `config.toml`, or in `AX_NTFY_TOPIC`. On ntfy.sh the topic name is the only password, and messages carry the dashboard link.

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

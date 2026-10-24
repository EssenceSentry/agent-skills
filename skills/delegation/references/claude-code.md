# Claude Code delegation

Read this after the shared [delegation skill](../SKILL.md) when using Claude, including usage-only requests. These mechanics apply to Claude workers, not ChatGPT Pro. Set `DELEGATION_SKILL` to the installed delegation skill directory.

Model selection, exact IDs, evidence and examples: [model-routing.md](model-routing.md).

## Inspect usage and reset times

Run before a batch, periodically during a long batch (about 5–10 minutes), after a batch, and after a limit response:

```sh
python3 "$DELEGATION_SKILL/scripts/usage.py" --json
```

The helper refreshes `/usage` through the authenticated CLI, then reads only quota data from its local config. It never extracts credentials. It returns all three windows, remaining percentages, absolute and local reset times, countdowns, and snapshot age.

- Require a fresh reading for a large batch. Check `refresh_verified`, `snapshot_status`, and each window's status. Exit 2 means incomplete freshness/availability; inspect the report.
- `--cached` is an offline snapshot. Missing limits mean unknown, not zero or unlimited. A passed reset does not prove the new period is unused.
- Fable has a distinct model allowance, but can also draw from the overall weekly allowance. **Do not add the percentages or treat Fable as an unrelated free pool.** Check all three before Fable work.
- Report observation and reset times, including timezone. Preserve `provider_is_active` as diagnostic data; false does not authorize ignoring a limit.
- Allowances are shared with the user's other sessions. Read `claude agents --json` if useful, but do not interfere with those sessions.

### Use capacity productively

Use the shared skill's atomic-context policy to choose assignments before choosing concurrency. Ample headroom permits more useful independent work; it does not justify fragmenting a coherent investigation. Prefer fewer well-informed workers when they can resolve related questions together. Be willing to launch a large batch when independent contexts and expected value justify it.

No count is a productivity target. Large concurrent batches can be useful, but the user must authorize their count, model and reasoning effort before launch. Stay within those bounds; obtain fresh approval before adding workers or raising settings. A pilot is useful when cost or output quality is uncertain, not a prerequisite for every batch. Give each worker clear ownership, avoid conflicting writes, and report the model and assignments in one compact launch update.

Before a substantial batch, check the live five-hour, weekly, and relevant model allowances and reset times. Preserve practical headroom for verification, synthesis, integration, and likely follow-up; do not allocate the whole window to first-pass investigation. Use observed consumption and useful returns to adjust later waves. Other sessions share the allowance, and token counts or dollar estimates do not provide an exact quota conversion. Near a reset, advance worthwhile authorized work that can finish or leave a usable checkpoint; expiring allowance alone is not a reason to launch agents.

Near exhaustion, reduce concurrency, continue useful independent work, or arrange a scheduled continuation near the reset using the [shared continuation policy](../SKILL.md#end-the-turn-and-resume-when-useful). Refresh actual allowance on return before dispatching; a scheduled time is not proof that capacity is available. When Fable's allowance is tight, use Opus for suitable tasks. A failed refresh need not stop independent parent work. Do not automatically enable credits, purchase usage, change accounts, or switch to API billing. Existing pay-as-you-go settings may already be enabled; the cost cap is an estimate cap, **not** a guarantee against charges. Stop dispatching before exhaustion unless paid overage is authorized.

Read [operations.md](operations.md) for quota troubleshooting, compatibility and billing interpretation.

## Independent review

Use a fresh reviewer context with requirements and neutral evidence. Ask for severity-ranked findings, concrete evidence or counterexamples, assumptions, and coverage gaps. Keep the implementation session and its self-assessment out of independent review. The parent adjudicates findings; agreement alone is not proof.

## Prepare a bounded assignment

Read the actual scope-defining artifact first. Include:

1. Objective, the coherent question or workflow being owned, and exact acceptance criteria.
2. Absolute working directory, relevant inputs, cross-module or cross-repository dependencies, shared assumptions, and separately identified owned files for edits.
3. Applicable user and repository rules, including relevant `AGENTS.md`/`CLAUDE.md` and nested rules. Include their content or explicit required reads accessible to the granted tools.
4. Constraints: preserve unrelated work; no commits, pushes, deployments, external messages, credential changes, or recursive delegation.
5. Output contract: a concise summary of the result or patch, actionable findings with file locations, actual validation results, uncertainties and blockers. Keep detailed evidence in local artifacts and link to it; include enough coverage information to judge completeness without loading the full transcript.

Supply enough relevant context to reason end to end without forcing each worker to rediscover the same background. Write boundaries should prevent conflicts without hiding needed callers or consumers. Avoid unrelated conversation dumps or credentials. Don't prime independent reviews with an expected conclusion. For extraction, use stable IDs, a schema, an abstention path, and a parent-checked pilot before scaling.

Start the brief with `ax brief implement|review|scout|continue --repo /absolute/repo --task "…" [--path FILE] [--accept CRITERION] [--diff RANGE] [--session ID]`. It fills in points 2–4 from the user's profile: the rules marked for workers in that repository, the repository's `AGENTS.md`/`CLAUDE.md` as required reads, the permission profile for the kind of work, and a budget halved when a Claude window is at 80% or more. It writes the brief under `~/.local/share/ax/briefs/` and prints the runner command. Add the task's own inputs and evidence to the file, then show the printed plan for approval before running the command.

The runner uses `--safe-mode`, disabling automatic instructions, plugins, hooks and MCP customization while retaining authentication and permissions. **The brief must carry applicable instructions.** It neither installs a repository `CLAUDE.md` bridge nor changes global configuration. Safe mode is not an OS sandbox.

Use a suitable isolated checkout for writes, or create a managed worktree through the host tool when needed. Inspect dirty state and preserve necessary uncommitted inputs. Simple disjoint work can use explicit file ownership in an authorized working directory. Keep private logs and briefs outside published source.

## Launch, monitor, follow up, stop

The runner needs Python 3.10+, Claude Code **2.1.283+**, and a working Claude subscription login. Verify `claude --version`; read [operations.md](operations.md) on first use. If the host sandbox hides Keychain auth, use approved host execution; don't extract tokens or bypass permissions.

```sh
python3 "$DELEGATION_SKILL/scripts/worker.py" run \
  --cwd /absolute/workspace \
  --brief /absolute/task/brief.md \
  --run-dir /absolute/task/claude-runs/review-01 \
  --model opus --effort high --profile read \
  --max-cost-usd 5 --timeout 900
```

Use the host's asynchronous process tool with a short initial yield. Save its process handle and run directory; continue independent work. Launch independent jobs in parallel with unique output directories.

Profiles:

- `none` has no tools.
- `read` provides Read, Glob and Grep, with no shell.
- `edit` adds Edit and Write, with no shell.
- `inspect` is `read` plus read-only shell commands: `git status`, `diff`, `log`, `show`, `branch`, `rev-parse` and `ls-files`, and `ls`, `wc`, `rg`, `grep`, `head`, `tail`, `cat`, `file`, `stat`, `shasum`, `pwd` and `which`. Use it for reviews.
- `verify` is `edit` plus those commands and the test and lint runners (`uv run pytest`, `ruff` and `pyright`, their `.venv/bin` forms, and `python3 -m pytest` or `unittest`). Use it for implementation.

No profile allows unrestricted Bash, `python -c`, or a git command that writes. Add any other required command explicitly, e.g. `--allow-tool 'Bash(python3 -m unittest discover -s tests)'`, after inspecting its effects. `dontAsk` fails unapproved tools instead of waiting on prompts. Never repair a denial with bypass permissions.

Rendered-UI review needs actual screenshots or render artifacts supplied by the parent, or a narrowly allowed project browser-test/capture command consistent with current tool policies. The default profiles do not provide a browser, and safe mode disables MCP/custom tools. Give the worker the necessary evidence or permissions explicitly. Without rendered evidence, label the result a static code review rather than a visual check.

```sh
python3 "$DELEGATION_SKILL/scripts/worker.py" status /absolute/task/claude-runs/review-01
python3 "$DELEGATION_SKILL/scripts/worker.py" stop /absolute/task/claude-runs/review-01
```

Monitor the host process and `run.json`; inspect `events.jsonl` and `stderr.log` when needed. Heartbeats update every five seconds. Quiet reasoning isn't proof of a hang; a stale heartbeat isn't success. Share meaningful progress, not every poll. Stop affects only this runner's own child, never a PID from the user's session list.

The runner's five-second status heartbeat is a liveness record, not a Codex wake-up trigger. If the remaining wait is long and there is no useful independent work, use the shared scheduled-continuation policy instead of keeping the parent in a polling loop. Verify that the chosen host process mechanism survives ending the turn before relying on it; this guide does not claim that every asynchronous process handle is durable. The follow-up reads the owned run directory and checks the actual outcome before reviewing or resuming the worker.

Read the answer, wait for process exit, then send a follow-up to the exact owned session in a new run directory:

```sh
python3 "$DELEGATION_SKILL/scripts/worker.py" run \
  --cwd /absolute/workspace \
  --brief /absolute/task/follow-up.md \
  --run-dir /absolute/task/claude-runs/review-02 \
  --resume-run /absolute/task/claude-runs/review-01 \
  --model opus --effort high --profile read \
  --max-cost-usd 8 --timeout 900
```

The budget applies to the new invocation; restored conversation costs don't consume it. Result cost totals can include the earlier conversation, so don't sum resumed cumulative totals. Keep model/context policy consistent unless intentionally changing it. Resume only the latest finished run in a lineage. The helper blocks concurrent resumes. Active-turn steering isn't implemented here: stop, inspect, and resume when necessary.

## Result interpretation

`completed` means the CLI returned successfully, not that the work is correct. Start with `answer.md`, compact status/result metadata, the actual diff, and targeted evidence. Inspect full transcripts only when a failure, uncertainty, or consequential claim warrants it. `needs_review` records permission denials; `failed`, `timed_out`, and `stopped` are incomplete. `cleanup_failed` requires verifying and stopping the owned child through the host. Check actual model records rather than only the requested ID, and preserve routing changes. Apply the shared verification and user-reporting guidance.

## Maintenance

Researched and live-tested 2026-09-27 on **2.1.283**, including Opus 5.5, exact-session follow-up, cumulative result costs, and fresh quotas. Usage also works on 2.1.220; Opus 5.5 itself requires at least 2.1.280. The helper requires 2.1.283+ for verified resume/cost behavior. Aliases and schemas can change: recheck sources and installed help when needed. Update `MODELS` when intentionally adopting newer models. After helper changes run `python3 scripts/test_helpers.py`.

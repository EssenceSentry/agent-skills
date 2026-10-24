---
name: jobs
description: Register, watch, wait on and report long-running work with `ax job` instead of sleep loops or repeated status commands. Use whenever a command will run longer than a couple of minutes, when you start or inherit a SageMaker, Seamless, Runwatch or Tools MCP job, when you need to wait for something to finish, or when the user wants progress on their phone.
---

# Jobs

`ax job` keeps long work visible without spending tokens: it records progress,
estimates the finish with an 80% interval, ends waits on failure, and can wake your
session when the job ends. Every command takes `--json`.

## Register the work

- **A command you start:** `ax job run --key KEY -- CMD ARGS`. It runs detached and
  records the exit code. A heredoc works: `ax job run --key KEY -- python - <<'PY' … PY`.
  A tqdm bar in the output counts as progress; for exact progress, the command can
  append `{"done": 10, "total": 40}` lines to `$AX_JOB_FILE`.
- **Something already running:**
  - `ax job watch pid PID`
  - `ax job watch sagemaker NAME [--type training|transform] [--profile P]`
  - `ax job watch seamless NAME [--state-url URL]`
  - `ax job watch runwatch RUN_DIR`
  - `ax job watch tools MCP_JOB_ID` (a job of the auto-classifier Tools MCP)
  - `ax job watch file PATH` (a JSON progress file)
- **A producer you write:** `F=$(ax job new KEY --total N --unit rows)`, then append
  JSON lines to `$F`, ending with `{"status": "done"}` or `{"exit": CODE}`.

Pick a short key that names the work (`score-violence-v5`); runs of one family that
share a key stem (`score-…`) teach the estimator their usual duration.

## Wait without polling

- **Claude Code:** run `ax job wait KEY` as a background command
  (`run_in_background`). It costs nothing while it waits, and its exit wakes you. Do not
  loop on `sleep` or `ax job show`.
- **Codex:** for a job under about 20 minutes, run `ax job wait KEY --timeout 1500`; if
  the shell hands back a session, wait on it with long pauses rather than re-running
  status commands. For anything longer, register with `--wake codex`, tell the user,
  and end your turn: the thread is resumed with a note when the job ends.
- **Overnight or unattended:** add `--wake auto` to `run`, `watch` or `new`; it resumes
  the session that registered the job once it ends.

`ax job wait` exit codes: 0 done, 1 failed, 2 stopped or ended, 3 stalled (with
`--until stalled`), 4 the source check kept failing (credentials, a wrong name),
124 timed out, 69 no such job. On 1 or 4, read `ax job show KEY` before acting.

## Report

- `ax job show KEY` prints status, progress, the estimate ("~12 min left (8–20 min)")
  and recent events; `ax job ls` lists active jobs.
- For the user's phone: `--share cloudflare --notify` on `run`, `watch` or `new` (or
  `ax job follow KEY --share cloudflare --notify --detach`) starts a dashboard and ntfy
  messages. The link carries an access token: give it to the user in your reply only,
  never in commits, docs or other messages, and only share publicly when asked.
- Seamless jobs have their own dashboard; link to it rather than sharing an ax page.

## Rules

- Never stop, forget or re-register a job you did not start without asking.
- A paused Runwatch run ends its ax job as failed: repair it, `runwatch resume`, then
  watch it again under a new key.
- AWS checks use the calling shell's credentials; a check error is not a failed job.

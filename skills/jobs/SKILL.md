---
name: jobs
description: Register, watch, wait on and report long-running work with `ax job` instead of sleep loops, bare background commands or repeated status checks. Use it by default, before you launch, for any command that may take over a minute, any Bash call you would give run_in_background, any loop over a remote API, any notebook execution (nbconvert --execute, Runwatch), any CI or deploy you wait on, and any SageMaker, Seamless or Tools MCP job you start or inherit; also when you need to wait for something to finish or the user wants progress on their phone.
---

# Jobs

`ax job` keeps long work visible without spending tokens: it records progress,
estimates the finish with an 80% interval, ends waits on failure, and can wake your
session when the job ends. Every command takes `--json`.

**It is the default for long or background work.** Don't guess whether a command is
long enough to deserve it: anything you would run in the background, loop over a
remote API, execute as a notebook or wait on remotely goes through `ax job`. A
background Bash call that bypasses it is paused by the guard; rerun it with
`AX_INTENT="<why>"` in front only for work that is not a job, such as a dev server.

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

**Say how long you expect it to take** with `--expect` (`--expect 25m`) on `run`,
`watch` or `new`; a rough guess is fine. A job expected to take over 10 minutes gets a
Haiku look every 5 minutes asking two questions: is it working, and is it working at
the pace it was expected to take? Each look leaves a one-sentence summary (`ax job show
KEY`, the dashboard and the app show the latest). When the job isn't working, the
problem is recorded and `ax job wait` ends with exit 5, which wakes you. Being behind
is not a problem by itself, since your estimate was a guess: you are warned once, with
exit 6, only when the log shows something holding it back (rate limits, a growing
backoff, items getting several times slower) or the job runs more than 20% past what
you expected. ax never stops a job: on 5 or 6 it is still running, and the message
says how to keep waiting or stop it yourself.

**Always describe the job** with `--label`: what it does and what you will do next
when it succeeds or fails ("Extract candidate text and embeddings; then build the
annotation pilot. On failure, fix and relaunch from the saved scores"). The
dashboard, the notifications and the note that wakes you all carry it. If you forgot,
`ax job describe KEY --label "…"` adds it to a job already running.

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

With `--wake`, the note reaches your conversation even while it is open: a Codex
thread open in the app gets it through `codex queue`; a Claude session that is still
running gets it in a background copy (`claude agents` lists it), and the user gets a
push saying so. If a job fails, Haiku reads the end of its log first and the note
starts with its diagnosis. While it runs, Haiku looks at the log every 30 minutes with
`--wake` (`--check-every 45s`, `10m`, `2h`; a bare number is minutes; 0 turns it
off). Each look leaves a short summary of where the job is, kept even when all is well
and shown by `ax job show`, the job's dashboard and the app; you are woken once per
problem it sees, such as the same error on every item. If no route reaches you, the
user gets a push.

- **When the user names an interval** ("have Haiku check every 10 minutes"): pass
  `--check-every 10m` to `ax job follow`, or run `ax job check KEY --every 10m` right
  after `run`, `new` or `watch` starts it, and to change a running job (`--every 0`
  stops the looks). `ax job check KEY
  --now` has Haiku look right away, and `ax job check KEY` shows the interval and the
  last summary. You may run these alone.

`ax job wait` exit codes: 0 done, 1 failed, 2 stopped or ended, 3 stalled (with
`--until stalled`), 4 the source check kept failing (credentials, a wrong name),
5 Haiku sees it not working, 6 Haiku sees it well behind its expected pace, 124 timed
out, 69 no such job. On 1, 4, 5 or 6, read `ax job show KEY` before acting. On 5 and 6
the job is still running and ax leaves it so: decide whether to wait again (`ax job
wait KEY`; a pace warning comes once) or stop it yourself, as the message says.

## Report

- `ax job show KEY` prints status, progress, the estimate ("~12 min left (8–20 min)")
  and recent events; `ax job ls` lists active jobs.
- For the user's phone: every job's dashboard is also in the ax app, at
  `/jobs/KEY/` and on its card, so when the app is shared (`ax app service --share
  cloudflare --notify`) its one link reaches every job; don't start a tunnel per job
  then. Without it, `--share cloudflare --notify` on `run`, `watch` or `new` (or
  `ax job follow KEY --share cloudflare --notify --detach`) starts a dashboard and ntfy
  messages. A link carries an access token: give it to the user in your reply only,
  never in commits, docs or other messages, and only share publicly when asked.
- Seamless jobs have their own dashboard; link to it rather than sharing an ax page.

## Rules

- Never stop, forget or re-register a job you did not start without asking.
- A paused Runwatch run ends its ax job as failed: repair it, `runwatch resume`, then
  watch it again under a new key.
- AWS checks use the calling shell's credentials; a check error is not a failed job.

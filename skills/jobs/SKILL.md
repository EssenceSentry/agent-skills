---
name: jobs
description: Register, watch, wait on and report long-running work with `ax job` instead of sleep loops, bare background commands or repeated status checks. Use it by default, before you launch, for any command that may take over a minute, any Bash call you would give run_in_background, any loop over a remote API, any notebook execution (nbconvert --execute, Runwatch), any CI or deploy you wait on, and any SageMaker, Seamless or Tools MCP job you start or inherit; also when you need to wait for something to finish or the user wants progress on their phone.
---

# Jobs

`ax job` keeps long work visible without spending tokens. You give each job a key and
a label; ax does the rest. It follows the job, wakes you when it ends, fails or needs
attention, has Haiku check it every 5 minutes once it has run 10, and pushes to the
user's phone what no agent hears. There is nothing else to choose. Every command takes
`--json`.

**It is the default for long or background work.** Don't guess whether a command is
long enough to deserve it: anything you would run in the background, loop over a
remote API, execute as a notebook or wait on remotely goes through `ax job`. A
background Bash call that bypasses it is paused by the guard; rerun it with
`AX_INTENT="<why>"` in front only for work that is not a job, such as a dev server.

## Register the work

Every registration takes two things, both required:

- `--key`: a short name for the work (`score-violence-v5`). Runs of one family that
  share a key stem (`score-…`) teach the estimator their usual duration.
- `--label`: what the job does and what you will do next when it succeeds or fails
  ("Extract candidate text and embeddings; then build the annotation pilot. On failure,
  fix and relaunch from the saved scores"). The note that wakes you carries it.

Then one of:

- **A command you start:** `ax job run --key KEY --label "…" -- CMD ARGS`, keeping any
  wrapper the command needs (`uv run`, `env`, a credentials script). A heredoc works:
  `ax job run --key KEY --label "…" -- python - <<'PY' … PY`. A tqdm bar in the output
  counts as progress, and so do `{"done": 10, "total": 40}` lines the command appends
  to `$AX_JOB_FILE`.
- **Something already running:** `ax job watch KIND REF --key KEY --label "…"`, where
  KIND is `pid`, `sagemaker` (a job name), `seamless`, `runwatch` (a run folder),
  `tools` (a Tools MCP job id) or `file` (a JSON progress file). ax finds the rest
  itself: a SageMaker job's type, the AWS region and profile from your shell, the
  runwatch command.
- **A producer you write:** `F=$(ax job new --key KEY --label "…")`, then append JSON
  lines to `$F`: `{"done": 10, "total": 40}`, `{"stage": "scoring"}`, and at the end
  `{"status": "done"}` or `{"exit": CODE}`.

**Notebooks under Runwatch.** Launch through `ax job run --key KEY --label "…" --
runwatch execute NOTEBOOK …`. ax follows the notebook, not only the process, as one
job for the run's whole life: each pause (a failed cell) wakes you with the cell, its
error and the end of its output. Repair it, `runwatch resume` or `restart`, and wait on
the same key; don't register it again. To look at intermediate results, add `--wake-at
CELL`: a cell number counted from 0 (`--wake-at 12,30`), a cell id, or a section
heading (its last cell). It wakes you with that cell's output while the run goes on;
`ax job wake-at KEY CELL…` changes the checkpoints (`--clear` drops them).

## Check it started before you wait

Many failures land in the first seconds: a typo, a missing file or import, a wrong
profile or job name. Right after launching:

1. Run `ax job wait KEY --timeout 60` in the foreground. Exit 124 means it is still
   running after a minute; any other code means it already ended, so read why.
2. Read what it has done so far: `ax job show KEY`, and for a run job the start of its
   output (`output.log`, beside the events file `ax job show` prints). Confirm it is
   doing the work you meant: the right inputs, a first item done or progress moving,
   no error repeating.
3. Only then wait on it as below.

## Wait without polling

- **Claude Code:** run `ax job wait KEY` as a background command
  (`run_in_background`). It costs nothing while it waits, and its exit wakes you. Do
  not loop on `sleep` or `ax job show`.
- **Codex:** for a job under about 20 minutes, run `ax job wait KEY --timeout 1500`.
  For anything longer, tell the user and end your turn: ax wakes your thread.

Even without a wait, ax wakes the session that registered the job: a Codex thread open
in the app through `codex queue`, an open Claude session through its inbox, a closed
one by resuming it. While your own `ax job wait` runs, or once it has returned what
happened, ax doesn't wake you a second time.

`ax job wait` exit codes: 0 done, 1 failed, 2 stopped or ended, 4 the source check kept
failing (credentials, a wrong name), 5 it is not working (Haiku sees a problem, or a
Runwatch run paused), 6 Haiku sees it well behind a pace it can't recover, 7 a
checkpoint cell succeeded, 124 timed out, 69 no such job. On 5 to 7 the job is still
running and ax leaves it so: the message says what was seen and what to do. After
repairing a paused run or looking at a checkpoint, wait again on the same key. ax never
stops a job; if one must stop, stop it yourself (`kill PID` for a run job; `ax job
show KEY` has its pid).

## What ax does on its own

- A job that fails: Haiku reads the end of its log, and the note that wakes you starts
  with its diagnosis.
- From 10 minutes into a job, Haiku looks every 5 minutes: is it working, and is it
  going at a pace it can sustain? Each look leaves a one-sentence summary (`ax job
  show KEY`, the dashboard, the app). You are woken once per problem it sees, such as
  the same error on every item, and warned once when something holds it back (rate
  limits, a growing backoff). A note about a job that is still running is a warning,
  not a go-ahead: leave what its label says comes next until it ends.
- When no agent can be reached, or none registered the job, the user's phone gets a
  push.
- **When the user names an interval** ("have Haiku check every 10 minutes"): `ax job
  check KEY --every 10m` (`--every 0` stops the looks, `--now` has Haiku look right
  away, and `ax job check KEY` shows the interval and the last summary). You may run
  these alone.

## Report

- `ax job show KEY` prints status, progress, the estimate ("~12 min left (8–20 min)")
  and recent events; `ax job ls` lists active jobs.
- For the user's phone: every job's page is in the ax app, at `/jobs/KEY/` and on its
  card, so when the app is shared (`ax app service --share cloudflare --notify`) its one
  link reaches every job. A link carries an access token: give it to the user in your
  reply only, never in commits, docs or other messages.
- Seamless jobs have their own dashboard; link to it rather than sharing an ax page.

## Rules

- Never stop, forget or re-register a job you did not start without asking.
- A Runwatch run still at "created" with no controller two minutes after it was made
  fails its job: it never started, and the output of the command that launched it says
  why (a taken port, a bad setting).
- AWS checks use the calling shell's credentials; a check error is not a failed job.
- Options from before (`--wake`, `--expect`, `--share`, `--notify`, `--show-log` on
  `run`, `watch` or `new`) are no longer needed: ax accepts them with a note and does
  what they asked for on its own. Don't add them.

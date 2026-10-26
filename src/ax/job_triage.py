"""Cheap model checks on a job: why it failed, and whether a running one looks wrong.

Deciding that a job ended, failed or stalled needs no model and stays in `jobs`. A
model (Haiku, through `claude -p`) reads what rules can't: the end of a failed job's
log, to name the likely cause for the agent that gets woken, and every so often a
running job's log, to spot an error repeating on every item, a retry loop or progress
that means nothing. Both read at most the last lines of output, redacted first.
"""

import json
from dataclasses import dataclass

from ax import jobs
from ax.redact import redact

TAIL_LINES = 120
TAIL_CHARS = 12_000

_DIAGNOSE = """A long-running job that a coding agent started has ended with status "{status}".
{label}
Below is the end of its output. In at most three short lines, say what failed, the most
likely cause, and the first thing to check or fix. Quote the decisive error line. If
the output shows no failure, say so in one line.

{tail}
"""

_CHECK = """A long-running job that a coding agent started is still running.
{label}
{pace}
Below is the end of its output. Answer two questions: is this process working, and is
it working at the pace it was expected to take? Reply in exactly two parts:
STATE: one sentence on where the job is and how fast it is going.
HEALTH: OK if it is working at about the expected pace. Otherwise PROBLEM: and one line
on what is wrong, quoting the log: it is not working (the same error on every item, a
retry loop, a crash being retried, progress that isn't progressing, results that are
clearly empty or wrong), or it is clearly behind its expected pace (on track to take
well over the expected time). Running faster than expected is fine, not a problem, and
so are routine warnings and normal variation.

{tail}
"""


def _pace(job, expected: float | None, now: float) -> str:
    """Elapsed time, progress and the expected duration, for judging pace."""
    elapsed = max(0.0, now - jobs.parse_iso(job.created).timestamp())
    parts = [f"It has run {jobs.duration_text(round(elapsed))}"]
    if job.done is not None and job.total:
        unit = f" {job.unit}" if job.unit else ""
        parts.append(f"{job.done:g} of {job.total:g}{unit} done ({job.done / job.total:.0%})")
    text = ", ".join(parts) + "."
    if expected:
        text = f"It was expected to take about {jobs.duration_text(round(expected))}. {text}"
    return text


@dataclass(frozen=True)
class Look:
    """What a model saw in a running job: where it is, and what looks wrong, if anything."""

    summary: str
    problem: str | None = None


def tail(config, job) -> str:
    """The end of the job's output log, or its latest events when it has no log."""
    log = jobs.events_path(config, job.key).parent / "output.log"
    if log.exists():
        with open(log, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - TAIL_CHARS * 2))
            text = f.read().decode("utf-8", "replace")
        lines = text.splitlines()[-TAIL_LINES:]
    else:
        events = jobs.events(config, job.key, latest=True, limit=40)
        lines = [f"{e['ts']} {e['type']} {json.dumps(e['data'])}" for e in events]
    return redact("\n".join(lines))[-TAIL_CHARS:]


def _label(job) -> str:
    return f"What it does: {job.label}" if job.label else ""


def _model(model):
    if model is not None:
        return model
    from ax import learn

    return learn.claude_model("haiku")


def diagnose(config, job, *, model=None) -> str:
    """Two or three lines on why the job failed, for the woken agent to start from."""
    prompt = _DIAGNOSE.format(status=job.status, label=_label(job), tail=tail(config, job))
    return _model(model)(prompt).strip()


def check(config, job, *, model=None, now: float | None = None) -> Look:
    """Where a running job is, and whether it is working at the pace it was expected
    to take; a problem names what is wrong."""
    import time

    pace = _pace(job, jobs.expected(config, job.key), time.time() if now is None else now)
    prompt = _CHECK.format(label=_label(job), pace=pace, tail=tail(config, job))
    answer = _model(model)(prompt).strip()
    state, _, health = answer.partition("HEALTH:")
    summary = state.split("STATE:", 1)[1] if "STATE:" in state else ""
    summary = " ".join(summary.split()).strip("*_ ")[:600]  # models sometimes add emphasis
    problem = None
    if "PROBLEM:" in answer:
        problem = answer.split("PROBLEM:", 1)[1].strip().splitlines()[0][:600] or None
    return Look(summary, problem)

"""Cheap model checks on a job: why it failed, and whether a running one looks wrong.

Deciding that a job ended, failed or stalled needs no model and stays in `jobs`. A
model (Haiku, through `claude -p`) reads what rules can't: the end of a failed job's
log, to name the likely cause for the agent that gets woken, and every so often a
running job's log, to spot an error repeating on every item, a retry loop or progress
that means nothing. Both read at most the last lines of output, redacted first.
"""

import json
import re
from dataclasses import dataclass

from ax import jobs
from ax.redact import redact

TAIL_LINES = 120
TAIL_CHARS = 12_000
OVERDUE = 1.2  # a job this far past its expected time is behind, whatever the log says

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
HEALTH: one of three answers.
- OK if it is working. Running faster than expected is fine, and so are routine
  warnings and normal variation. Being behind the expected pace is OK too unless the log
  shows why: the expectation was only an estimate.
- SLOW: and one line quoting the log, only if it is working but significant evidence
  shows something pathological holding it back that it will not recover from on its own:
  throttling or rate limits, a backoff that keeps growing, items taking several times
  longer than the first ones, a resource running out. Say how far behind it is.
- PROBLEM: and one line quoting the log, if it is not working: the same error on every
  item, a retry loop, a crash being retried, progress that isn't progressing, or results
  that are clearly empty or wrong.

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
    """What a model saw in a running job: where it is, whether it is working, and
    whether it is keeping its expected pace."""

    summary: str
    problem: str | None = None  # not working
    slow: str | None = None  # working, but held back, or well past its expected time


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
    to take. A problem names what is wrong. Slow needs the model to see something
    pathological in the log, or the job to outlast its expected time by OVERDUE."""
    import time

    now = time.time() if now is None else now
    expected = jobs.expected(config, job.key)
    pace = _pace(job, expected, now)
    prompt = _CHECK.format(label=_label(job), pace=pace, tail=tail(config, job))
    answer = _model(model)(prompt).strip()
    state, _, health = answer.partition("HEALTH:")
    summary = state.split("STATE:", 1)[1] if "STATE:" in state else ""
    summary = " ".join(summary.split()).strip("*_ ")[:600]  # models sometimes add emphasis

    # The verdict leads; models punctuate it variously ("SLOW:", "SLOW -", "**SLOW**:").
    verdict = re.match(r"[\s*_]*(OK|SLOW|PROBLEM)\b[\s*_:\u2013\u2014-]*(.*)", health, re.S)
    word, reason = verdict.groups() if verdict else ("", "")
    reason = (reason.strip().splitlines() or [""])[0][:600] or None
    problem = reason if word == "PROBLEM" else None
    slow = reason if word == "SLOW" else None
    elapsed = now - jobs.parse_iso(job.created).timestamp()
    if not problem and not slow and expected and elapsed > OVERDUE * expected:
        slow = (f"it has run {jobs.duration_text(round(elapsed))}, more than "
                f"{OVERDUE - 1:.0%} over the {jobs.duration_text(round(expected))} it was "
                "expected to take")  # fmt: skip
    return Look(summary, problem, slow)

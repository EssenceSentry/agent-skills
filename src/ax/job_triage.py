"""Cheap model checks on a job: why it failed, and whether a running one looks wrong.

Deciding that a job ended, failed or stalled needs no model and stays in `jobs`. A
model (Haiku, through `claude -p`) reads what rules can't: the end of a failed job's
log, to name the likely cause for the agent that gets woken, and every so often a
running job's log, to spot an error repeating on every item, a retry loop or progress
that means nothing. Both read at most the last lines of output, redacted first.
"""

import json

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
Below is the end of its output. Reply with exactly OK if nothing looks wrong. If
something does (the same error on every item, a retry loop, a crash being retried,
progress that isn't progressing, results that are clearly empty or wrong), reply with
one line that starts with PROBLEM: and says what, quoting the log. Routine warnings
and normal slow progress are OK.

{tail}
"""


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


def check(config, job, *, model=None) -> str | None:
    """What looks wrong with a running job, or None when it looks fine."""
    answer = _model(model)(_CHECK.format(label=_label(job), tail=tail(config, job))).strip()
    if "PROBLEM:" not in answer:
        return None
    return answer.split("PROBLEM:", 1)[1].strip().splitlines()[0] or None

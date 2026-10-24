"""ntfy messages about a job: started, progress, a new stage, stalled, and the end.

Fields go in the query string rather than headers, so titles may use any
characters. On ntfy.sh the topic name is the only password; keep it private.
"""

import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlencode

from ax.jobs import Job, progress_text

_END_TAGS = {
    "done": "white_check_mark",
    "failed": "x",
    "stopped": "octagonal_sign",
    "ended": "grey_question",
}


@dataclass(frozen=True)
class Ntfy:
    server: str
    topic: str
    token: str | None = None

    @property
    def url(self) -> str:
        return f"{self.server.rstrip('/')}/{self.topic}"


def settings(config, env=None) -> Ntfy | None:
    """Where to send: AX_NTFY_* variables win over [notify] in config.toml."""
    import os

    env = os.environ if env is None else env
    topic = env.get("AX_NTFY_TOPIC") or config.notify_topic
    if not topic:
        return None
    server = (env.get("AX_NTFY_SERVER") or config.notify_server).rstrip("/")
    return Ntfy(server, topic, env.get("AX_NTFY_TOKEN") or None)


def post(url: str, body: bytes, headers: dict, timeout: float = 10) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status


def send(
    ntfy: Ntfy,
    title: str,
    message: str,
    *,
    tags=(),
    priority: int | None = None,
    click: str | None = None,
    attempts: int = 3,
    sleep=time.sleep,
) -> str | None:
    """Send one message, retrying with backoff. Returns None, or the last error."""
    query = {"title": title}
    if tags:
        query["tags"] = ",".join(tags)
    if priority:
        query["priority"] = str(priority)
    if click:
        query["click"] = click
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if ntfy.token:
        headers["Authorization"] = f"Bearer {ntfy.token}"
    error = None
    for attempt in range(attempts):
        try:
            post(f"{ntfy.url}?{urlencode(query)}", message.encode(), headers)
            return None
        except Exception as exc:  # network, HTTP and URL errors all just mean "not sent"
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts - 1:
                sleep(2**attempt)
    return error


def _summary(job: Job) -> list[str]:
    lines = []
    if job.done is not None or job.total is not None:
        lines.append(progress_text(job))
    if job.stage:
        lines.append(f"stage: {job.stage}")
    return lines


def _message(title: str, lines: list[str], *, tags, priority=None, click=None) -> dict:
    return {
        "title": title,
        "message": "\n".join(line for line in lines if line) or title,
        "tags": tags,
        "priority": priority,
        "click": click,
    }


def started(job: Job, link: str | None = None) -> dict:
    what = job.label or (f"{job.kind} {job.ref}" if job.ref else job.kind)
    return _message(
        f"{job.key} started", [what, *_summary(job)], tags=("arrow_forward",), click=link
    )


def progress(job: Job, link: str | None = None) -> dict:
    if job.total and job.done is not None:
        title = f"{job.key}: {100 * job.done / job.total:.0f}%"
    else:
        title = f"{job.key}: {progress_text(job)}"
    return _message(title, _summary(job), tags=("hourglass_flowing_sand",), click=link)


def stage(job: Job, link: str | None = None) -> dict:
    return _message(f"{job.key}: {job.stage}", _summary(job), tags=("arrow_right",), click=link)


def stalled(job: Job, seconds: float, link: str | None = None) -> dict:
    lines = [f"No change for {seconds / 60:.0f} min.", *_summary(job), job.check_error or ""]
    return _message(f"{job.key} stalled", lines, tags=("warning",), priority=4, click=link)


def finished(job: Job, link: str | None = None) -> dict:
    priority = 4 if job.status in ("failed", "ended") else 3
    lines = [job.message or "", *_summary(job)]
    tags = (_END_TAGS.get(job.status, "grey_question"),)
    return _message(f"{job.key} {job.status}", lines, tags=tags, priority=priority, click=link)


def link_changed(job: Job, link: str) -> dict:
    return _message(
        f"{job.key}: new dashboard link", ["The Cloudflare link was replaced."],
        tags=("link",), click=link,
    )  # fmt: skip

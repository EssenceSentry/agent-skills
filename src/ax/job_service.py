"""The background pass launchd runs every minute (`ax job poll --background`).

- Jobs nobody follows are refreshed, so their events, stalls and estimates keep up.
- A followed job is left to its follower.
- A follower that died (a crash, a reboot) is restarted from the options in its
  follower.json, at most three times per job, so its end message and wake-up still
  happen. One whose job ended more than a day ago is only cleaned up.
- AWS sources are checked only for jobs registered with a named profile: credentials
  an agent exported in its shell are invisible to launchd, and checking with the
  wrong ones would just record errors.
"""

import json
from dataclasses import fields
from datetime import UTC, datetime, timedelta

from ax import job_follow, jobs

MAX_REVIVALS = 3
REVIVE_WITHIN = timedelta(days=1)
_AWS = {"sagemaker", "seamless"}


def _follower(config, key: str) -> dict | None:
    try:
        info = json.loads(job_follow.follower_path(config, key).read_text())
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def _options(info: dict) -> job_follow.FollowOptions:
    known = {f.name for f in fields(job_follow.FollowOptions)}
    saved = {k: v for k, v in (info.get("options") or {}).items() if k in known}
    return job_follow.FollowOptions(**{**saved, "resumed": True})


def _revive(config, job, info, now, start, found) -> None:
    path = job_follow.follower_path(config, job.key)
    if job.terminal and job.finished and now - jobs.parse_iso(job.finished) > REVIVE_WITHIN:
        path.unlink(missing_ok=True)
        return
    revivals = sum(
        e["type"] == "follower_revived"
        for e in jobs.events(config, job.key, limit=1000, latest=True)
    )
    if revivals >= MAX_REVIVALS:
        found["gave_up"].append(job.key)
        return
    path.unlink(missing_ok=True)
    jobs.record_event(config, job.key, "follower_revived", {"previous_pid": info.get("pid")})
    try:
        start(config, job.key, job_follow.options_args(_options(info)))
    except RuntimeError as exc:
        jobs.record_event(config, job.key, "follower_revive_failed", {"error": str(exc)})
        return
    found["revived"].append(job.key)


def tick(config, *, now: datetime | None = None, start=job_follow.start_detached) -> dict:
    """One background pass; returns which jobs it refreshed, left alone or revived."""
    now = now or datetime.now(UTC)
    found = {key: [] for key in ("refreshed", "followed", "unchecked", "revived", "gave_up")}
    for job in jobs.list_jobs(config, include_finished=True, refresh_active=False):
        info = _follower(config, job.key)
        if info is not None:
            if job_follow.running(config, job.key):
                found["followed"].append(job.key)
            else:
                _revive(config, job, info, now, start, found)
            continue
        if job.terminal:
            continue
        check = job.kind not in _AWS or bool(job.spec.get("profile"))
        jobs.refresh(config, job.key, now=now, check=check)
        found["refreshed" if check else "unchecked"].append(job.key)
    return found

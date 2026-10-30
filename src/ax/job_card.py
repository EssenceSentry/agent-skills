"""The card a chat shows for a job its session is waiting on.

Only what is still going: the job's stage and progress, Haiku's last look, and for a
Runwatch notebook its current cell, how many cells are done, and what it started that is
still running, such as a SageMaker job. A job that ended is left to the note that wakes
its agent, unless that note never arrived: then its card stays, with a warning.
"""

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from ax import job_eta, job_sources, jobs

NOTEBOOK_TTL = 10.0  # seconds a notebook's state is reused; it costs a runwatch call
_SESSION_KEY = {"claude": "claude_session", "codex": "codex_thread"}
_UNHEARD_FOR = timedelta(hours=24)  # how long a failure nobody heard of keeps its card
_notebooks: dict[str, tuple[float, dict | None]] = {}


def clear_cache() -> None:
    _notebooks.clear()


def card(config, job: jobs.Job, *, clock=time.monotonic) -> dict:
    eta = None if job.terminal else job_eta.estimate(config, job)
    look = jobs.latest_look(config, job.key)
    percent = round(100 * job.done / job.total) if job.total and job.done is not None else None
    return {
        "key": job.key,
        "label": job.label or (f"{job.kind} {job.ref}" if job.ref else job.kind),
        "kind": job.kind,
        "status": job.status,
        "stage": job.stage,
        "message": job.message,
        "progress": {
            "done": job.done,
            "total": job.total,
            "unit": job.unit,
            "percent": percent,
            "text": jobs.progress_text(job),
        },  # fmt: skip
        "eta": eta["text"] if eta else None,
        "look": {"summary": look["summary"], "at": look["at"]} if look else None,
        "notebook": None if job.terminal else notebook(job, clock=clock),
        "attention": _unheard(config, job),
        "page": f"/jobs/{quote(job.key)}/",
        "updated": job.updated,
    }


def session_cards(config, provider: str, session_id: str) -> list[dict]:
    """The cards of the jobs a session registered that are still going, newest first."""
    field = _SESSION_KEY.get(provider)
    if field is None:
        raise ValueError(f"unknown provider {provider!r}")
    found = [
        job
        for job in jobs.list_jobs(config, include_finished=True, refresh_active=False)
        if job.agent.get(field) == session_id
    ]
    return [card(config, job) for job in found if not job.terminal or _unheard(config, job)]


def counts(config) -> dict[tuple[str, str], int]:
    """How many cards each session has, from one read of the jobs."""
    found: dict[tuple[str, str], int] = {}
    for job in jobs.list_jobs(config, include_finished=True, refresh_active=False):
        if job.terminal and not _unheard(config, job):
            continue
        for provider, field in _SESSION_KEY.items():
            if job.agent.get(field):
                key = (provider, job.agent[field])
                found[key] = found.get(key, 0) + 1
    return found


def _unheard(config, job: jobs.Job) -> str | None:
    """Why a job that ended still needs a card: its agent was never told."""
    if not job.terminal or job.status == "done" or not job.finished:
        return None
    if datetime.now(UTC) - jobs.parse_iso(job.finished) > _UNHEARD_FOR:
        return None
    failed = jobs.latest_event(config, job.key, "wake_failed", full=True)
    woke = jobs.latest_event(config, job.key, "woke", full=True)
    if failed is None or (woke and woke["seq"] > failed["seq"]):
        return None
    return f"ax couldn't reach the agent to tell it: {failed['data'].get('error', '')}".strip()


def notebook(job: jobs.Job, *, clock=time.monotonic) -> dict | None:
    """A Runwatch run's notebook and current cell, its cells done, and what it started
    that still runs."""
    rw = job_sources.runwatch_spec(job)
    if not rw or not rw.get("binary") or not rw.get("run"):
        return None
    now = clock()
    cached = _notebooks.get(rw["run"])
    if cached and now - cached[0] < NOTEBOOK_TTL:
        return cached[1]
    try:
        context = job_sources._runwatch_json(rw, "context")
    except job_sources.CheckError:
        view = None
    else:
        view = _view(context)
    _notebooks[rw["run"]] = (now, view)
    return view


def _view(context: dict) -> dict:
    run, cells = context.get("run") or {}, context.get("cells") or []
    current = run.get("current_cell_index")
    at = next((c for c in cells if c.get("cell_index") == current), None)
    counted = [c for c in cells if c.get("status") != "skipped"]
    return {
        "path": context.get("source_path"),  # the notebook it runs, which a card can open
        "cell": {
            "index": current,
            "label": job_sources.section_label(at.get("label")) if at else None,
        }
        if current is not None
        else None,
        "cells": {
            "done": sum(c.get("status") == "succeeded" for c in counted),
            "total": len(counted),
        },
        "resources": [
            {
                "label": r.get("display_label"),
                "kind": f"{r.get('provider')} {r.get('resource_type')}".strip(),
                "status": r.get("status"),
            }
            for r in context.get("resources") or []
            if not r.get("terminal")
        ],  # fmt: skip
    }

"""Long jobs any agent can register, read and wait on, without importing ax.

A job is a key with a status, a stage and progress. Producers feed it in two ways:
- by appending JSON lines to the job's events file (the file protocol), from any
  language or shell, with nothing to install in the job's own environment;
- through a source that ax checks itself (a file, a process, a SageMaker or
  Seamless job), in `ax.job_sources`.

State lives in `jobs.db`, apart from `ax.db`, which a parser change rebuilds.
"""

import json
import os
import re
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ax.config import Config
from ax.sources.common import project_name

STATUSES = ("running", "done", "failed", "stopped", "ended")
TERMINAL = frozenset({"done", "failed", "stopped", "ended"})
# `ax job wait` exit codes; 69 (no such job) matches `ax usage guard`'s "unknown".
WAIT_CODES = {"done": 0, "failed": 1, "stopped": 2, "ended": 2, "stalled": 3, "timeout": 124}
SOURCE_KINDS = ("file", "pid", "sagemaker", "seamless")

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_STATUS_WORDS = {
    "done": "done", "completed": "done", "complete": "done", "succeeded": "done",
    "success": "done", "ok": "done",
    "failed": "failed", "failure": "failed", "error": "failed",
    "stopped": "stopped", "cancelled": "stopped", "canceled": "stopped",
    "running": "running", "in_progress": "running", "inprogress": "running",
}  # fmt: skip
_AGENT_ENV = {"claude_session": "CLAUDE_CODE_SESSION_ID", "codex_thread": "CODEX_THREAD_ID"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    ref TEXT,
    label TEXT,
    spec TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    stage TEXT,
    done REAL,
    total REAL,
    unit TEXT,
    message TEXT,
    cwd TEXT,
    project TEXT,
    agent TEXT NOT NULL DEFAULT '{}',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    changed TEXT NOT NULL,
    checked TEXT,
    finished TEXT,
    check_error TEXT,
    offset INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_key ON events(key, seq);
"""


@dataclass
class Job:
    key: str
    kind: str
    ref: str | None
    label: str | None
    status: str
    stage: str | None
    done: float | None
    total: float | None
    unit: str | None
    message: str | None
    cwd: str | None
    project: str | None
    created: str
    updated: str
    changed: str
    checked: str | None
    finished: str | None
    check_error: str | None
    offset: int = 0
    spec: dict = field(default_factory=dict)
    agent: dict = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    def to_dict(self) -> dict:
        data = asdict(self)
        del data["offset"]
        return data


@dataclass
class Update:
    """What one events-file line or one source check says about a job."""

    status: str | None = None
    stage: str | None = None
    done: float | None = None
    total: float | None = None
    unit: str | None = None
    message: str | None = None
    events: list[tuple[str, dict]] = field(default_factory=list)


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def normalize_status(value) -> str | None:
    if not isinstance(value, str):
        return None
    return _STATUS_WORDS.get(value.strip().lower().replace(" ", "_").replace("-", "_"))


def number(value) -> float | None:
    """A count from a producer: finite, not negative, and not a boolean."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 and value == value and value != float("inf") else None


def jobs_dir(config: Config) -> Path:
    return config.data / "jobs"


def events_path(config: Config, key: str) -> Path:
    return jobs_dir(config) / check_key(key) / "events.jsonl"


def check_key(key: str) -> str:
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError(
            f"job key {key!r} must start with a letter or digit and use only letters, "
            "digits, '.', '_' or '-' (at most 100 characters)"
        )
    return key


@contextmanager
def connect(config: Config):
    config.data.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.data / "jobs.db", timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(_SCHEMA)
        yield db
    finally:
        db.close()


@contextmanager
def _transaction(db):
    # IMMEDIATE takes the write lock up front, so two refreshes never apply one line twice.
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


def _row_to_job(row) -> Job:
    data = dict(row)
    data["spec"] = json.loads(data["spec"] or "{}")
    data["agent"] = json.loads(data["agent"] or "{}")
    return Job(**data)


def _load(db, key: str) -> Job | None:
    row = db.execute("SELECT * FROM jobs WHERE key = ?", (key,)).fetchone()
    return _row_to_job(row) if row else None


def _save(db, job: Job) -> None:
    data = asdict(job)
    data["spec"] = json.dumps(job.spec, sort_keys=True)
    data["agent"] = json.dumps(job.agent, sort_keys=True)
    columns = ", ".join(data)
    marks = ", ".join(f":{c}" for c in data)
    db.execute(f"INSERT OR REPLACE INTO jobs ({columns}) VALUES ({marks})", data)


def _event(db, key: str, ts: str, type_: str, data: dict) -> None:
    db.execute(
        "INSERT INTO events (key, ts, type, data) VALUES (?, ?, ?, ?)",
        (key, ts, type_, json.dumps(data, sort_keys=True, default=str)),
    )


def _agent(env) -> dict:
    return {name: env[var] for name, var in _AGENT_ENV.items() if env.get(var)}


def _register(config, key, kind, ref, *, label, spec, cwd, env, total=None, unit=None) -> Job:
    check_key(key)
    env = os.environ if env is None else env
    with connect(config) as db, _transaction(db):
        existing = _load(db, key)
        if existing:
            if existing.kind == kind and existing.ref == ref:
                return existing
            raise ValueError(
                f"job {key!r} already exists as a {existing.kind} job"
                + (f" for {existing.ref}" if existing.ref else "")
                + "; pick another --key or `ax job forget` it first"
            )
        ts = now_iso()
        cwd = cwd or os.getcwd()
        job = Job(
            key=key, kind=kind, ref=ref, label=label, status="running", stage=None,
            done=None, total=total, unit=unit, message=None, cwd=cwd,
            project=project_name(cwd), created=ts, updated=ts, changed=ts, checked=None,
            finished=None, check_error=None, spec=spec or {}, agent=_agent(env),
        )  # fmt: skip
        folder = jobs_dir(config) / key
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "events.jsonl").touch()
        _save(db, job)
        _event(db, key, ts, "created", {"kind": kind, "ref": ref, "label": label})
        return job


def new(config, key, *, total=None, unit=None, label=None, cwd=None, env=None) -> Job:
    """Register a job fed only through its events file."""
    return _register(
        config, key, "events", None, label=label, spec={}, cwd=cwd, env=env,
        total=number(total), unit=unit,
    )  # fmt: skip


def watch(config, kind, ref, *, key=None, label=None, options=None, cwd=None, env=None) -> Job:
    """Register a job that a source checks, then check it once."""
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source {kind!r}; choose one of {', '.join(SOURCE_KINDS)}")
    existing = get(config, check_key(key)) if key else None
    if existing and existing.kind != kind:
        raise ValueError(f"job {key!r} already exists as a {existing.kind} job")
    from ax import job_sources

    ref, spec = job_sources.prepare(kind, str(ref), dict(options or {}), cwd or os.getcwd())
    key = key or job_sources.default_key(kind, ref)
    _register(config, key, kind, ref, label=label, spec=spec, cwd=cwd, env=env)
    return refresh(config, key, force=True)


def get(config, key) -> Job | None:
    with connect(config) as db:
        return _load(db, key)


def events(config, key, *, after: int = 0, limit: int = 200, latest: bool = False) -> list[dict]:
    """A job's events in order: the first `limit` after `after`, or the `latest` ones."""
    order = "DESC" if latest else "ASC"
    with connect(config) as db:
        rows = db.execute(
            "SELECT seq, ts, type, data FROM events WHERE key = ? AND seq > ? "
            f"ORDER BY seq {order} LIMIT ?",
            (key, after, limit),
        ).fetchall()
    rows = rows[::-1] if latest else rows
    return [{**dict(r), "data": json.loads(r["data"])} for r in rows]


def forget(config, key) -> bool:
    check_key(key)
    with connect(config) as db, _transaction(db):
        found = db.execute("DELETE FROM jobs WHERE key = ?", (key,)).rowcount
        db.execute("DELETE FROM events WHERE key = ?", (key,))
    folder = jobs_dir(config) / key
    if folder.is_dir():
        shutil.rmtree(folder)
    return bool(found)


def parse_line(raw: dict) -> Update:
    """Read one events-file object. Unknown keys become an event of their own."""
    update = Update()
    update.done = number(raw.get("done"))
    update.total = number(raw.get("total"))
    if isinstance(raw.get("unit"), str):
        update.unit = raw["unit"]
    if isinstance(raw.get("stage"), str):
        update.stage = raw["stage"]
    if isinstance(raw.get("message"), str):
        update.message = raw["message"]
    if "exit" in raw:
        code = raw["exit"]
        update.status = "done" if code == 0 else "failed"
        if code != 0 and not update.message:
            update.message = f"exited with code {code}"
    elif "status" in raw:
        update.status = normalize_status(raw["status"])
        if update.status is None:
            update.events.append(("bad_line", {"reason": "unknown status", "line": raw}))
    known = {"done", "total", "unit", "stage", "message", "exit", "status", "ts"}
    extra = {k: v for k, v in raw.items() if k not in known}
    if extra:
        update.events.append((str(extra.pop("event", "note")), extra))
    return update


def read_lines(path: Path, offset: int) -> tuple[list[Update], int]:
    """Complete lines after `offset`; a line still missing its newline waits."""
    if not path.exists():
        return [], offset
    with path.open("rb") as f:
        f.seek(offset)
        chunk = f.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset
    updates = []
    for line in chunk[: end + 1].splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            raw = None
        if isinstance(raw, dict):
            updates.append(parse_line(raw))
        else:
            text = line.decode("utf-8", "replace")[:200]
            updates.append(
                Update(events=[("bad_line", {"reason": "not a JSON object", "line": text})])
            )
    return updates, offset + end + 1


def apply(db, job: Job, update: Update, ts: str) -> None:
    """Fold one update into the job and record what changed. Ended jobs stay ended."""
    for type_, data in update.events:
        _event(db, job.key, ts, type_, data)
    if job.terminal:
        return
    changed = False
    if update.unit and update.unit != job.unit:
        job.unit = update.unit
    if update.total is not None and update.total != job.total:
        job.total, changed = update.total, True
    if update.done is not None and update.done != job.done:
        job.done, changed = update.done, True
    if changed:
        _event(db, job.key, ts, "progress", {"done": job.done, "total": job.total})
    if update.stage and update.stage != job.stage:
        job.stage, changed = update.stage, True
        _event(db, job.key, ts, "stage", {"stage": job.stage})
    if update.message and update.message != job.message:
        job.message = update.message
        _event(db, job.key, ts, "message", {"message": job.message})
    if update.status and update.status != job.status:
        job.status, changed = update.status, True
        _event(db, job.key, ts, "status", {"status": job.status, "message": job.message})
        if job.terminal:
            job.finished = ts
    if changed:
        job.changed = ts
    job.updated = ts


def refresh(config, key, *, now: datetime | None = None, force: bool = False) -> Job | None:
    """Read new events-file lines and, when due, ask the job's source."""
    now = now or datetime.now(UTC)
    ts = now_iso(now)
    with connect(config) as db, _transaction(db):
        job = _load(db, key)
        if job is None:
            return None
        lines, job.offset = read_lines(events_path(config, key), job.offset)
        for update in lines:
            apply(db, job, update, ts)
        if job.kind in SOURCE_KINDS and not job.terminal and (force or _due(job, now)):
            from ax import job_sources

            job.checked = ts
            try:
                updates = job_sources.check(job, now)
            except job_sources.CheckError as exc:
                if str(exc) != job.check_error:
                    _event(db, key, ts, "check_error", {"error": str(exc)})
                job.check_error = str(exc)
            else:
                job.check_error = None
                for update in updates:
                    apply(db, job, update, ts)
        _save(db, job)
        return job


def _due(job: Job, now: datetime) -> bool:
    from ax import job_sources

    if not job.checked:
        return True
    interval = job_sources.MIN_INTERVAL.get(job.kind, 0)
    return (now - parse_iso(job.checked)).total_seconds() >= interval


def list_jobs(config, *, include_finished: bool = False, refresh_active: bool = True) -> list[Job]:
    with connect(config) as db:
        keys = [
            r["key"]
            for r in db.execute("SELECT key, status FROM jobs")
            if refresh_active and r["status"] not in TERMINAL
        ]
    for key in keys:
        refresh(config, key)
    with connect(config) as db:
        found = [_row_to_job(r) for r in db.execute("SELECT * FROM jobs ORDER BY updated DESC")]
    return [j for j in found if include_finished or not j.terminal]


def poll(config) -> list[Job]:
    """Refresh every active job once; returns the jobs that are still active."""
    return list_jobs(config)


def wait(
    config,
    key,
    *,
    until=None,
    timeout: float | None = None,
    interval: float = 15.0,
    stall_after: float | None = None,
    clock=time.time,
    sleep=time.sleep,
) -> tuple[str, Job]:
    """Block until the job reaches a status in `until`, ends, stalls or times out.

    A job that has ended returns at once even if `until` didn't name its status,
    since nothing else can happen to it. "stalled" in `until` turns on stall
    detection after 30 minutes unless `stall_after` says otherwise.

    Returns (outcome, job), where outcome is a status, "stalled" or "timeout".
    Raises KeyError for an unknown job.
    """
    until = set(until or TERMINAL)
    if "stalled" in until and stall_after is None:
        stall_after = 1800.0
    start = clock()
    while True:
        now = clock()
        job = refresh(config, key, now=datetime.fromtimestamp(now, UTC))
        if job is None:
            raise KeyError(key)
        if job.status in until or job.terminal:
            return job.status, job
        if (
            stall_after is not None
            and job.status == "running"
            and now - parse_iso(job.changed).timestamp() >= stall_after
        ):
            return "stalled", job
        if timeout is not None and now - start >= timeout:
            return "timeout", job
        pause = interval if timeout is None else min(interval, max(0.0, start + timeout - now))
        sleep(max(pause, 0.01))

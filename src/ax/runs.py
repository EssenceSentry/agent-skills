"""One list of delegated and background agent runs from both tools.

Three sources, none of which needs registering in advance:
- delegation helper runs (the delegation skill's worker.py and codex_worker.py),
  found by their run.json through Spotlight or configured folders;
- Claude Code background sessions, from `claude agents --json --all`;
- subagents of either tool, from the archive, running while their transcript grows.
"""

import contextlib
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ax.config import Config
from ax.config import load as load_config
from ax.sources.common import first_line, parse_ts, project_name
from ax.store import Store

__all__ = ["load_config"]  # re-exported so the CLI can be pointed at a test config

_WORKERS = {
    "claude-delegation": ("claude-worker", "claude"),
    "codex-cli-delegation": ("codex-worker", "codex"),
}
_BACKGROUND_STATES = {"working": "running", "blocked": "waiting"}
_ACTIVE = {"starting", "running", "waiting"}
# A helper's heartbeat is 30 s; a silent runner that is gone for this long has died.
LOST_AFTER = 300
# A subagent transcript written this recently means the subagent is still working.
RUNNING_WINDOW = 120


class CannotStop(RuntimeError):
    """Only a running delegation helper run can be asked to stop."""


@dataclass
class Run:
    id: str
    source: str  # claude-worker, codex-worker, claude-background, claude-subagent, codex-subagent
    provider: str
    title: str
    state: str
    project: str
    model: str | None
    started: datetime | None
    updated: datetime | None
    path: Path | None = None  # run directory or transcript
    note: str | None = None  # vault note, for archived subagents
    parent: str | None = None
    session_id: str | None = None

    @property
    def active(self) -> bool:
        return self.state in _ACTIVE


def collect(
    config: Config,
    *,
    background=None,
    include_archive: bool = True,
    since_days: float = 1,
) -> list[Run]:
    """Every known run updated within `since_days`, plus every active one, newest first."""
    now = time.time()
    found = [r for r in (_worker(p, now) for p in run_files(config)) if r]
    found += [_background(row) for row in (background or claude_background)()]
    if include_archive and config.db_path.exists():
        found += _archived_subagents(config, now, since_days)
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    found = [r for r in found if r.active or (r.updated and r.updated >= cutoff)]
    return sorted(found, key=lambda r: r.updated or datetime.min.replace(tzinfo=UTC), reverse=True)


def find(found: list[Run], prefix: str) -> Run | None:
    matches = [r for r in found if r.id.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def stop(run: Run) -> None:
    """Ask a running helper's own runner to stop; it ends its own process group."""
    if run.source not in ("claude-worker", "codex-worker") or not run.active or not run.path:
        raise CannotStop(f"{run.id} is a {run.state} {run.source}; only running helper runs stop")
    (run.path / "stop.request").write_text(json.dumps({"requested_at": time.time(), "by": "ax"}))


def run_files(config: Config) -> list[Path]:
    if config.run_roots:
        return [p for root in config.run_roots if root.exists() for p in root.rglob("run.json")]
    try:
        result = subprocess.run(
            ["mdfind", "kMDItemFSName == 'run.json'"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [Path(line) for line in result.stdout.splitlines() if line]


def claude_background() -> list[dict]:
    try:
        result = subprocess.run(
            ["claude", "agents", "--json", "--all"], capture_output=True, text=True, timeout=15
        )
        rows = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _worker(path: Path, now: float) -> Run | None:
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("kind") not in _WORKERS:
        return None
    source, provider = _WORKERS[record["kind"]]
    directory = path.parent
    updated = record.get("updated_at") or record.get("started_at")
    with contextlib.suppress(OSError):  # the file's own time is the latest heartbeat
        updated = max(updated or 0, path.stat().st_mtime)
    state = str(record.get("status") or "unknown")
    silent = now - (updated or 0) > LOST_AFTER
    if state in ("starting", "running") and silent and not _alive(record.get("runner_pid")):
        state = "lost"
    cwd = record.get("cwd")
    return Run(
        id="w" + hashlib.sha1(str(directory).encode()).hexdigest()[:7],
        source=source,
        provider=provider,
        title=_brief_title(directory) or directory.name,
        state=state,
        project=project_name(cwd) if cwd else "unknown",
        model=record.get("model_requested"),
        started=_epoch(record.get("started_at")),
        updated=_epoch(updated),
        path=directory,
        session_id=record.get("session_id"),
    )


def _background(row: dict) -> Run:
    status = str(row.get("status") or "unknown")
    started = parse_ts(row.get("startedAt"))
    session = str(row.get("sessionId") or "")
    return Run(
        id="b" + session[:7],
        source="claude-background",
        provider="claude",
        title=str(row.get("name") or session),
        state=_BACKGROUND_STATES.get(status, status),
        project=project_name(row.get("cwd")),
        model=None,
        started=started,
        updated=started,
        session_id=session,
    )


def _archived_subagents(config: Config, now: float, since_days: float) -> list[Run]:
    since = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()
    with Store(config.db_path) as store:
        rows = store.subagents_since(since)
    found = []
    for row in rows:
        path = Path(row["source_path"]) if row["source_path"] else None
        try:
            mtime = path.stat().st_mtime if path else None
        except OSError:
            mtime = None
        running = mtime is not None and now - mtime < RUNNING_WINDOW
        found.append(
            Run(
                id=row["provider"][:2] + row["session_id"][-6:],
                source=f"{row['provider']}-subagent",
                provider=row["provider"],
                title=row["title"] or row["session_id"],
                state="running" if running else "done",
                project=row["project"] or "unknown",
                model=row["model"],
                started=parse_ts(row["started"]),
                updated=_epoch(mtime) if running else parse_ts(row["ended"]),
                path=path,
                note=str(config.vault / row["note_path"]) if row["note_path"] else None,
                parent=row["parent_key"],
                session_id=row["session_id"],
            )
        )
    return found


def _brief_title(directory: Path) -> str:
    try:
        text = (directory / "brief.md").read_text(errors="replace")
    except OSError:
        return ""
    return first_line(text.lstrip("# "), 80).lstrip("# ")


def _alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _epoch(value) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int | float) and value else None

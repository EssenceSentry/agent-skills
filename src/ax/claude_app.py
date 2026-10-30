"""The Claude desktop app's list of Code sessions, which a Claude session joins when ax hands
it back, so the app shows it and continues it, the Artifact tool and all.

The app keeps one record per session, `local_<id>.json`, in a folder per account, and the
record points at the Claude Code transcript by `cliSessionId`. The format is the app's own:
ax writes only the fields of the app's smallest records, using this session's confirmed
model, effort, mode and connector configuration, and never changes a record the app wrote.
The app reads the records when it starts, then fills in the rest itself.
"""

import json
import os
import tempfile
import time
import uuid
from pathlib import Path


def _folder(config) -> Path | None:
    """The account in use: the folder holding the session the app wrote last."""
    records = list(Path(config.claude_app_sessions).glob("*/*/local_*.json"))
    if not records:
        return None
    return max(records, key=lambda p: p.stat().st_mtime).parent


def _read(path: Path) -> dict:
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def find(config, sid: str) -> str | None:
    """The app's id for a Claude session it lists, by its Claude Code id."""
    folder = _folder(config)
    if folder is None:
        return None
    return next((p.stem for p in folder.glob("local_*.json")
                 if _read(p).get("cliSessionId") == sid), None)  # fmt: skip


def register(
    config,
    sid: str,
    *,
    cwd: str,
    title: str,
    now: int | None = None,
    settings: dict | None = None,
    connectors: list | None = None,
) -> str | None:
    """The app's id for a Claude session, added to its list if it isn't there yet; None
    when the app or its sessions aren't on this Mac."""
    folder = _folder(config)
    if folder is None:
        return None
    known = find(config, sid)
    if known:
        return known
    actual = settings or {}
    at = now if now is not None else int(time.time() * 1000)
    local = f"local_{uuid.uuid4()}"
    record = {
        "sessionId": local, "cliSessionId": sid, "cwd": cwd, "originCwd": cwd,
        "lastFocusedAt": at, "createdAt": at, "lastActivityAt": at,
        "model": actual.get("model"), "effort": actual.get("effort"), "isArchived": False,
        "title": title, "titleSource": "user",
        "permissionMode": ("plan" if actual.get("plan") else "auto" if actual.get("auto")
                           else "default"),
        "remoteMcpServersConfig": connectors or [],
        "completedTurns": 1, "alwaysAllowedReasons": [], "sessionPermissionUpdates": [],
        "classifierSummaryEnabled": True, "spawnSeed": {},
    }  # fmt: skip
    # Whole or not at all, and as private as the app's own records.
    handle, temporary = tempfile.mkstemp(dir=folder, prefix=".ax-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as out:
            json.dump(record, out)
        os.chmod(temporary, 0o600)
        os.replace(temporary, folder / f"{local}.json")
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return local

"""Limits the main agent sets for its subagents and workers.

A limit is a pattern over what a command runs, and why. ax-guard stops a subagent or
worker whose command matches it; the main agent that set it is never bound by it. A
limit belongs to one conversation (Claude's subagents share their parent's session id)
or applies to every subagent and worker, which is how Codex's subagents and any
`codex exec` worker are reached. Agents may add and remove limits; nothing here is
locked away from them.
"""

import json
import re
from datetime import date

from ax import guard


def _path(config):
    return guard.policy_path(config.data)


def _load(config) -> dict:
    try:
        found = json.loads(_path(config).read_text())
    except (OSError, ValueError):
        return {"last": 0, "limits": []}
    return found if isinstance(found, dict) else {"last": 0, "limits": []}


def _save(config, data: dict) -> None:
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(path)


def add(config, pattern: str, why: str, *, session: str | None = None) -> dict:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"the pattern is not a valid regular expression: {exc}") from None
    if not why.strip():
        raise ValueError("a limit needs its reason")
    data = _load(config)
    data["last"] = int(data.get("last") or 0) + 1  # ids are never reused
    limit = {"id": f"L{data['last']}", "pattern": pattern, "why": why.strip(),
             "session": session, "added": date.today().isoformat()}  # fmt: skip
    data.setdefault("limits", []).append(limit)
    _save(config, data)
    return limit


def listing(config, *, session: str | None = None) -> list[dict]:
    """Every limit; with `session`, the ones that reach that conversation's subagents."""
    limits = [x for x in _load(config).get("limits", []) if isinstance(x, dict)]
    if session is None:
        return limits
    return [x for x in limits if x.get("session") in (None, session)]


def remove(config, limit_id: str) -> None:
    data = _load(config)
    kept = [x for x in data.get("limits", []) if x.get("id") != limit_id]
    if len(kept) == len(data.get("limits", [])):
        raise ValueError(f"no limit {limit_id}; see `ax policy list`")
    data["limits"] = kept
    _save(config, data)

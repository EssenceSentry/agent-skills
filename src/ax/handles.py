"""Conversation handles: short ids an agent can give and any conversation can recall.

A handle is the last eight characters of a session id, the same short id the end of a
session note's file name shows, written `ax:9fe6d7e6` where it must stand out. Both
tools tell the commands an agent runs which conversation they belong to: Claude Code
through CLAUDE_CODE_SESSION_ID and Codex through CODEX_THREAD_ID. When both are set
(one tool started from inside the other), the conversation whose transcript was
written last is the one running.
"""

import os
import re
import time
from pathlib import Path

from ax.store import Store

PREFIX = "ax:"
_REF = re.compile(r"[0-9a-f][0-9a-f-]{5,35}")
# What counts as one conversation mentioning another: a tagged handle, a recall command,
# or a full session id. A bare eight-character hex word is too often a commit or colour.
_TAGGED = re.compile(r"\bax:([0-9a-f]{8})\b")
_RECALLED = re.compile(r"\bax recall\s+(?:ax:)?([0-9a-f][0-9a-f-]{5,35})\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_ENV = (("codex", "CODEX_THREAD_ID"), ("claude", "CLAUDE_CODE_SESSION_ID"))
_COLUMNS = (
    "key, provider, session_id, kind, parent_key, title, project, started, ended, "
    "note_path, source_path, user_turns"
)


class NotFound(ValueError):
    pass


class Ambiguous(ValueError):
    def __init__(self, ref: str, rows: list):
        self.rows = rows
        names = ", ".join(f"{r['session_id']} ({r['title'] or 'untitled'})" for r in rows[:5])
        super().__init__(f"{ref!r} matches {len(rows)} conversations: {names}")


def handle(session_id: str) -> str:
    return session_id[-8:]


def tag(session_id: str) -> str:
    return PREFIX + handle(session_id)


def _rows(store: Store, where: str, args) -> list[dict]:
    return [
        dict(r) for r in store.db.execute(f"SELECT {_COLUMNS} FROM sessions WHERE {where}", args)
    ]


def lookup(store: Store, ref: str) -> list[dict]:
    """Every archived conversation a reference could mean."""
    ref = ref.strip().removeprefix(PREFIX)
    if ref.startswith(("claude:", "codex:")):
        return _rows(store, "key = ?", (ref,))
    if ref.endswith(".md") or "/" in ref or " " in ref:
        stem = Path(ref).name.removesuffix(".md")
        return _rows(store, "note_path = ? OR note_path LIKE ?", (ref, f"%/{stem}.md"))
    ref = ref.lower()
    if not _REF.fullmatch(ref):
        return []
    exact = _rows(store, "session_id = ?", (ref,))
    return exact or _rows(store, "session_id LIKE ? OR session_id LIKE ?", (f"%{ref}", f"{ref}%"))


def resolve(config, ref: str) -> dict:
    """The one archived conversation a handle, id, id prefix or note name refers to."""
    if not config.db_path.exists():
        raise NotFound("no archive yet; run `ax sync`")
    with Store(config.db_path) as store:
        rows = lookup(store, ref)
    if not rows:
        raise NotFound(f"no archived conversation matches {ref!r}; run `ax sync` if it is new")
    if len(rows) > 1:
        raise Ambiguous(ref, rows)
    return rows[0]


def _transcript(config, provider: str, session_id: str) -> Path | None:
    if provider == "claude":
        found = list((config.claude_home / "projects").glob(f"*/{session_id}.jsonl"))
    else:
        found = list((config.codex_home / "sessions").glob(f"**/*{session_id}.jsonl"))
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def current(config, env=None, *, fresh: float | None = None) -> tuple[str, str] | None:
    """(provider, session id) of the conversation these commands run in, if any.

    A long-running process such as an MCP server keeps the id it started with, which
    goes stale when the user clears the conversation; `fresh` (seconds) then requires
    that conversation's transcript to have been written that recently.
    """
    env = os.environ if env is None else env
    found = [(provider, env[name]) for provider, name in _ENV if env.get(name)]

    def written(pair):
        path = _transcript(config, *pair)
        return path.stat().st_mtime if path else 0.0

    best = max(found, key=written) if len(found) > 1 else (found[0] if found else None)
    if best and fresh is not None and time.time() - written(best) > fresh:
        return None
    return best


def mentions(text: str) -> set[str]:
    """References to other conversations in a piece of text, still to be resolved."""
    return set(_TAGGED.findall(text)) | set(_RECALLED.findall(text)) | set(_UUID.findall(text))

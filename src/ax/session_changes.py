"""What a session changed with its edit tools, and each file as it was before: when the
latest turn began, from the tool's own records, or at the last commit, from git.

Claude Code keeps each file its edit tools touch as it was at the start of every turn
(its rewind checkpoints, in `file-history/<session>/`, named by a hash of the path); a
file first touched in the latest turn has only its first backup, `@v1`, from just before
that edit. Codex records each patch it applies with its diff, so a file is rebuilt by
undoing the turn's diffs from the end. Edits made through shell commands appear in
neither record, so they aren't listed.
"""

import hashlib
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ax import live_sessions
from ax.sources.common import iter_records

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
BASES = ("turn", "commit")
MAX_BYTES = 2_000_000
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class NotFound(live_sessions.NotFound):
    """Nothing to show for that file: not one the session changed, or not rebuildable."""


class CantUndo(ValueError):
    """A diff no longer matches the file it should be undone from."""


@dataclass
class _Read:
    cwd: str | None = None
    start: int = -1  # the record that began the latest turn
    prompt: str | None = None  # its id, for Claude's checkpoint
    edits: list = field(default_factory=list)  # (record, path)
    patches: list = field(default_factory=list)  # (record, path, change), Codex only
    snapshots: dict = field(default_factory=dict)  # message id -> files, Claude only


def _is_prompt(record: dict) -> bool:
    """A message the user typed, not a tool's result coming back."""
    if record.get("type") != "user" or record.get("isMeta") or record.get("isCompactSummary"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _claude(records: list[dict]) -> _Read:
    found = _Read()
    for i, r in enumerate(records):
        found.cwd = r.get("cwd") or found.cwd
        if r.get("type") == "file-history-snapshot":
            found.snapshots[r.get("messageId")] = (r.get("snapshot") or {}).get(
                "trackedFileBackups"
            ) or {}
        elif _is_prompt(r):
            found.start, found.prompt = i, r.get("uuid")
        elif r.get("type") == "assistant":
            for block in (r.get("message") or {}).get("content") or []:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") in EDIT_TOOLS
                ):
                    given = block.get("input") or {}
                    path = given.get("file_path") or given.get("notebook_path")
                    if isinstance(path, str) and path:
                        found.edits.append((i, path))
    return found


def _codex(records: list[dict]) -> _Read:
    found = _Read()
    for i, r in enumerate(records):
        payload = r.get("payload") or {}
        if r.get("type") in ("session_meta", "turn_context") and payload.get("cwd"):
            found.cwd = payload["cwd"]
        if r.get("type") != "event_msg":
            continue
        item = payload.get("item") or {}
        if payload.get("type") == "user_message" or item.get("type") == "UserMessage":
            found.start = i
        elif item.get("type") == "FileChange" and item.get("status") == "completed":
            for path, change in (item.get("changes") or {}).items():
                if isinstance(change, dict):
                    where = change.get("move_path") or path
                    found.edits.append((i, where))
                    found.patches.append((i, where, change))
    return found


def _read(config, provider: str, sid: str) -> _Read:
    if provider not in ("claude", "codex"):
        raise ValueError(f"unknown provider {provider!r}")
    path = live_sessions.transcript_path(config, provider, sid)
    if path is None or not path.exists():
        raise NotFound(f"no transcript for {provider} session {sid}")
    records = list(iter_records(path, Counter()))
    return _claude(records) if provider == "claude" else _codex(records)


def _unique(paths) -> list[str]:
    return list(dict.fromkeys(paths))


def changes(config, provider: str, sid: str) -> dict:
    """The files the session changed with its edit tools: in the latest turn, and in all,
    each once, in the order it first touched them."""
    found = _read(config, provider, sid)
    return {
        "cwd": found.cwd,
        "turn": _unique(p for i, p in found.edits if i > found.start),
        "session": _unique(p for _, p in found.edits),
    }


def _text(data: bytes, path: str) -> str:
    if len(data) > MAX_BYTES:
        raise NotFound(f"{path} is too large to show as text")
    try:
        if b"\x00" in data:
            raise UnicodeDecodeError("utf-8", data, 0, 1, "a NUL byte")
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise NotFound(f"{path} isn't text") from None


def _on_disk(path: str) -> str | None:
    try:
        return _text(Path(path).read_bytes(), path)
    except FileNotFoundError:
        return None


def _at_commit(path: str) -> str | None:
    """The file in the last commit of its repository; None when the commit hasn't it."""
    file = Path(path)
    folder = file.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    run = {"capture_output": True, "timeout": 20}
    top = subprocess.run(
        ["git", "-C", str(folder), "rev-parse", "--show-toplevel"], text=True, **run
    )
    if top.returncode != 0:
        raise NotFound(f"{path} isn't in a git repository")
    real = Path(os.path.realpath(folder)) / file.relative_to(folder)
    relative = real.relative_to(Path(top.stdout.strip()).resolve()).as_posix()
    shown = subprocess.run(["git", "-C", top.stdout.strip(), "show", f"HEAD:{relative}"], **run)
    return _text(shown.stdout, path) if shown.returncode == 0 else None


def _claude_turn(config, sid: str, found: _Read, path: str) -> str | None:
    tracked = found.snapshots.get(found.prompt)
    if tracked is None:
        raise NotFound("Claude kept no checkpoint for this turn")
    history = config.claude_home / "file-history" / sid
    if path in tracked:
        name = (tracked[path] or {}).get("backupFileName")
    else:  # first touched this turn: its first backup, if it existed before the edit
        first = f"{hashlib.sha256(path.encode()).hexdigest()[:16]}@v1"
        name = first if (history / first).exists() else None
    return _text((history / name).read_bytes(), path) if name else None


def _codex_turn(found: _Read, path: str) -> str | None:
    text = _on_disk(path)
    try:
        for i, where, change in reversed(found.patches):
            if i <= found.start or where != path:
                continue
            kind = change.get("type")
            if kind == "add":
                text = None
            elif kind == "delete":
                text = change.get("content") if isinstance(change.get("content"), str) else None
            elif text is None:
                raise CantUndo("the file is gone")
            else:
                text = unapply(text, change.get("unified_diff") or "")
    except CantUndo:
        raise NotFound(f"{path} changed since the turn; it can't be rebuilt as it was") from None
    return text


def before(config, provider: str, sid: str, path: str, *, base: str) -> str | None:
    """One file the session changed, as it was when the latest turn began or at the last
    commit; None when it didn't exist then."""
    if base not in BASES:
        raise ValueError(f"base is one of {', '.join(BASES)}")
    found = _read(config, provider, sid)
    mine = (p for i, p in found.edits if base == "commit" or i > found.start)
    if path not in set(mine):
        raise NotFound(
            f"the session didn't change {path}" + (" this turn" if base == "turn" else "")
        )
    if base == "commit":
        return _at_commit(path)
    return (
        _claude_turn(config, sid, found, path) if provider == "claude" else _codex_turn(found, path)
    )


def _hunks(diff: str) -> list[tuple[int, int, list[tuple[str, str]]]]:
    """Each hunk's new start and length, and its lines as (sign, text with newline)."""
    hunks: list = []
    for line in diff.split("\n"):
        head = _HUNK.match(line)
        if head:
            hunks.append((int(head[1]), int(head[2]) if head[2] is not None else 1, []))
        elif hunks and line[:1] in (" ", "-", "+"):
            hunks[-1][2].append((line[0], line[1:] + "\n"))
        elif hunks and line.startswith("\\") and hunks[-1][2]:  # the last line has no newline
            sign, text = hunks[-1][2][-1]
            hunks[-1][2][-1] = (sign, text.removesuffix("\n"))
    return hunks


def unapply(text: str, diff: str) -> str:
    """The text before a unified diff was applied to it; CantUndo when it doesn't match."""
    lines = text.splitlines(keepends=True)
    for start, length, body in reversed(_hunks(diff)):
        new = [t for s, t in body if s in " +"]
        old = [t for s, t in body if s in " -"]
        expected = start - 1 if length else start
        if new:
            near = sorted(range(len(lines) - len(new) + 1), key=lambda at: abs(at - expected))
            at = next((n for n in near if lines[n : n + len(new)] == new), None)
            if at is None:
                raise CantUndo("a hunk no longer matches")
        else:
            at = min(max(expected, 0), len(lines))
        lines[at : at + len(new)] = old
    return "".join(lines)

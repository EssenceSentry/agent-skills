"""What a session changed with its edit tools, and each file as it was before: when the
latest turn began, from the tool's own records, or at the last commit, from git.

Claude Code keeps each file its edit tools touch as it was at the start of every turn
(its rewind checkpoints, in `file-history/<session>/`, named by a hash of the path); a
file first touched in the latest turn has only its first backup, `@v1`, from just before
that edit. Codex records each patch it applies with its diff, so a file is rebuilt by
undoing the turn's diffs from the end. Edits made through shell commands appear in
neither record, so they aren't listed.
"""

import contextlib
import difflib
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
BASES = ("turn", "session", "commit")
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
    boundary: str = "inferred"


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
    checkpoints = {
        r.get("messageId")
        for r in records
        if r.get("type") == "file-history-snapshot" and isinstance(r.get("messageId"), str)
    }
    lifecycle = bool(checkpoints) or any(
        r.get("type") == "system" and r.get("subtype") in ("stop_hook_summary", "turn_duration")
        for r in records
    )
    found.boundary = "provider" if lifecycle else "inferred"
    active, current_identity = False, None
    for i, r in enumerate(records):
        found.cwd = r.get("cwd") or found.cwd
        if r.get("type") == "file-history-snapshot":
            found.snapshots[r.get("messageId")] = (r.get("snapshot") or {}).get(
                "trackedFileBackups"
            ) or {}
        elif _is_prompt(r):
            # Checkpoint identities and positive lifecycle ends distinguish a new
            # turn from input Claude consumes while the current turn is working.
            identity = r.get("turnId") or r.get("turn_id") or r.get("promptId")
            if (
                not active
                or not identity
                or identity != current_identity
                or r.get("uuid") in checkpoints
            ):
                found.start, found.prompt = i, r.get("uuid")
                found.boundary = (
                    "provider" if identity or r.get("uuid") in checkpoints else "inferred"
                )
            active, current_identity = True, identity
        elif r.get("type") == "system" and r.get("subtype") in (
            "stop_hook_summary",
            "turn_duration",
        ):
            active = False
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
    active = False
    for i, r in enumerate(records):
        payload = r.get("payload") or {}
        if r.get("type") in ("session_meta", "turn_context") and payload.get("cwd"):
            found.cwd = payload["cwd"]
        if r.get("type") != "event_msg":
            continue
        item = payload.get("item") or {}
        if payload.get("type") == "task_started":
            found.start, active = i, True
            found.boundary = "provider"
        elif payload.get("type") in ("task_complete", "turn_aborted"):
            active = False
        elif not active and (
            payload.get("type") == "user_message" or item.get("type") == "UserMessage"
        ):
            found.start = i
        elif item.get("type") == "FileChange" and item.get("status") == "completed":
            for path, change in (item.get("changes") or {}).items():
                if isinstance(change, dict):
                    source = (
                        str(Path(found.cwd or ".") / path) if not Path(path).is_absolute() else path
                    )
                    moved = change.get("move_path")
                    where = (
                        (
                            str(Path(found.cwd or ".") / moved)
                            if not Path(moved).is_absolute()
                            else moved
                        )
                        if moved
                        else source
                    )
                    if moved:
                        found.edits.append((i, source))
                        change = {**change, "_source_path": source, "move_path": where}
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
        "coverage": "Provider edit history only. Shell edits and changes outside this session may be missing."
        + (
            " Turn boundaries are inferred because provider lifecycle records are unavailable."
            if found.boundary == "inferred"
            else ""
        ),
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


def _codex_tree(found: _Read, focus=None):
    """Invert recorded operations in memory, keeping rename pairs inseparable."""
    patches = [(i, path, change) for i, path, change in found.patches if i > found.start]
    paths = _unique(
        p for _, path, change in patches for p in (path, change.get("_source_path", path))
    )
    groups = {path: {path} for path in paths}
    for _, path, change in patches:
        if change.get("move_path"):
            source = change["_source_path"]
            joined = groups[path] | groups[source]
            for member in joined:
                groups[member] = joined
    if focus is not None:
        paths = [path for path in paths if path in groups.get(focus, {focus})]
        patches = [entry for entry in patches if entry[1] in paths]
    texts, errors = {}, {}
    for path in paths:
        try:
            texts[path] = _on_disk(path)
        except (NotFound, OSError) as exc:
            for member in groups[path]:
                errors[member] = str(exc)
    for _, path, change in reversed(patches):
        if path in errors:
            continue
        try:
            text, kind = texts[path], change.get("type")
            if kind == "add":
                if not isinstance(change.get("content"), str) or text != change["content"]:
                    raise CantUndo("the added file has further changes")
                texts[path] = None
            elif kind == "delete":
                if text is not None:
                    raise CantUndo("the deleted file was recreated")
                if not isinstance(change.get("content"), str):
                    raise CantUndo("the provider recorded no deleted-file contents")
                texts[path] = change["content"]
            else:
                if text is None:
                    raise CantUndo("the file is gone")
                patch = change.get("unified_diff")
                if not isinstance(patch, str) or (not patch and not change.get("move_path")):
                    raise CantUndo("the provider recorded no inverse patch")
                prior = unapply(text, patch)
                if change.get("move_path"):
                    source = change["_source_path"]
                    if texts[source] is not None:
                        raise CantUndo("the original rename path is occupied")
                    texts[source], texts[path] = prior, None
                else:
                    texts[path] = prior
        except (CantUndo, OSError) as exc:
            for member in groups[path]:
                errors[member] = str(exc)
    return texts, errors, groups


def _codex_turn(found: _Read, path: str) -> str | None:
    texts, errors, _ = _codex_tree(found, path)
    if path in errors:
        raise NotFound(
            f"{path} changed since the turn; it can't be rebuilt as it was: {errors[path]}"
        )
    return texts[path] if path in texts else _on_disk(path)


def before(config, provider: str, sid: str, path: str, *, base: str) -> str | None:
    """One file the session changed, as it was when the latest turn began or at the last
    commit; None when it didn't exist then."""
    if base not in BASES:
        raise ValueError(f"base is one of {', '.join(BASES)}")
    found = _read(config, provider, sid)
    mine = (p for i, p in found.edits if base != "turn" or i > found.start)
    allowed = set(mine)
    if base == "commit" and path not in allowed and found.cwd:
        with contextlib.suppress(NotFound):
            allowed.update(workspace(found.cwd)["paths"])
    if path not in allowed:
        raise NotFound(
            f"the session didn't change {path}" + (" this turn" if base == "turn" else "")
        )
    if base == "commit":
        return _at_commit(path)
    if base == "session":
        if provider == "codex":
            found.start = -1
            return _codex_turn(found, path)
        history = config.claude_home / "file-history" / sid
        first = history / f"{hashlib.sha256(path.encode()).hexdigest()[:16]}@v1"
        if first.exists():
            return _text(first.read_bytes(), path)
        checkpoint = next(
            (files[path] for files in found.snapshots.values() if path in files), None
        )
        if checkpoint is None:
            raise NotFound("Claude kept no initial checkpoint for this file")
        name = checkpoint.get("backupFileName")
        return _text((history / name).read_bytes(), path) if name else None
    return (
        _claude_turn(config, sid, found, path) if provider == "claude" else _codex_turn(found, path)
    )


def workspace(cwd: str) -> dict:
    """Working tree changes, including staged and untracked paths, without touching the index."""
    run = {"capture_output": True, "timeout": 20, "check": True}
    try:
        root = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"], text=True, **run
        ).stdout.strip()
        committed = (
            subprocess.run(
                ["git", "-C", root, "rev-parse", "--verify", "HEAD"],
                capture_output=True,
                timeout=20,
            ).returncode
            == 0
        )
        names = subprocess.run(
            ["git", "-C", root, "diff", "--no-renames", "--name-only", "-z", "HEAD"]
            if committed
            else ["git", "-C", root, "ls-files", "-z"],
            **run,
        ).stdout
        untracked = subprocess.run(
            ["git", "-C", root, "ls-files", "--others", "--exclude-standard", "-z"], **run
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise NotFound("This folder has no readable Git HEAD for a workspace comparison") from exc
    paths = _unique(str(Path(root) / os.fsdecode(p)) for p in (names + untracked).split(b"\0") if p)
    return {
        "cwd": root,
        "paths": paths,
        "coverage": "All Git workspace changes since HEAD, including unrelated edits and untracked nonignored files.",
    }


def text_diff(before, after, fromfile="", tofile=""):
    """A valid unified diff, including explicit markers for unterminated lines."""
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), fromfile=fromfile, tofile=tofile
        )
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
            matches = [n for n in near if lines[n : n + len(new)] == new]
            if not matches:
                raise CantUndo("a hunk no longer matches")
            if len(matches) > 1:
                raise CantUndo("multiple matching hunks; no unique restore is possible")
            at = matches[0]
        else:
            if lines or expected:
                raise CantUndo("a deletion has no surviving context to locate it safely")
            at = 0
        lines[at : at + len(new)] = old
    return "".join(lines)

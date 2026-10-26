"""Helpers shared by the source parsers."""

import io
import json
import re
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import zstandard


def open_text(path: Path) -> io.TextIOBase:
    """Open a transcript as text, decompressing `.zst` files on the fly."""
    if path.suffix == ".zst":
        stream = zstandard.ZstdDecompressor().stream_reader(path.open("rb"))
        return io.TextIOWrapper(stream, encoding="utf-8", errors="replace")
    return path.open(encoding="utf-8", errors="replace")


def iter_records(path: Path, unknown: Counter, *, numbered: bool = False) -> Iterator:
    """Yield each JSON object in a JSONL file, or with `numbered` (its line, the object);
    count lines that aren't one."""
    with open_text(path) as fh:
        for number, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                unknown["invalid-json"] += 1
                continue
            if isinstance(record, dict):
                yield (number, record) if numbered else record
            else:
                unknown["invalid-json"] += 1


_DATA_URL = re.compile(r"data:(image/[\w.+-]+);base64,(.*)", re.S)


def claude_images(record: dict) -> list[tuple[str, str, str | None]]:
    """Each image in a Claude record, in order: its media type, its base64 data, and the
    tool call it came back from (None for one the user pasted)."""
    content = (record.get("message") or {}).get("content")
    found: list[tuple[str, str, str | None]] = []

    def add(block, owner):
        source = block.get("source")
        if isinstance(source, dict) and source.get("type") == "base64" and source.get("data"):
            found.append((str(source.get("media_type") or "image/png"), source["data"], owner))

    for item in content if isinstance(content, list) else ():
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image":
            add(item, None)
        elif item.get("type") == "tool_result" and isinstance(item.get("content"), list):
            for part in item["content"]:
                if isinstance(part, dict) and part.get("type") == "image":
                    add(part, item.get("tool_use_id"))
    return found


def codex_images(payload: dict) -> list[tuple[str, str, str | None]]:
    """Each image in a Codex response item, in order: its media type, its base64 data, and
    the tool call it came back from (None for one in a message)."""
    kind = payload.get("type")
    if kind == "message":
        parts, owner = payload.get("content"), None
    elif kind in ("function_call_output", "custom_tool_call_output"):
        parts, owner = payload.get("output"), payload.get("call_id")
    else:
        return []
    found = []
    for part in parts if isinstance(parts, list) else ():
        if isinstance(part, dict) and part.get("type") == "input_image":
            data = _DATA_URL.match(str(part.get("image_url") or ""))
            if data:
                found.append((data.group(1), data.group(2), owner))
    return found


def parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def as_text(value) -> str | None:
    """A non-empty string, or None: transcripts sometimes carry objects where text is usual."""
    return value if isinstance(value, str) and value else None


def first_line(text: str, limit: int = 100) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def code(text: str) -> str:
    """Format text as inline code, even when it contains backticks."""
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def relative(path: str, cwd: str | None) -> str:
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1 :]
    return path


def project_name(cwd: str | None, repo_url: str | None = None) -> str:
    """Name a session's project: its git repository, else the repo URL, else the folder."""
    if cwd:
        root = _git_root(Path(cwd))
        if root:
            return root.name
    if repo_url:
        name = repo_url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        return name.removesuffix(".git") or "unknown"
    if cwd:
        return Path(cwd).name or "unknown"
    return "unknown"


def _git_root(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        marker = directory / ".git"
        if marker.is_dir():
            return directory
        if marker.is_file():
            # A worktree: ".git" points into <main repo>/.git/worktrees/<name>.
            text = marker.read_text(errors="replace").strip()
            if text.startswith("gitdir:"):
                gitdir = Path(text.removeprefix("gitdir:").strip())
                if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
                    return gitdir.parent.parent.parent
            return directory
    return None

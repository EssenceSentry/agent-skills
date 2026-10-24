"""Helpers shared by the source parsers."""

import io
import json
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


def iter_records(path: Path, unknown: Counter) -> Iterator[dict]:
    """Yield each JSON object in a JSONL file; count lines that aren't one."""
    with open_text(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                unknown["invalid-json"] += 1
                continue
            if isinstance(record, dict):
                yield record
            else:
                unknown["invalid-json"] += 1


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

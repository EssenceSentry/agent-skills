"""Copy, parse, index and render every new or changed transcript.

Native session stores are only read. Raw files are backed up before anything
else, notes are rebuilt from parsed sessions, and a note is kept even after its
source transcript disappears. A transcript counts as synced only once its note
is written, so any failure is retried on the next run.
"""

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path

import zstandard

from ax import handles
from ax.config import Config
from ax.model import Session
from ax.redact import redact
from ax.render import note_relpath, render
from ax.sources import claude, codex
from ax.store import Store

# Bump when parsing or rendering changes, so the next sync rebuilds every note.
PARSER_VERSION = "7"


class SyncBusy(RuntimeError):
    """Another sync holds the lock."""


@dataclass
class Report:
    discovered: int = 0
    parsed: int = 0
    written: int = 0
    renamed: int = 0
    removed: int = 0
    excluded: int = 0
    not_rendered: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class _Item:
    session: Session
    raw: Path | None = None
    # (path, size, mtime_ns) of the transcript, recorded once its note is written.
    files: list[tuple[Path, int, int]] = field(default_factory=list)
    old_note: str | None = None
    note: str | None = None


@contextmanager
def lock(config: Config):
    """Hold the sync lock, or raise SyncBusy if another sync has it."""
    config.data.mkdir(parents=True, exist_ok=True)
    with (config.data / "ax.lock").open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncBusy("another ax sync is running") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def sync(config: Config, *, progress: Callable[[int, int], None] | None = None) -> Report:
    with lock(config):
        return _sync(config, progress)


def _sync(config: Config, progress) -> Report:
    report = Report()
    titles = codex.read_titles(config.codex_home)
    sources = [("claude", p) for p in claude.discover(config.claude_home)]
    sources += [("codex", p) for p in codex.discover(config.codex_home)]
    report.discovered = len(sources)

    with Store(config.db_path) as store:
        build = _build_key(config)
        rebuild = store.get_meta("parser_version") != build
        stale_titles = _renamed_codex_threads(store, titles)
        items: dict[str, _Item] = {}

        for done, (provider, path) in enumerate(sources, 1):
            if progress:
                progress(done, len(sources))
            try:
                stat = path.stat()
            except OSError as exc:  # compressed or moved since discovery
                report.errors.append(f"{path}: {type(exc).__name__}: {exc}")
                continue
            unchanged = store.file_state(path) == (stat.st_size, stat.st_mtime_ns)
            renamed = provider == "codex" and codex.session_id_from_name(path) in stale_titles
            if unchanged and not renamed and not rebuild:
                continue
            try:
                raw = _backup(config, provider, path, stat.st_size)
                session = _parse(provider, path, titles)
            except Exception as exc:  # one unreadable file must not stop the archive
                report.errors.append(f"{path}: {type(exc).__name__}: {exc}")
                continue
            report.parsed += 1
            previous = items.get(session.key)
            files = previous.files if previous else []
            files.append((path, stat.st_size, stat.st_mtime_ns))
            # A conversation the user moved to another folder has a copy in each; the
            # newest copy holds all of it and says where it lives now.
            newest = max((m for _, _, m in files[:-1]), default=-1)
            if previous and newest > stat.st_mtime_ns:
                previous.files = files
            else:
                items[session.key] = _Item(session, raw, files)

        if rebuild:
            # Sessions whose transcript is gone are rebuilt from their raw backup.
            for row in store.all_sessions():
                if row["key"] not in items:
                    session = _reparse(row, titles, report)
                    if session:
                        report.parsed += 1
                        items[row["key"]] = _Item(session)

        for key, item in list(items.items()):
            try:
                with store.savepoint():
                    _save(config, store, item, report)
            except Exception as exc:
                report.errors.append(f"{key}: {type(exc).__name__}: {exc}")
                del items[key]

        dirty = dict(items)
        for key, item in items.items():
            # Notes that link to this one must be rebuilt when it appears, moves or goes.
            if item.old_note != item.note:
                neighbours = [c["key"] for c in store.children(key)]
                if item.session.parent_key:
                    neighbours.append(item.session.parent_key)
                for other in neighbours:
                    _add_neighbour(store, other, dirty, titles, report)

        for key, item in dirty.items():
            try:
                _write_note(config, store, item.session, report)
            except Exception as exc:
                report.errors.append(f"{key}: {type(exc).__name__}: {exc}")
                if item.old_note != item.note:
                    store.set_note_path(key, item.old_note)  # the old note stays the live one
                continue
            if item.old_note and item.old_note != item.note:
                _remove_note(config.vault / item.old_note, item.session)
                if item.note:
                    report.renamed += 1
                else:
                    report.removed += 1
            for path, size, mtime in item.files:
                store.record_file(path, item.session.provider, size, mtime, key)

        store.set_meta("last_sync", datetime.now(UTC).isoformat(timespec="seconds"))
        store.set_meta("last_sync_errors", str(len(report.errors)))
        if not report.errors:
            store.set_meta("parser_version", build)
    return report


def _parse(provider: str, path: Path, titles: dict[str, str]) -> Session:
    return claude.parse(path) if provider == "claude" else codex.parse(path, titles)


def _reparse(row: dict, titles: dict[str, str], report: Report) -> Session | None:
    """Parse a stored session again from its transcript, or its raw backup when that's gone."""
    for candidate in (row["source_path"], row["raw_path"]):
        path = Path(candidate).expanduser() if candidate else None
        if path and path.exists():
            try:
                return _parse(row["provider"], path, titles)
            except Exception as exc:
                report.errors.append(f"{path}: {type(exc).__name__}: {exc}")
                return None
    return None


def _save(config: Config, store: Store, item: _Item, report: Report) -> None:
    session = item.session
    excluded = bool(session.cwd) and any(fnmatch(session.cwd, p) for p in config.exclude)
    rendered = not excluded and (session.kind != "guardian" or config.render_guardian)
    if excluded:
        report.excluded += 1
    elif not rendered:
        report.not_rendered += 1

    old = store.session(session.key)
    item.old_note = old["note_path"] if old else None
    if rendered:
        item.note = str(note_relpath(session))
        owner = store.note_owner(item.note)
        if owner and owner != session.key:
            item.note = str(note_relpath(session, full_id=True))
    raw = _display(item.raw) if item.raw else (old["raw_path"] if old else None)
    store.save_session(
        session,
        note_path=item.note,
        raw_path=raw,
        excluded=excluded,
        index_messages=rendered,
    )


def _add_neighbour(store: Store, key: str, dirty: dict, titles: dict, report: Report) -> None:
    if key in dirty:
        return
    row = store.session(key)
    if not row or not row["note_path"]:
        return
    session = _reparse(row, titles, report)
    if session:
        dirty[key] = _Item(session, old_note=row["note_path"], note=row["note_path"])


def _write_note(config: Config, store: Store, session: Session, report: Report) -> None:
    row = store.session(session.key)
    if not row or not row["note_path"]:
        return
    parent = store.session(session.parent_key) if session.parent_key else None
    parent_note = Path(parent["note_path"]).stem if parent and parent["note_path"] else None
    kids = store.children(session.key)
    children = [(Path(c["note_path"]).stem, c["title"]) for c in kids if c["note_path"]]
    store.set_mentions(session.key, _mentioned(store, session, {c["key"] for c in kids}))
    builds_on = list(
        {
            r["target_key"]: (Path(r["note_path"]).stem, r["title"])
            for r in store.links_from(session.key)
            if r["note_path"]
        }.values()
    )
    text = render(
        session, parent_note=parent_note, raw_path=row["raw_path"], children=children,
        builds_on=builds_on,
    )  # fmt: skip
    target = config.vault / row["note_path"]
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem[:40]}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, target)
    report.written += 1


def _mentioned(store: Store, session: Session, children: set) -> set:
    """Conversations this one refers to by handle, recall command or full id, other than
    itself and the parent and subagents its note already links."""
    refs = set().union(*(handles.mentions(e.text) for e in session.events if e.text))
    skip = {session.key, session.parent_key, *children}
    found = set()
    for ref in refs:
        rows = handles.lookup(store, ref)
        if len(rows) == 1 and rows[0]["key"] not in skip:
            found.add(rows[0]["key"])
    return found


def _remove_note(path: Path, session: Session) -> None:
    """Delete a note ax generated for this session, never anything else."""
    if path.exists() and f'session_id: "{session.session_id}"' in path.read_text(encoding="utf-8"):
        path.unlink()


def _backup(config: Config, provider: str, path: Path, size: int) -> Path:
    """Copy a transcript into the raw archive, compressed, as of `size` bytes.

    Live sessions keep growing, so only the first `size` bytes are copied; the
    frame records that size, so any zstd tool can restore the file.
    """
    home = config.claude_home if provider == "claude" else config.codex_home
    dest = config.raw_dir / provider / path.relative_to(home)
    if path.suffix != ".zst":
        dest = dest.with_name(dest.name + ".zst")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    with os.fdopen(fd, "wb") as out:
        if path.suffix == ".zst":
            with path.open("rb") as src:
                shutil.copyfileobj(src, out)
        else:
            with path.open("rb") as src:
                writer = zstandard.ZstdCompressor(level=6).stream_writer(
                    out, size=size, closefd=False
                )
                remaining = size
                while remaining > 0:
                    chunk = src.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    writer.write(chunk)
                    remaining -= len(chunk)
                writer.flush(zstandard.FLUSH_FRAME)
    os.replace(tmp, dest)
    meta = path.with_name(path.name.removesuffix(".jsonl") + ".meta.json")
    if meta.exists():
        shutil.copyfile(meta, dest.with_name(meta.name))
    return dest


def _build_key(config: Config) -> str:
    """Changes when the parser or the settings that decide which notes exist change."""
    settings = json.dumps([sorted(config.exclude), config.render_guardian])
    return f"{PARSER_VERSION}:{hashlib.sha1(settings.encode()).hexdigest()[:12]}"


def _renamed_codex_threads(store: Store, titles: dict[str, str]) -> set[str]:
    """Codex threads renamed in the app: only `session_index.jsonl` changes."""
    stored = store.titles("codex")
    return {sid for sid, title in titles.items() if sid in stored and stored[sid] != redact(title)}


def _display(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)

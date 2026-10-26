"""Every live session of Claude Code and Codex: what each is doing, the last thing it
said, the jobs it waits on, and its transcript as it grows.

This is the read-only first stage of the chat view (PLAN.md, component 21). Claude's
interactive sessions, the desktop app's included, come from `claude agents --json`.
Codex threads come from its app-server: the shared daemon when the Codex app runs one,
so states match the app, else a short-lived `codex app-server`, whose threads aren't
loaded; their state is then read from the end of each rollout. Transcripts are parsed with the archive's own
parsers, again only when the file grew, and redacted before they leave ax.
"""

import contextlib
import json
import queue
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from ax import job_card, jobs
from ax.redact import redact
from ax.sources import claude as claude_source
from ax.sources import codex as codex_source
from ax.sources.common import first_line, project_name

# A Codex thread untouched this long, and not open anywhere, isn't live.
RECENT = 24 * 3600.0
# A Codex turn left open in a rollout that hasn't moved this long belongs to a process
# that is gone.
STALE_TURN = 1800.0
TAIL_BYTES = 256 * 1024
TEXT_CHARS = 20_000
OUTPUT_CHARS = 2_000
LISTING_TTL = 4.0
_ORDER = {"waiting": 0, "working": 1, "idle": 2}
_paths: dict[tuple[str, str, str], Path] = {}  # (tool home, provider, session id)
_parsed: dict[str, tuple[tuple[int, int], list]] = {}
_listings: dict[str, tuple[float, dict]] = {}


class NotFound(LookupError):
    """No transcript for that session."""


def clear_cache() -> None:
    _paths.clear()
    _parsed.clear()
    _listings.clear()


def _run(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True).stdout


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds") if ts else None


def _mtime(path: Path | None) -> float | None:
    try:
        return path.stat().st_mtime if path else None
    except OSError:
        return None


def _session(provider, sid, name, cwd, state, waiting_for, *, kind, started, updated, last):
    return {
        "provider": provider, "id": sid, "name": name or sid[:8], "cwd": cwd,
        "project": project_name(cwd) if cwd else None, "state": state,
        "waiting_for": waiting_for, "kind": kind, "started": started, "updated": updated,
        "last": last,
    }  # fmt: skip


# Claude Code


def claude(config, *, run=_run) -> list[dict]:
    """Claude's interactive sessions as `claude agents` lists them, the desktop app's
    included. Background sessions (`claude --bg`: wake-ups, dispatched checks) are
    agents' side tasks, not conversations the user holds, so they stay out."""
    found = []
    for row in json.loads(run(["claude", "agents", "--json"]) or "[]"):
        sid = row.get("sessionId")
        if not isinstance(sid, str) or not sid or row.get("kind") == "background":
            continue
        path = _claude_path(config, sid)
        last, said_at = _claude_tail(path)
        state, waiting_for = _claude_state(row)
        started = row.get("startedAt")
        found.append(_session(
            "claude", sid, row.get("name"), row.get("cwd"), state, waiting_for,
            kind=row.get("kind"), started=_iso(started / 1000) if started else None,
            updated=said_at or _iso(_mtime(path)), last=last,
        ))  # fmt: skip
    return found


def _claude_state(row: dict) -> tuple[str, str | None]:
    status = row.get("status")
    if status in ("busy", "working", "running"):
        return "working", None
    if status == "waiting" or row.get("waitingFor"):
        return "waiting", row.get("waitingFor") or "you"
    return "idle", None


def _claude_path(config, sid: str) -> Path | None:
    key = (str(config.claude_home), "claude", sid)
    if key not in _paths:
        found = next((config.claude_home / "projects").glob(f"*/{sid}.jsonl"), None)
        if found is None:
            return None
        _paths[key] = found
    return _paths[key]


def _tail_records(path: Path | None):
    """The JSON records in the last part of a transcript, oldest first."""
    if path is None:
        return
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return
    lines = chunk.splitlines()
    for line in lines[1:] if size > TAIL_BYTES else lines:  # the first may be cut
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def _claude_tail(path: Path | None) -> tuple[str | None, str | None]:
    """The first line of the last thing the session said, and when."""
    last = at = None
    for record in _tail_records(path):
        message = record.get("message") or {}
        if record.get("type") != "assistant" or not isinstance(message.get("content"), list):
            continue
        text = "\n".join(b.get("text", "") for b in message["content"]
                         if isinstance(b, dict) and b.get("type") == "text").strip()  # fmt: skip
        if text:
            last, at = first_line(text, 200), record.get("timestamp")
    return last, at


# Codex


class AppServer:
    """A JSON-lines client for `codex app-server`: requests, and their answers in turn."""

    def __init__(self, command: list[str]):
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )  # fmt: skip
        self.lines: queue.Queue = queue.Queue()
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message: dict) -> None:
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict | None = None, timeout: float = 20.0):
        self.next_id += 1
        asked = self.next_id
        self.send({"id": asked, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError(f"codex app-server gave no answer to {method}") from None
            if line is None:
                raise RuntimeError(f"codex app-server ended before answering {method}")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") != asked:
                continue  # a notification, or an answer to something else
            if "error" in message:
                raise RuntimeError(f"codex app-server: {message['error'].get('message')}")
            return message.get("result")

    def start(self) -> "AppServer":
        self.request("initialize", {"clientInfo": {"name": "ax", "title": "ax", "version": "1"},
                                    "capabilities": None})  # fmt: skip
        self.send({"method": "initialized"})
        return self

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


def codex_command(config) -> list[str]:
    """The shared daemon when the Codex app runs one, so states match the app."""
    socket = config.codex_home / "app-server-control" / "app-server-control.sock"
    return ["codex", "app-server", "proxy"] if socket.exists() else ["codex", "app-server"]


def codex(config, *, command=None, held=None, now=None) -> list[dict]:
    """Codex threads that are live: loaded in an app-server, open in the app, or touched
    in the last day."""
    from ax import job_wake

    held = held or (lambda thread: job_wake.codex_held(config, thread))
    now = time.time() if now is None else now
    server = AppServer(command or codex_command(config)).start()
    try:
        listed = server.request("thread/list", {"limit": 50, "sortKey": "updated_at",
                                                "useStateDbOnly": True}) or {}  # fmt: skip
    finally:
        server.close()
    found = []
    for thread in listed.get("data") or []:
        status = thread.get("status") or {}
        loaded = status.get("type") not in (None, "notLoaded")
        is_open = held(thread["id"])
        if not loaded and not is_open and now - (thread.get("updatedAt") or 0) > RECENT:
            continue
        path = Path(thread["path"]) if thread.get("path") else None
        if path:
            _paths[(str(config.codex_home), "codex", thread["id"])] = path
        last, turn_open = _codex_tail(path)
        moved = _mtime(path)
        state, waiting_for = _codex_state(status, turn_open, moved, is_open, now)
        found.append(_session(
            "codex", thread["id"], thread.get("name") or first_line(thread.get("preview") or "", 80),
            thread.get("cwd"), state, waiting_for, kind="app" if is_open else thread.get("source"),
            started=_iso(thread.get("createdAt")), updated=_iso(thread.get("updatedAt")), last=last,
        ))  # fmt: skip
    return found


def _codex_tail(path: Path | None) -> tuple[str | None, bool]:
    """The first line of the thread's last answer, and whether a turn is still open."""
    last, turn_open = None, False
    for record in _tail_records(path):
        payload = record.get("payload") or {}
        kind = payload.get("type")
        if record.get("type") == "event_msg" and kind == "task_started":
            turn_open = True
        elif record.get("type") == "event_msg" and kind in ("task_complete", "turn_aborted"):
            turn_open = False
        elif kind == "message" and payload.get("role") == "assistant":
            text = "\n".join(c.get("text", "") for c in payload.get("content") or []
                             if isinstance(c, dict) and c.get("type") == "output_text").strip()  # fmt: skip
            if text:
                last = first_line(text, 200)
    return last, turn_open


def _codex_state(status: dict, turn_open: bool, moved, is_open: bool, now: float):
    kind = status.get("type")
    if kind == "active":
        flags = status.get("activeFlags") or []
        if "waitingOnApproval" in flags:
            return "waiting", "approval"
        if "waitingOnUserInput" in flags:
            return "waiting", "input"
        return "working", None
    if kind == "systemError":
        return "waiting", "an error"
    if kind == "idle":
        return "idle", None
    fresh = moved is not None and now - moved < STALE_TURN
    return ("working", None) if turn_open and (is_open or fresh) else ("idle", None)


def _codex_path(config, sid: str) -> Path | None:
    key = (str(config.codex_home), "codex", sid)
    if key not in _paths:
        found = next((config.codex_home / "sessions").rglob(f"rollout-*-{sid}.jsonl"), None)
        if found is None:
            return None
        _paths[key] = found
    return _paths[key]


# Together


def listing(config, *, claude_of=claude, codex_of=codex) -> dict:
    """Every live session, those waiting for the user first, each with its jobs counted."""
    sessions, errors = [], []
    for name, read in (("claude", claude_of), ("codex", codex_of)):
        try:
            sessions += read(config)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append(f"{name}: {exc}")
    counts = job_card.counts(config)
    for s in sessions:
        s["jobs"] = counts.get((s["provider"], s["id"]), 0)
    sessions.sort(key=lambda s: (_ORDER.get(s["state"], 3), _negated(s["updated"])))
    return {"sessions": sessions, "errors": errors}


def _negated(iso: str | None) -> float:
    try:
        return -jobs.parse_iso(iso).timestamp() if iso else 0.0
    except ValueError:
        return 0.0


def cached_listing(config, *, ttl: float = LISTING_TTL) -> dict:
    """The listing at most `ttl` seconds old: the app asks every few seconds, and asking
    both tools costs about a second."""
    key = str(config.data)
    found = _listings.get(key)
    if found and time.monotonic() - found[0] < ttl:
        return found[1]
    fresh = listing(config)
    _listings[key] = (time.monotonic(), fresh)
    return fresh


def _parse(provider: str, path: Path) -> list:
    stat = path.stat()
    stamp = (stat.st_size, stat.st_mtime_ns)
    cached = _parsed.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    parser = claude_source.parse if provider == "claude" else codex_source.parse
    events = parser(path).events
    _parsed[str(path)] = (stamp, events)
    return events


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…"


def _shown(i: int, e) -> dict:
    return {
        "i": i, "kind": e.kind, "text": redact(_clip(e.text or "", TEXT_CHARS)),
        "tool": e.tool, "ok": e.ok, "output": redact(_clip(e.output or "", OUTPUT_CHARS)),
        "ts": e.ts.isoformat(timespec="seconds") if e.ts else None,
    }  # fmt: skip


def transcript(config, provider: str, sid: str, *, after: int = 0, limit: int = 300) -> dict:
    """The user's messages and the agent's answers from event `after`, or the last `limit`
    of them at first, redacted, and the command running now, if any.

    Finished commands and notices are left out: a reader wants the conversation, and while
    the agent works, one line on what it runs. `next` counts every event, so the page
    asks for what came after the last one it saw.
    """
    if provider not in ("claude", "codex"):
        raise ValueError(f"unknown provider {provider!r}")
    path = _claude_path(config, sid) if provider == "claude" else _codex_path(config, sid)
    if path is None or not path.exists():
        raise NotFound(f"no transcript for {provider} session {sid}")
    events = _parse(provider, path)
    chat = [i for i, e in enumerate(events) if e.kind in ("user", "assistant")]
    picked = [i for i in chat if i >= after] if after else chat[-limit:]
    since = chat[-1] + 1 if chat else 0
    running = [i for i in range(since, len(events))
               if events[i].kind == "tool" and events[i].ok is None and not events[i].output]  # fmt: skip
    return {
        "events": [_shown(i, events[i]) for i in picked],
        "running": [_shown(i, events[i]) for i in running[-1:]],
        "next": len(events),
        "first": after if after else (picked[0] if picked else 0),
        "earlier": 0 if after else len(chat) - len(picked),
    }


def session_view(config, provider: str, sid: str, *, after: int = 0) -> dict:
    """One session for the app: its state, its transcript from `after`, and its job cards."""
    found = transcript(config, provider, sid, after=after)
    listed = cached_listing(config)["sessions"]
    session = next((s for s in listed if s["provider"] == provider and s["id"] == sid),
                   {"provider": provider, "id": sid, "name": sid[:8], "state": None})  # fmt: skip
    return {"session": session, **found, "cards": job_card.session_cards(config, provider, sid)}

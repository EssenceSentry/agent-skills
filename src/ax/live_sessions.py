"""Every live session of Claude Code and Codex: what each is doing, the last thing it
said, the jobs it waits on, and its transcript as it grows.

This is the read-only first stage of the chat view (PLAN.md, component 21). Claude's
interactive sessions, the desktop app's included, come from `claude agents --json`.
Codex threads come from its app-server: the shared daemon when the Codex app runs one,
so states match the app, else a short-lived `codex app-server`, whose threads aren't
loaded; their state is then read from the end of each rollout. Transcripts are parsed with the archive's own
parsers, again only when the file grew, and redacted before they leave ax.
"""

import base64
import binascii
import contextlib
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from ax import job_card, jobs
from ax.redact import redact
from ax.sources import claude as claude_source
from ax.sources import codex as codex_source
from ax.sources.common import claude_images, codex_images, first_line, open_text, project_name

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
_parsed: dict[str, tuple[tuple[int, int], object]] = {}  # path -> (size and time, parsed)
_listings: dict[str, tuple[float, dict]] = {}
_listing_lock = threading.RLock()


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
        if path.suffix == ".zst":  # a compressed rollout reads from its start
            with open_text(path) as fh:
                text = fh.read()
            size, chunk = len(text), text[-TAIL_BYTES:]
        else:
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
    """A thread's rollout: plain while Codex writes it, `.jsonl.zst` once it compresses an
    older one, in `sessions/` or `archived_sessions/`. The newest copy, looked for again
    when the one remembered has gone (compressed or archived since)."""
    key = (str(config.codex_home), "codex", sid)
    known = _paths.get(key)
    if known is None or not known.exists():
        copies = [path for root in ("sessions", "archived_sessions")
                  for pattern in (f"rollout-*-{sid}.jsonl", f"rollout-*-{sid}.jsonl.zst")
                  for path in (config.codex_home / root).rglob(pattern)]  # fmt: skip
        if not copies:
            _paths.pop(key, None)
            return None
        _paths[key] = max(copies, key=_age)
    return _paths[key]


def _age(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:  # compressed or archived while we looked
        return -1


# Together


def transcript_path(config, provider: str, sid: str) -> Path | None:
    """Where a session of either tool keeps its transcript, if it has one yet."""
    return _claude_path(config, sid) if provider == "claude" else _codex_path(config, sid)


def listing(config, *, claude_of=claude, codex_of=codex) -> dict:
    """Every live session, those waiting for the user first, each with its jobs counted."""
    sessions, errors = [], []
    for name, read in (("claude", claude_of), ("codex", codex_of)):
        try:
            sessions += read(config)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append(f"{name}: {exc}")
    from ax import chat

    listed = {(s["provider"], s["id"]): s for s in sessions}
    chat.yield_held(config)  # what the Claude app opened since, ax lets go of
    for mine in chat.held():  # what ax holds itself: its state is the true one
        found = listed.get((mine["provider"], mine["id"]))
        if found:
            found.update(state=mine["state"], waiting_for=mine["waiting_for"], kind=mine["kind"],
                         name=mine["name"])  # its first words, over the tool's placeholder  # fmt: skip
        else:
            sessions.append(mine)
    from ax import chat_store

    for row in sessions:
        meta = chat_store.metadata(config, row["provider"], row["id"])
        row.update(
            {k: v for k, v in meta.items() if k in ("name", "pinned", "archived", "group", "order")}
        )
    present = {(row["provider"], row["id"]) for row in sessions}
    for meta in chat_store.all_metadata(config):
        if (meta["provider"], meta["id"]) not in present and meta.get("name"):
            sessions.append(
                {
                    **_session(
                        meta["provider"],
                        meta["id"],
                        meta["name"],
                        meta.get("cwd"),
                        None,
                        None,
                        kind="saved",
                        started=None,
                        updated=None,
                        last=None,
                    ),
                    **meta,
                }
            )
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
    with _listing_lock:
        found = _listings.get(key)
        if found and time.monotonic() - found[0] < ttl:
            return found[1]
        fresh = listing(config)
        _listings[key] = (time.monotonic(), fresh)
        return fresh


def _parsed_session(provider: str, path: Path):
    """The archive's reading of a transcript, again only when the file changed."""
    stat = path.stat()
    stamp = (stat.st_size, stat.st_mtime_ns)
    cached = _parsed.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    parser = claude_source.parse if provider == "claude" else codex_source.parse
    parsed = parser(path)
    _parsed[str(path)] = (stamp, parsed)
    return parsed


def _parse(provider: str, path: Path) -> list:
    return _parsed_session(provider, path).events


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…"


def _picture(provider: str, sid: str, ref: dict) -> dict:
    url = (f"/api/session/image?provider={provider}&id={quote(sid)}"
           f"&line={ref['line']}&n={ref['n']}")  # fmt: skip
    return {"url": url, "media": ref["media"], "line": ref["line"], "n": ref["n"]}


def _asked(ask: dict) -> dict:
    """A question set for the page; what was typed for a secret one stays hidden."""
    answers = ask.get("answers")
    if answers:
        answers = [["•••"] if a and q.get("secret") else a
                   for q, a in zip(ask["questions"], answers, strict=False)]  # fmt: skip
    return {**ask, "answers": answers}


def _is_question(e) -> bool:
    return e.kind == "tool" and bool(e.ask and e.ask.get("questions"))


def _shown(i: int, e, provider: str = "", sid: str = "", shots=()) -> dict:
    text = e.text or ""
    if e.images:  # the archive marks each picture with "[image]"; here it shows itself
        text = "\n\n".join(p for p in text.split("\n\n") if p.strip() != "[image]")
    return {
        "i": i, "kind": e.kind, "text": redact(_clip(text, TEXT_CHARS)),
        "native_id": e.native_id, "turn_id": e.turn_id, "call_id": e.call_id,
        "tool": e.tool, "ok": e.ok, "exit_code": e.exit_code, "duration_ms": e.duration_ms, "output": redact(_clip(e.output or "", OUTPUT_CHARS)),
        "ts": e.ts.isoformat(timespec="seconds") if e.ts else None,
        "images": [_picture(provider, sid, ref) for ref in e.images],
        "shots": [_picture(provider, sid, ref) for ref in shots],
        **({"kind": "question", "ask": _asked(e.ask)} if _is_question(e) else {}),
    }  # fmt: skip


def transcript(config, provider: str, sid: str, *, after: int = 0, limit: int = 300,
               again: Iterable[int] = (), before: int | None = None, include_tools=False,
               cursor: str | None = None, query: str | None = None) -> dict:  # fmt: skip
    """The user's messages and the agent's answers from event `after`, or the last `limit`
    of them at first, redacted, and the command running now, if any.

    Finished commands and notices are left out: a reader wants the conversation, and while
    the agent works, one line on what it runs. `next` counts every event, so the page
    asks for what came after the last one it saw, and names in `again` the questions it
    still shows open: an answer changes an event the page already has.
    """
    if provider not in ("claude", "codex"):
        raise ValueError(f"unknown provider {provider!r}")
    path = transcript_path(config, provider, sid)
    if path is None or not path.exists():
        raise NotFound(f"no transcript for {provider} session {sid}")
    events = _parse(provider, path)
    reset = False

    def anchor(offset):
        digest = hashlib.sha256()
        for event in events[:offset]:
            digest.update(
                f"{event.kind}:{event.ts}:{event.native_id}:{event.text}\n".encode(
                    "utf-8", "replace"
                )
            )
        return digest.hexdigest()[:20]

    if cursor:
        try:
            offset, stamp = json.loads(base64.urlsafe_b64decode(cursor))
            if offset > len(events) or anchor(offset) != stamp:
                after, reset = 0, True
            else:
                after = offset
        except (ValueError, TypeError):
            raise ValueError("invalid history cursor") from None
    limit = max(1, min(int(limit), 500))
    # The conversation: your messages, its answers and the questions it asked you; a reply
    # that answered a question shows as the question's answer, not again as a message.
    chat = [i for i, e in enumerate(events)
            if (e.kind in ("user", "assistant") and not (e.ask and e.ask.get("reply")))
            or _is_question(e) or (include_tools and e.kind in ("tool", "notice"))]  # fmt: skip
    excerpts = {}
    if query:
        needle = query.casefold()
        for call_id, raw in _raw_tool_outputs(provider, path):
            clean = redact(raw)
            index = clean.casefold().find(needle)
            if index >= 0:
                excerpts[call_id] = clean[max(0, index - 250) : index + 750]
        chat = [
            i
            for i in chat
            if needle in redact(f"{events[i].text}\n{events[i].output}").casefold()
            or events[i].call_id in excerpts
        ]
    eligible = [i for i in chat if before is None or i < before]
    picked = [i for i in eligible if i >= after][:limit] if after else eligible[-limit:]
    next_offset = picked[-1] + 1 if after and len(picked) == limit else len(events)
    if after:
        asked = {i for i in again if 0 <= i < min(after, len(events)) and events[i].kind == "tool"}
        picked = sorted(asked) + picked
    since = chat[-1] + 1 if chat else 0
    running = [i for i in range(since, len(events))
               if events[i].kind == "tool" and events[i].ok is None and not events[i].output]  # fmt: skip
    # Screenshots and pictures the tools returned go under the answer that follows them.
    shots: dict[int, list] = {}
    waiting: list = []
    for i, e in enumerate(events):
        if e.kind == "tool":
            waiting += e.images
        elif e.kind == "assistant":
            shots[i], waiting = waiting, []
    return {
        "events": [
            {
                **_shown(i, events[i], provider, sid, shots.get(i, ())),
                **(
                    {"output": excerpts[events[i].call_id]} if events[i].call_id in excerpts else {}
                ),
            }
            for i in picked
        ],
        "running": [_shown(i, events[i], provider, sid) for i in running[-1:]],
        "shots": [_picture(provider, sid, ref) for ref in waiting],  # no answer after them yet
        "next": next_offset,
        "first": after if after and not cursor else (picked[0] if picked else (before or 0)),
        "earlier": sum(i < picked[0] for i in chat) if picked else 0,
        "cursor": base64.urlsafe_b64encode(
            json.dumps([next_offset, anchor(next_offset)]).encode()
        ).decode(),
        "reset": reset,
    }


_offsets: dict[str, tuple[int, list[int]]] = {}


_packed: dict = {}  # the last compressed rollout read whole: its path, its stamp, its lines


def _packed_line(path: Path, number: int) -> bytes | None:
    """One line of a compressed rollout, which no longer grows: decompressed once, split
    as the parsers split it, so line numbers agree."""
    stamp = path.stat().st_mtime_ns
    if _packed.get("path") != str(path) or _packed.get("stamp") != stamp:
        with open_text(path) as fh:
            lines = [line.encode() for line in fh]
        _packed.update(path=str(path), stamp=stamp, lines=lines)
    lines = _packed["lines"]
    return lines[number] if 0 <= number < len(lines) else None


def _line_at(path: Path, number: int) -> bytes | None:
    """One line of a growing transcript, from an index of where its lines start that is
    extended as the file grows."""
    if path.suffix == ".zst":
        return _packed_line(path, number)
    size = path.stat().st_size
    scanned, starts = _offsets.get(str(path), (0, [0]))
    if size < scanned:  # replaced, not grown
        scanned, starts = 0, [0]
    with path.open("rb") as f:
        if size > scanned:
            f.seek(scanned)
            at = scanned
            while chunk := f.read(1 << 20):
                found = chunk.find(b"\n")
                while found != -1:
                    starts.append(at + found + 1)
                    found = chunk.find(b"\n", found + 1)
                at += len(chunk)
            _offsets[str(path)] = (size, starts)
        if not 0 <= number < len(starts) or starts[number] >= size:
            return None
        f.seek(starts[number])
        return f.readline()


def image(config, provider: str, sid: str, line: int, n: int) -> tuple[bytes, str]:
    """The `n`th image in line `line` of a session's transcript, and its media type."""
    if provider not in ("claude", "codex"):
        raise ValueError(f"unknown provider {provider!r}")
    path = transcript_path(config, provider, sid)
    raw = _line_at(path, line) if path and path.exists() else None
    try:
        record = json.loads(raw) if raw else None
    except ValueError:
        record = None
    if not isinstance(record, dict):
        raise NotFound(f"no line {line} in that transcript")
    found = (claude_images(record) if provider == "claude"
             else codex_images(record.get("payload") or {}))  # fmt: skip
    if not 0 <= n < len(found):
        raise NotFound(f"no image {n} on line {line}")
    media, data, _ = found[n]
    try:
        return base64.b64decode(data), media
    except (ValueError, binascii.Error):
        raise NotFound("that image can't be read") from None


def session_view(config, provider: str, sid: str, *, after: int = 0,
                 again: Iterable[int] = (), before: int | None = None, include_tools=False,
                 cursor: str | None = None, query: str | None = None) -> dict:  # fmt: skip
    """One session for the app: its state, its transcript from `after` with the questions
    named in `again`, its job cards, what it is doing now and its turn's task list. One ax
    has just started shows before its tool has written a transcript."""
    from ax import chat, session_activity

    held = next((s for s in chat.held() if s["provider"] == provider and s["id"] == sid), None)
    try:
        found = transcript(
            config,
            provider,
            sid,
            after=after,
            again=again,
            before=before,
            include_tools=include_tools,
            cursor=cursor,
            query=query,
        )
    except NotFound:
        if held is None:
            raise
        found = {"events": [], "running": [], "shots": [], "next": 0, "first": 0, "earlier": 0}
    listed = cached_listing(config)["sessions"]
    session = next((s for s in listed if s["provider"] == provider and s["id"] == sid), held)
    path = transcript_path(config, provider, sid)
    if session is None:  # no longer live: its transcript still knows its folder and title
        parsed = _parsed_session(provider, path) if path and path.exists() else None
        cwd = getattr(parsed, "cwd", None)
        session = {"provider": provider, "id": sid, "state": None,
                   "name": getattr(parsed, "title", None) or sid[:8], "cwd": cwd,
                   "project": project_name(cwd) if cwd else None}  # fmt: skip

    from ax import chat_store

    session.update(chat_store.metadata(config, provider, sid))
    now = (session_activity.read(path, provider) if path and path.exists()
           else {"activity": None, "tasks": None})  # fmt: skip
    talk = chat.state(config, provider, sid)
    return {"session": session, **found, "cards": job_card.session_cards(config, provider, sid),
            "chat": talk, "activity": now["activity"],
            "tasks": now["tasks"] or talk.get("tasks")}  # a Codex plan arrives only live  # fmt: skip


def tool_output(config, provider, sid, index, offset=0):
    path = transcript_path(config, provider, sid)
    if path is None:
        raise NotFound("No transcript")
    events = _parse(provider, path)
    if not 0 <= index < len(events):
        raise ValueError("No such event")
    event = events[index]
    output = event.output or ""
    if event.call_id:
        from collections import Counter

        from ax.sources import claude as claude_source
        from ax.sources import codex as codex_source
        from ax.sources.common import iter_records

        for record in iter_records(path, Counter()):
            if provider == "claude" and record.get("type") == "user":
                content = (record.get("message") or {}).get("content") or []
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict) and block.get("tool_use_id") == event.call_id:
                        output = claude_source._result_text(block.get("content"))
            elif provider == "codex":
                item = record.get("payload") or {}
                if item.get("call_id") == event.call_id and item.get("type") in (
                    "function_call_output",
                    "custom_tool_call_output",
                ):
                    output = codex_source._output_text(item.get("output"))
    output = redact(output)
    offset = max(0, offset)
    return {
        "text": output[offset : offset + 16000],
        "next": offset + 16000 if len(output) > offset + 16000 else None,
    }


def context_files(cwd, query):
    import re

    root = Path(cwd).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Choose a working folder first")
    match = re.fullmatch(r"(.*?)(?::(\d+)(?:[-–](\d+))?)?", query)
    needle = (match[1] if match else query).casefold()
    try:
        run = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True,
            timeout=10,
            check=True,
        )
        files = [root / os.fsdecode(p) for p in run.stdout.split(b"\0") if p][:5000]
    except (OSError, subprocess.SubprocessError):
        files = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".") and d not in ("node_modules", "__pycache__", "dist")
            ]
            files.extend(Path(folder) / name for name in names)
            if len(files) >= 2000:
                break
    result = []
    for file in [f for f in files if needle in str(f).casefold()][:30]:
        if match and match[2]:
            text = file.read_text()
            lines = text.splitlines()
            start, end = int(match[2]), int(match[3] or match[2])
            if not 1 <= start <= end <= len(lines):
                continue
            result.append(
                {
                    "kind": "selection",
                    "path": str(file),
                    "start": start,
                    "end": end,
                    "text": "\n".join(lines[start - 1 : end]),
                    "language": "",
                }
            )
        else:
            result.append({"kind": "file", "path": str(file)})
    return result


def _raw_tool_outputs(provider, path):
    from collections import Counter

    from ax.sources import claude as claude_source
    from ax.sources import codex as codex_source
    from ax.sources.common import iter_records

    for record in iter_records(path, Counter()):
        if provider == "claude" and record.get("type") == "user":
            content = (record.get("message") or {}).get("content") or []
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("tool_use_id"):
                    yield block["tool_use_id"], claude_source._result_text(block.get("content"))
        elif provider == "codex":
            item = record.get("payload") or {}
            if item.get("call_id") and item.get("type") in (
                "function_call_output",
                "custom_tool_call_output",
            ):
                yield item["call_id"], codex_source._output_text(item.get("output"))

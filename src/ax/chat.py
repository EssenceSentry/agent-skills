"""Writing to sessions from the ax app.

Codex: a thread the Codex app has open gets the message through `codex queue`, which
hands it to the app as the thread's next turn, approvals and all. Any other thread is
continued through a private `codex app-server`: its reply streams here, and its
approvals are answered here.

Claude Code: a session nothing else holds is continued by a headless `claude -p` that
speaks stream-json, in the background: its reply streams here, and its tools ask here.
A session the desktop app or a terminal holds can't be written to from outside:
resuming it would start a copy working beside it on the same files, and its inbox takes
messages from other sessions, never as the user. So it is taken over: the user closes it
there, and ax continues it.

Whatever comes through a shared link needs a second yes: the first request is answered
with a one-time confirmation for exactly that message or approval, and only a second
request carrying it acts.
"""

import base64
import binascii
import contextlib
import hashlib
import json
import os
import queue
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from ax import job_wake
from ax.sources import claude as claude_source
from ax.sources.common import first_line

CONFIRM_TTL = 120.0  # seconds a confirmation from a shared link stays good
CODEX_RESUME = {"excludeTurns": True}  # what resuming a thread changes: nothing it runs with
IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 10_000_000
OPEN_TTL = 3.0  # seconds `claude agents` is trusted for which sessions are open elsewhere
_APPROVALS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
}


class Driver:
    """One conversation ax holds open: whether a turn runs, the reply streaming in, and
    the approval it waits on."""

    provider = ""

    def __init__(self, sid: str, name: str | None, cwd: str | None):
        self.sid, self.name, self.cwd = sid, name or sid[:8], cwd
        self.busy = False
        self.partial = ""
        self.approval: dict | None = None
        self.error: str | None = None
        self.started = time.time()
        self.lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.process: subprocess.Popen | None = None

    def _spawn(self, command: list[str]) -> None:
        folder = self.cwd if self.cwd and Path(self.cwd).is_dir() else None
        self.process = subprocess.Popen(
            command, cwd=folder, env=job_wake.clean_env(os.environ), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )  # fmt: skip
        threading.Thread(target=self._read_all, daemon=True).start()

    def _write(self, message: dict) -> None:
        with self._write_lock:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()

    def _read_all(self) -> None:
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                self._read(message)
        self.busy, self.approval = False, None
        self.error = self.error or f"the {self.provider} process ended"

    def _read(self, message: dict) -> None:
        raise NotImplementedError

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def view(self) -> dict:
        return {"busy": self.busy, "partial": self.partial, "approval": self.approval,
                "error": self.error}  # fmt: skip

    def _claim(self) -> None:
        with self.lock:
            if self.busy:
                raise ValueError("it is still working: wait for its answer, or stop it")
            if not self.alive:
                raise ValueError(self.error or "its process has ended; send again to restart it")
            self.busy, self.partial, self.error = True, "", None

    def close(self) -> None:
        if self.process is None:
            return
        with contextlib.suppress(OSError):
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()


class CodexDriver(Driver):
    """A Codex thread continued through a private app-server."""

    provider = "codex"

    def __init__(self, sid, name, cwd, command: list[str]):
        super().__init__(sid, name, cwd)
        self.next_id = 0
        self.answers: dict[int, queue.Queue] = {}
        self.asked: dict[str, object] = {}  # an approval's id here -> the server's own id
        self.turn: str | None = None
        self._spawn(command)
        self.call("initialize", {"clientInfo": {"name": "ax", "title": "ax", "version": "1"},
                                 "capabilities": None})  # fmt: skip
        self._write({"method": "initialized"})
        # The thread keeps its own approval settings, as in the Codex app: approvals
        # that would come to the user there come to the page here. A new one starts in
        # its folder with the user's settings.
        if sid is None:
            started = self.call("thread/start", {"cwd": cwd})
            self.sid = (started.get("thread") or {}).get("id") or ""
            if not self.sid:
                raise ValueError("codex started no thread")
        else:
            self.call("thread/resume", {"threadId": sid, **CODEX_RESUME})

    def call(self, method: str, params: dict, timeout: float = 30.0):
        with self.lock:
            self.next_id += 1
            asked = self.next_id
            box = self.answers[asked] = queue.Queue()
        self._write({"id": asked, "method": method, "params": params})
        try:
            answer = box.get(timeout=timeout)
        except queue.Empty:
            raise ValueError(f"codex didn't answer {method}") from None
        finally:
            self.answers.pop(asked, None)
        if "error" in answer:
            raise ValueError(f"codex: {(answer['error'] or {}).get('message')}")
        return answer.get("result") or {}

    def _read(self, message: dict) -> None:
        method, params = message.get("method"), message.get("params") or {}
        if method is None and "id" in message:
            box = self.answers.get(message["id"])
            if box:
                box.put(message)
        elif "id" in message:
            self._asked(message["id"], method, params)
        elif method == "item/agentMessage/delta":
            self.partial += params.get("delta") or ""
        elif method == "turn/started":
            self.busy, self.turn = True, (params.get("turn") or {}).get("id") or self.turn
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            self.busy, self.partial, self.approval, self.turn = False, "", None, None
            if turn.get("status") == "failed":
                self.error = ((turn.get("error") or {}).get("message")) or "the turn failed"
        elif method == "error":
            self.error = (params.get("error") or {}).get("message") or "codex reported an error"

    def _asked(self, raw_id, method: str, params: dict) -> None:
        if method not in _APPROVALS:  # nothing here can answer it; don't leave the turn hanging
            self._write({"id": raw_id, "error": {"code": -32601, "message": (
                "ax can't answer this; open the thread in the Codex app")}})  # fmt: skip
            return
        key = f"codex-{raw_id}"
        self.asked[key] = raw_id
        if method == "item/commandExecution/requestApproval":
            summary = f"run `{params.get('command') or 'a command'}`"
        elif method == "item/fileChange/requestApproval":
            summary = "change files" + (
                f" under {params['grantRoot']}" if params.get("grantRoot") else ""
            )
        else:
            summary = "use more permissions"
        self.approval = {"id": key, "tool": method.split("/")[1], "summary": summary,
                         "reason": params.get("reason"), "detail": None}  # fmt: skip

    def send(self, text: str, images=()) -> None:
        self._claim()
        given = [{"type": "localImage", "path": i["path"]} for i in images]
        given += [{"type": "text", "text": text}] if text else []
        try:
            started = self.call("turn/start", {"threadId": self.sid, "input": given})
        except ValueError:
            self.busy = False
            raise
        self.turn = self.turn or (started.get("turn") or {}).get("id")

    def answer(self, request: str, allow: bool) -> None:
        raw = self.asked.pop(request, None)
        if raw is None:
            raise ValueError("that approval is no longer waiting")
        self._write({"id": raw, "result": {"decision": "accept" if allow else "decline"}})
        self.approval = None

    def stop(self) -> None:
        if self.turn:
            self.call("turn/interrupt", {"threadId": self.sid, "turnId": self.turn})


class ClaudeDriver(Driver):
    """A Claude session continued by a headless `claude -p` speaking stream-json."""

    provider = "claude"

    def __init__(self, sid, name, cwd, command: list[str]):
        super().__init__(sid, name, cwd)
        self.inputs: dict[str, dict] = {}
        self.ready = threading.Event()
        self.stops = 0
        self._spawn(command)
        self._write({"type": "control_request", "request_id": "init",
                     "request": {"subtype": "initialize"}})  # fmt: skip
        if not self.ready.wait(30):
            self.close()
            raise ValueError("claude didn't start; is it signed in?")

    def _read(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "stream_event":
            event = message.get("event") or {}
            delta = event.get("delta") or {}
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                self.partial += delta.get("text") or ""
        elif kind == "assistant":
            self.partial = ""  # the whole message is in the transcript now
        elif kind == "control_request":
            request = message.get("request") or {}
            if request.get("subtype") == "can_use_tool":
                rid, tool = message.get("request_id"), request.get("tool_name") or "tool"
                given = request.get("input") or {}
                self.inputs[rid] = given
                self.approval = {
                    "id": rid, "tool": tool, "reason": request.get("decision_reason"),
                    "summary": _as_request(claude_source._summarize(tool, given, self.cwd)),
                    "detail": json.dumps(given, indent=2)[:2000],
                }  # fmt: skip
        elif kind == "control_response":
            if (message.get("response") or {}).get("request_id") == "init":
                self.ready.set()
        elif kind == "result":
            self.busy, self.partial, self.approval = False, "", None
            subtype = message.get("subtype") or ""
            if subtype.startswith("error") and subtype != "error_during_execution":
                self.error = message.get("result") or subtype.replace("_", " ")

    def send(self, text: str, images=()) -> None:
        self._claim()
        content = [{"type": "image", "source": {"type": "base64", "media_type": i["media"],
                                                "data": i["data"]}} for i in images]  # fmt: skip
        content += [{"type": "text", "text": text}] if text else []
        self._write({"type": "user", "message": {"role": "user", "content": content}})

    def answer(self, request: str, allow: bool) -> None:
        given = self.inputs.pop(request, None)
        if given is None:
            raise ValueError("that approval is no longer waiting")
        response = ({"behavior": "allow", "updatedInput": given} if allow
                    else {"behavior": "deny", "message": "Refused from the ax app."})  # fmt: skip
        self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": request, "response": response}})  # fmt: skip
        self.approval = None

    def stop(self) -> None:
        self.stops += 1
        self._write({"type": "control_request", "request_id": f"stop-{self.stops}",
                     "request": {"subtype": "interrupt"}})  # fmt: skip


# The transcript says what a tool did; an approval asks for what it would do.
_PRESENT = {"ran": "run", "edited": "edit", "wrote": "write", "searched": "search",
            "listed": "list", "started": "start", "fetched": "fetch", "used": "use",
            "called": "call"}  # fmt: skip


def _as_request(summary: str) -> str:
    first, _, rest = summary.partition(" ")
    return f"{_PRESENT.get(first, first)} {rest}".strip()


def claude_command(sid: str, new: bool = False) -> list[str]:
    """Continue a session headlessly, or start one with this id when `new`, its tools
    asking here before they run."""
    return [
        shutil.which("claude") or "claude", "-p", "--input-format", "stream-json",
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--session-id" if new else "--resume", sid, "--permission-mode", "default",
        "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
    ]  # fmt: skip


def codex_command() -> list[str]:
    return [shutil.which("codex") or "codex", "app-server"]


class Chats:
    """The conversations ax holds open, and take-overs waiting for the app to let go."""

    def __init__(self, codex_command=codex_command, claude_command=claude_command):
        self.codex_command, self.claude_command = codex_command, claude_command
        self.drivers: dict[tuple[str, str], Driver] = {}
        self.pending: dict[tuple[str, str], dict] = {}
        self.lock = threading.Lock()

    def get(self, provider: str, sid: str) -> Driver | None:
        with self.lock:
            found = self.drivers.get((provider, sid))
            if found and not found.alive and not found.busy:
                del self.drivers[(provider, sid)]  # its process ended; a new send restarts it
                return None
            return found

    def open(self, provider: str, sid: str, *, cwd=None, name=None) -> Driver:
        found = self.get(provider, sid)
        if found:
            return found
        if provider == "codex":
            driver: Driver = CodexDriver(sid, name, cwd, self.codex_command())
        else:
            driver = ClaudeDriver(sid, name, cwd, self.claude_command(sid))
        with self.lock:
            self.drivers[(provider, sid)] = driver
            self.pending.pop((provider, sid), None)
        return driver

    def start(self, provider: str, *, cwd: str, name: str | None) -> Driver:
        """A new session in `cwd`, held by ax from its first message."""
        if provider == "codex":
            driver: Driver = CodexDriver(None, name, cwd, self.codex_command())
        else:
            sid = str(uuid.uuid4())
            driver = ClaudeDriver(sid, name, cwd, self.claude_command(sid, new=True))
        with self.lock:
            self.drivers[(provider, driver.sid)] = driver
        return driver

    def release(self, provider: str, sid: str) -> bool:
        with self.lock:
            driver = self.drivers.pop((provider, sid), None)
            self.pending.pop((provider, sid), None)
        if driver:
            driver.close()
        return driver is not None

    def close_all(self) -> None:
        for provider, sid in list(self.drivers):
            self.release(provider, sid)


CHATS = Chats()
_confirmations: dict[str, tuple[float, str]] = {}
_open: dict[str, tuple[float, set]] = {}
_lock = threading.Lock()


def _run(argv: list[str], env) -> tuple[int, str]:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=env)
    return done.returncode, (done.stdout + done.stderr)


def codex_open_in_app(config, tid: str) -> bool:
    return job_wake.codex_held(config, tid)


def claude_open_elsewhere(config, sid: str) -> bool:
    """Whether a Claude process (the desktop app, a terminal, a background run) holds it."""
    now = time.monotonic()
    with _lock:
        cached = _open.get("claude")
    if cached is None or now - cached[0] > OPEN_TTL:
        try:
            out = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True,
                                 timeout=30, check=True).stdout  # fmt: skip
            held = {
                row.get("sessionId") for row in json.loads(out or "[]") if isinstance(row, dict)
            }
        except (OSError, ValueError, subprocess.SubprocessError):
            held = set()
        cached = (now, held)
        with _lock:
            _open["claude"] = cached
    return sid in cached[1]


def held() -> list[dict]:
    """The sessions ax holds open, for the Sessions list."""
    found = []
    for (provider, sid), driver in list(CHATS.drivers.items()):
        approval = driver.approval
        state = "waiting" if approval else ("working" if driver.busy else "idle")
        found.append({
            "provider": provider, "id": sid, "name": driver.name, "cwd": driver.cwd,
            "project": Path(driver.cwd).name if driver.cwd else None, "state": state,
            "waiting_for": "approval" if approval else None, "kind": "ax (background)",
            "started": None, "updated": None, "last": None,
        })  # fmt: skip
    return found


_BACKGROUND = ("Running in the background through ax, so the Claude app doesn't show it. Hand "
               "it back to continue it elsewhere, such as `claude --resume {sid}` in a terminal.")  # fmt: skip


def state(config, provider: str, sid: str) -> dict:
    """Who holds the conversation, whether the user can write to it now, and what runs."""
    base = {"holder": None, "can_send": True, "take_over": False, "pending": False,
            "busy": False, "partial": "", "approval": None, "error": None, "note": ""}  # fmt: skip
    driver = CHATS.get(provider, sid)
    if driver:
        note = (_BACKGROUND.format(sid=sid) if provider == "claude" else
                "ax holds this thread in the background: hand it back before opening it in "
                "the Codex app.")  # fmt: skip
        return {**base, **driver.view(), "holder": "ax", "can_send": not driver.busy,
                "note": note}  # fmt: skip
    if provider == "codex":
        if codex_open_in_app(config, sid):
            return {**base, "holder": "codex app", "note": "Open in the Codex app: your message "
                    "goes there as its next turn, and its approvals are answered there."}  # fmt: skip
        return {**base, "note": "Your message continues this thread in the background "
                "through ax."}  # fmt: skip
    pending = CHATS.pending.get((provider, sid))
    if claude_open_elsewhere(config, sid):
        note = ("Waiting for you to close it in the Claude app; ax continues it here as soon "
                "as it's closed." if pending else "Open in the Claude app or a terminal. Take "
                "over to write here: close it there, and ax continues it in the background.")  # fmt: skip
        return {**base, "holder": "elsewhere", "can_send": False, "take_over": True,
                "pending": bool(pending), "note": note}  # fmt: skip
    if pending:
        CHATS.open(provider, sid, cwd=pending.get("cwd"), name=pending.get("name"))
        return state(config, provider, sid)
    return {**base, "note": "Not open anywhere: your message continues it in the background "
            "through ax."}  # fmt: skip


def _fingerprint(payload: dict) -> str:
    keys = ("action", "provider", "id", "cwd", "text", "request", "allow")
    pictures = [i.get("data") for i in payload.get("images") or [] if isinstance(i, dict)]
    return hashlib.sha256(
        json.dumps([[payload.get(k) for k in keys], pictures]).encode()
    ).hexdigest()


def _question(payload: dict) -> str:
    name = payload.get("name") or str(payload.get("id"))[:8]
    if payload.get("action") in ("send", "start"):
        text = str(payload.get("text") or "").strip()
        shown = text if len(text) <= 300 else text[:300] + "…"
        count = len(payload.get("images") or [])
        pictures = f"\n\nwith {count} image{'s' if count != 1 else ''}" if count else ""
        if payload.get("action") == "start":
            tool = "Codex" if payload.get("provider") == "codex" else "Claude Code"
            return (f"Start a new {tool} session in {payload.get('cwd')} from the shared "
                    f"link?\n\n“{shown}”{pictures}")  # fmt: skip
        return f"Send this to {name} from the shared link?\n\n“{shown}”{pictures}"
    driver = CHATS.get(payload.get("provider"), payload.get("id"))
    approval = (driver.approval if driver else None) or {}
    verb = "Allow" if payload.get("allow") else "Refuse"
    return f"{verb} {approval.get('summary') or 'this'} in {name}, from the shared link?"


def _confirmed(payload: dict) -> dict | None:
    """None when a shared link's request may act; else the confirmation to ask for."""
    given, fingerprint, now = payload.get("confirm"), _fingerprint(payload), time.monotonic()
    with _lock:
        for nonce in [n for n, (expires, _) in _confirmations.items() if expires < now]:
            del _confirmations[nonce]
        if given:
            expected = _confirmations.get(str(given))
            if expected is None or expected[1] != fingerprint:
                raise ValueError("that confirmation doesn't match this or has expired; "
                                 "confirm again")  # fmt: skip
            del _confirmations[str(given)]  # used once
            return None
        nonce = secrets.token_urlsafe(16)
        _confirmations[nonce] = (now + CONFIRM_TTL, fingerprint)
    return {"ok": False, "confirm": nonce, "question": _question(payload)}


def act(config, payload: dict, *, remote: bool = False) -> dict:
    """Send, answer an approval, stop, take over or hand back; a ValueError says why not.
    From a shared link (`remote`), sending and answering need a second request carrying
    the confirmation the first one returns."""
    action, provider, sid = payload.get("action"), payload.get("provider"), payload.get("id")
    if provider not in ("claude", "codex"):
        raise ValueError("say which tool: provider is claude or codex")
    if action != "start" and (not isinstance(sid, str) or not sid):
        raise ValueError("say which session: its id")
    folder = _folder(payload.get("cwd")) if action == "start" else None
    images = _images(payload) if action in ("send", "start") else []
    if action in ("send", "start") and not str(payload.get("text") or "").strip() and not images:
        raise ValueError("there is nothing to send: no text and no image")
    if remote and action in ("send", "answer", "start"):
        ask = _confirmed(payload)
        if ask:
            return ask
    cwd, name = payload.get("cwd"), payload.get("name")
    if action == "start":
        return _start(config, provider, folder, str(payload.get("text") or "").strip(), name,
                      images)  # fmt: skip
    if action == "send":
        text = str(payload.get("text") or "").strip()
        return _send(config, provider, sid, text, cwd, name, images)
    if action == "answer":
        driver = CHATS.get(provider, sid)
        if driver is None:
            raise ValueError("ax isn't holding that session")
        driver.answer(str(payload.get("request")), bool(payload.get("allow")))
        return {"ok": True, "message": "Answered."}
    if action == "stop":
        driver = CHATS.get(provider, sid)
        if driver is None:
            raise ValueError("ax isn't holding that session")
        driver.stop()
        return {"ok": True, "message": "Asked it to stop."}
    if action == "take-over":
        if provider != "claude":
            raise ValueError("Codex threads need no take-over")
        if CHATS.get(provider, sid):
            return {"ok": True, "waiting": False, "message": "ax already holds it."}
        if claude_open_elsewhere(config, sid):
            CHATS.pending[(provider, sid)] = {"cwd": cwd, "name": name}
            return {"ok": True, "waiting": True, "message": (
                "Close it in the Claude app (it stays on disk). ax continues it here, in the "
                "background, as soon as it's closed.")}  # fmt: skip
        CHATS.open(provider, sid, cwd=cwd, name=name)
        return {"ok": True, "waiting": False, "message": _BACKGROUND.format(sid=sid)}
    if action == "release":
        CHATS.release(provider, sid)
        return {"ok": True, "message": "Handed back: ax no longer holds it."}
    raise ValueError(f"unknown action {action!r}")


def _images(payload: dict) -> list[dict]:
    """The pasted images, checked before anything is sent: their media type, base64 data
    and bytes."""
    given = payload.get("images") or []
    if not isinstance(given, list):
        raise ValueError("images must be a list")
    if len(given) > MAX_IMAGES:
        raise ValueError(f"send at most {MAX_IMAGES} images at once")
    found = []
    for item in given:
        media = item.get("media") if isinstance(item, dict) else None
        if media not in IMAGE_TYPES:
            raise ValueError("images must be PNG, JPEG, GIF or WebP")
        try:
            raw = base64.b64decode(str(item.get("data") or ""), validate=True)
        except (ValueError, binascii.Error):
            raw = b""
        if not raw:
            raise ValueError("one of the images isn't an image")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"an image is over {MAX_IMAGE_BYTES // 1_000_000} MB")
        found.append({"media": media, "data": item["data"], "bytes": raw})
    return found


def _saved(config, images: list[dict]) -> list[dict]:
    """The images as files, for Codex, which takes pictures by path."""
    folder = config.data / "chat-images"
    folder.mkdir(parents=True, exist_ok=True)
    for image in images:
        path = folder / f"{uuid.uuid4().hex}{IMAGE_TYPES[image['media']]}"
        path.write_bytes(image["bytes"])
        image["path"] = str(path)
    return images


def _folder(given) -> str:
    """The folder a new session starts in: an existing directory, given in full."""
    if not isinstance(given, str) or not given.strip():
        raise ValueError("say which folder the session starts in")
    folder = Path(given.strip()).expanduser()
    if not folder.is_absolute():
        raise ValueError(f"give the folder in full, from the root: {given!r}")
    if not folder.is_dir():
        raise ValueError(f"there is no folder {folder}")
    return str(folder.resolve())


def _start(config, provider: str, folder: str, text: str, name, images) -> dict:
    """A new session in `folder`, held by ax, its first message sent."""
    title = name or first_line(text, 60) or "New session"
    driver = CHATS.start(provider, cwd=folder, name=title)
    driver.send(text, _saved(config, list(images)) if provider == "codex" else images)
    return {"ok": True, "provider": provider, "id": driver.sid,
            "message": "Started in the background through ax."}  # fmt: skip


def _send(config, provider: str, sid: str, text: str, cwd, name, images=()) -> dict:
    driver = CHATS.get(provider, sid)
    if provider == "codex":
        images = _saved(config, list(images))
    if driver is None and provider == "codex" and codex_open_in_app(config, sid):
        binary = shutil.which("codex") or "codex"
        argv = job_wake.command("codex", sid, text, binary, queue=True)
        argv += [arg for image in images for arg in ("--image", image["path"])]
        code, said = _run(argv, job_wake.clean_env(os.environ))
        if code:
            lines = [line for line in said.splitlines() if line.strip()]
            raise ValueError(f"codex queue: {lines[-1] if lines else code}")
        return {"ok": True, "via": "codex app", "message": "Sent to the Codex app."}
    if driver is None and provider == "claude" and claude_open_elsewhere(config, sid):
        raise ValueError("it's open in the Claude app or a terminal: take it over first")
    if driver is None:
        driver = CHATS.open(provider, sid, cwd=cwd, name=name)
    driver.send(text, images)
    return {"ok": True, "via": "ax", "message": "Sent."}

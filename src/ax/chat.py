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

Each session ax holds also has its modes: plan mode, approve for me, its model and
effort, and a goal to keep pursuing. Claude takes them as permission modes and its model
at once, effort only by restarting between turns, and a goal as its `/goal` command;
Codex takes them with its next turn, and a goal through `thread/goal/set`.
"""

import base64
import binascii
import contextlib
import fcntl
import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from functools import wraps
from pathlib import Path

from ax import chat_store, claude_app, job_wake
from ax.sources import asks
from ax.sources import claude as claude_source
from ax.sources.common import first_line

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


def _request_locked(method):
    @wraps(method)
    def synchronized(self, *args, **kwargs):
        with self.request_lock:
            return method(self, *args, **kwargs)

    return synchronized


class Driver:
    """One conversation ax holds open: whether a turn runs, the reply streaming in, and
    the approval it waits on."""

    provider = ""

    def __init__(self, sid: str, name: str | None, cwd: str | None):
        self.sid, self.name, self.cwd = sid, name or sid[:8], cwd
        self.busy = False
        self.partial = ""
        self.approval: dict | None = None
        self.question: dict | None = (
            None  # a question with options it waits on: {id, via, call, questions}
        )
        self.error: str | None = None
        self.started = time.time()
        self.lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        # Plan mode, approve for me, and the model and effort; None is the session's own.
        self.settings: dict = {"plan": False, "auto": False, "model": None, "effort": None}
        self.models: list[dict] = []  # {id, label, efforts, default_effort}
        self.goal: dict | None = None  # {objective, status, tokens_used, token_budget, seconds}
        self.tasks: dict | None = None  # Codex's plan for the turn, which only arrives live
        self.mid_turn: list[str] = []  # what the user sent while a turn ran, until it ends
        self.pids: set[int] = set()  # every process ax started for it, to know its own
        self.in_app = False  # listed in the Claude app's sessions
        self.request_lock = threading.RLock()
        self.requests: dict[str, dict] = {}
        self.pending_settings: dict = {}
        self.diagnostics = ""
        self.context: dict | None = None
        self.lease = None

    @_request_locked
    def _request(self, value: dict, kind: str) -> None:
        self.requests[value["id"]] = {**value, "kind": kind}
        self._request_heads()

    def _request_heads(self) -> None:
        approval = next((r for r in self.requests.values() if r["kind"] != "question"), None)
        question = next((r for r in self.requests.values() if r["kind"] == "question"), None)
        self.approval = {k: v for k, v in approval.items() if k != "kind"} if approval else None
        self.question = {k: v for k, v in question.items() if k != "kind"} if question else None

    @_request_locked
    def _answered(self, key: str) -> None:
        self.requests.pop(key, None)
        self._request_heads()

    @_request_locked
    def _clear_requests(self) -> None:
        self.requests.clear()
        self.approval = self.question = None
        for field in ("asked", "request_methods", "inputs"):
            getattr(self, field, {}).clear()

    def _spawn(self, command: list[str]) -> None:
        folder = self.cwd if self.cwd and Path(self.cwd).is_dir() else None
        self.process = subprocess.Popen(
            command, cwd=folder, env={**job_wake.clean_env(os.environ), **({"CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING": "1"} if self.provider == "claude" else {})}, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        )  # fmt: skip
        self.pids.add(self.process.pid)
        threading.Thread(target=self._read_all, args=(self.process,), daemon=True).start()
        threading.Thread(target=self._read_errors, args=(self.process,), daemon=True).start()

    def _read_errors(self, process) -> None:
        from ax.redact import redact

        for line in process.stderr:
            self.diagnostics = (self.diagnostics + redact(line))[-12000:]

    def _write(self, message: dict) -> None:
        with self._write_lock:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()

    def _read_all(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and process is self.process:
                try:
                    self._read(message)
                except Exception as exc:
                    self.error = f"{self.provider} event could not be read: {exc}"
        if process is self.process:  # not a process ax replaced on purpose
            self.busy = False
            self._clear_requests()
            self.error = (
                self.error or self.diagnostics.strip() or f"the {self.provider} process ended"
            )

    def _read(self, message: dict) -> None:
        raise NotImplementedError

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @_request_locked
    def view(self) -> dict:
        return {"busy": self.busy, "partial": self.partial, "approval": self.approval,
                "question": self.question, "error": self.error, "settings": dict(self.settings),
                "models": self.models, "goal": self.goal, "tasks": self.tasks,
                "mid_turn": list(self.mid_turn), "requests": list(self.requests.values()),
                "pending_settings": dict(self.pending_settings), "diagnostics": self.diagnostics,
                "context": self.context}  # fmt: skip

    def model(self, wanted: str | None = None) -> dict | None:
        """A model this session offers: the one named, else the one it runs."""
        name = wanted or self.settings["model"] or "default"
        return next((m for m in self.models if m["id"] == name), None)

    def _claim(self) -> None:
        with self.lock:
            if self.busy:
                raise ValueError("it is still working: wait for its answer, or stop it")
            if not self.alive:
                raise ValueError(self.error or "its process has ended; send again to restart it")
            self.busy, self.partial, self.error = True, "", None

    def close(self, *, release=True) -> None:
        process, self.process = self.process, None
        if process is None:
            if release and self.lease:
                self.lease.close()
                self.lease = None
            return
        with contextlib.suppress(OSError):
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if release and self.lease:
            self.lease.close()
            self.lease = None


class CodexDriver(Driver):
    """A Codex thread continued through a private app-server."""

    provider = "codex"

    def __init__(self, sid, name, cwd, command: list[str]):
        super().__init__(sid, name, cwd)
        self.next_id = 0
        self.answers: dict[int, queue.Queue] = {}
        self.asked: dict[str, object] = {}  # an approval's id here -> the server's own id
        self.request_methods: dict[str, tuple[str, dict]] = {}
        self.items: dict[str, dict] = {}
        self.partial_id = None
        self.turn: str | None = None
        self.overrides: dict = {}  # what the user changed, sent with each turn from then on
        self._goal_at = -1
        self._spawn(command)
        # Plan mode (a collaboration mode) is in Codex's experimental API.
        try:
            self._initialize(sid, cwd)
        except BaseException:
            self.close()
            raise

    def _initialize(self, sid, cwd):
        self.call("initialize", {"clientInfo": {"name": "ax", "title": "ax", "version": "2"},
                                 "capabilities": {"experimentalApi": True}})  # fmt: skip
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
            started = self.call("thread/resume", {"threadId": sid, **CODEX_RESUME})
        self._settled(started)
        self.models = codex_models(self.call("model/list", {}))
        self._goal(self.call("thread/goal/get", {"threadId": self.sid}).get("goal"))

    def _settled(self, given: dict) -> None:
        """The settings the thread runs with, as Codex reports them."""
        mode = (given.get("collaborationMode") or {}).get("mode")
        reviewer = given.get("approvalsReviewer")
        self.settings.update(
            plan=mode == "plan" if "collaborationMode" in given else self.settings["plan"],
            auto=reviewer in ("auto_review", "guardian_subagent") if reviewer else self.settings["auto"],
            model=given.get("model") or self.settings["model"],
            effort=given.get("reasoningEffort") if "reasoningEffort" in given else self.settings["effort"],
        )  # fmt: skip

    def _goal(self, goal: dict | None, *, newer: bool = False) -> None:
        """The thread's goal, unless an update already brought a later one."""
        if goal is None:
            self.goal, self._goal_at = None, -1
            return
        at = goal.get("updatedAt") or 0
        if at > self._goal_at or (newer and at >= self._goal_at):
            self._goal_at = at
            self.goal = {"objective": goal.get("objective"), "status": goal.get("status"),
                         "tokens_used": goal.get("tokensUsed"),
                         "token_budget": goal.get("tokenBudget"),
                         "seconds": goal.get("timeUsedSeconds")}  # fmt: skip

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

    @_request_locked
    def _read(self, message: dict) -> None:
        method, params = message.get("method"), message.get("params") or {}
        if method is None and "id" in message:
            box = self.answers.get(message["id"])
            if box:
                box.put(message)
        elif "id" in message:
            self._asked(message["id"], method, params)
        elif method == "item/agentMessage/delta":
            item_id = params.get("itemId")
            if item_id != self.partial_id:
                self.partial, self.partial_id = "", item_id
            self.partial += params.get("delta") or ""
        elif method in ("item/started", "item/completed"):
            item = params.get("item") or {}
            self.items[item.get("id")] = item
            if method == "item/completed" and item.get("type") == "agentMessage":
                self.partial, self.partial_id = "", None
        elif method == "thread/tokenUsage/updated":
            self.context = params.get("tokenUsage")
        elif method == "turn/started":
            self.busy, self.turn = True, (params.get("turn") or {}).get("id") or self.turn
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            self.busy, self.partial, self.approval, self.turn = False, "", None, None
            self.question, self.mid_turn = None, []
            self._clear_requests()
            self.asked.clear()
            self.request_methods.clear()
            if turn.get("status") == "failed":
                self.error = ((turn.get("error") or {}).get("message")) or "the turn failed"
        elif method == "error":
            self.error = (params.get("error") or {}).get("message") or "codex reported an error"
        elif method == "turn/plan/updated":
            self.tasks = {
                "items": [{"text": step.get("step") or "",
                           "status": {"inProgress": "in_progress", "completed": "completed"}.get(
                               step.get("status"), "pending")}
                          for step in params.get("plan") or [] if isinstance(step, dict)],
                "explanation": params.get("explanation"),
            }  # fmt: skip
        elif method == "thread/goal/updated":
            self._goal(params.get("goal"), newer=True)
        elif method == "thread/goal/cleared":
            self._goal(None)
        elif method == "thread/settings/updated":
            self._settled(params.get("threadSettings") or {})

    @_request_locked
    def _asked(self, raw_id, method: str, params: dict) -> None:
        if method in (
            "item/tool/requestUserInput",
            "tool/requestUserInput",
        ):  # a question with options, for the user
            key = f"codex-{raw_id}"
            self.asked[key] = raw_id
            self._request({"id": key, "via": "codex", "call": params.get("itemId"),
                             "questions": [asks.question(q) for q in params.get("questions") or []
                                           if isinstance(q, dict)]}, "question")  # fmt: skip
            return
        if method == "mcpServer/elicitation/request":
            key = f"codex-{raw_id}"
            self.asked[key] = raw_id
            self.request_methods[key] = (method, params)
            self._request(
                {
                    "id": key,
                    "tool": "MCP",
                    "summary": params.get("message") or "MCP input",
                    "reason": None,
                    "detail": json.dumps(params),
                    "elicitation": params,
                },
                "elicitation",
            )
            return
        if method not in _APPROVALS:  # nothing here can answer it; don't leave the turn hanging
            self._write({"id": raw_id, "error": {"code": -32601, "message": (
                "ax can't answer this; open the thread in the Codex app")}})  # fmt: skip
            return
        key = f"codex-{raw_id}"
        self.asked[key] = raw_id
        self.request_methods[key] = (method, params)
        if method == "item/commandExecution/requestApproval":
            summary = f"run `{params.get('command') or 'a command'}`"
        elif method == "item/fileChange/requestApproval":
            summary = "change files" + (
                f" under {params['grantRoot']}" if params.get("grantRoot") else ""
            )
        else:
            summary = "use more permissions"
        item = self.items.get(params.get("itemId"), {})
        self._request(
            {
                "id": key,
                "tool": method.split("/")[1],
                "summary": summary,
                "reason": params.get("reason"),
                "detail": json.dumps({**item, **params}),
                "permissions": params.get("permissions"),
                "plan": None,
            },
            "approval",
        )

    def send(self, text: str, images=()) -> None:
        given = [{"type": "localImage", "path": i["path"]} for i in images]
        given += [{"type": "text", "text": text}] if text else []
        with self.lock:
            running = self.turn if self.busy else None
            waiting = self.approval
        if waiting:  # "or tell it something else": not that, and this instead
            self.answer(waiting["id"], False)
        if running:  # the turn that runs takes it as it goes, as the Codex app's steer
            try:
                self.call("turn/steer", {"threadId": self.sid, "expectedTurnId": running,
                                         "input": given})  # fmt: skip
            except ValueError:
                # Only a lifecycle-confirmed end permits starting another turn. An RPC
                # rejection or timeout can leave delivery uncertain and must stay visible.
                with self.lock:
                    if self.busy or self.turn == running:
                        raise
            else:
                self.mid_turn.append(text or "a picture")
                return
        self._claim()
        self.tasks = None  # a new message starts a new list
        try:
            started = self.call("turn/start", {"threadId": self.sid, "input": given,
                                               **self.overrides})  # fmt: skip
        except ValueError:
            self.busy = False
            raise
        with self.lock:
            if self.busy and not self.turn:
                self.turn = (started.get("turn") or {}).get("id")
        self.settings.update(self.pending_settings)
        self.pending_settings.clear()

    @_request_locked
    def answer(
        self, request: str, allow: bool, message: str | None = None, response: dict | None = None
    ) -> None:
        raw = self.asked.get(request)
        if raw is None:
            raise ValueError("that approval is no longer waiting")
        method, params = self.request_methods.get(request, ("", {}))
        if method == "item/permissions/requestApproval":
            requested = params.get("permissions") or {}
            granted = (response or {}).get("permissions", requested if allow else {})
            # A response cannot expand the requested permission profile.
            from ax.chat_requests import permission_subset

            permission_subset(requested, granted)
            scope = (response or {}).get("scope", "turn")
            if scope not in ("turn", "session"):
                raise ValueError("permission scope is turn or session")
            result = {"permissions": granted, "scope": scope}
        elif method == "mcpServer/elicitation/request":
            result = response or {"action": "accept" if allow else "decline"}
            from ax.chat_requests import elicitation_response

            elicitation_response(params, result)
        else:
            result = {"decision": "accept" if allow else "decline"}
        self._write({"id": raw, "result": result})
        self.asked.pop(request, None)
        self.request_methods.pop(request, None)
        self._answered(request)

    def stop(self) -> None:
        if self.turn:
            self.call("turn/interrupt", {"threadId": self.sid, "turnId": self.turn})

    @_request_locked
    def answer_question(self, request: str, answers: list[list[str]]) -> None:
        raw = self.asked.get(request)
        question = self.requests.get(request) or self.question
        if raw is None or not question:
            raise ValueError("that question is no longer waiting")
        given = {q["id"]: {"answers": a} for q, a in
                 zip(question["questions"], answers, strict=False) if a and q["id"]}  # fmt: skip
        self._write({"id": raw, "result": {"answers": given}})
        self.asked.pop(request, None)
        self._answered(request)

    def configure(self, changes: dict) -> None:
        """New modes, sent with every turn from the next one on; the thread keeps its own
        settings until one is changed."""
        self.pending_settings.update(changes)
        effective = {**self.settings, **self.pending_settings}
        if "auto" in changes:
            self.overrides["approvalsReviewer"] = "auto_review" if changes["auto"] else "user"
        if "model" in changes or "effort" in changes:
            self.overrides.update(model=effective["model"], effort=effective["effort"])
        if "plan" in changes or "collaborationMode" in self.overrides:
            self.overrides["collaborationMode"] = {
                "mode": "plan" if effective["plan"] else "default",
                "settings": {"model": effective["model"],
                             "reasoning_effort": effective["effort"],
                             "developer_instructions": None},
            }  # fmt: skip

    def set_goal(self, objective: str, budget: int | None, images=()) -> None:
        """A goal it keeps pursuing, begun at once with the objective as the message."""
        params = {"threadId": self.sid, "objective": objective, "origin": "user"}
        if budget:
            params["tokenBudget"] = budget
        self._goal(self.call("thread/goal/set", params).get("goal"))
        self.send(objective, images)

    def clear_goal(self) -> None:
        self.call("thread/goal/clear", {"threadId": self.sid, "origin": "user"})
        self._goal(None)


class ClaudeDriver(Driver):
    """A Claude session continued by a headless `claude -p` speaking stream-json."""

    provider = "claude"

    def __init__(self, sid, name, cwd, command: Callable[[str | None, bool], list[str]],
                 effort: str | None = None):  # fmt: skip
        super().__init__(sid, name, cwd)
        self.settings["effort"] = effort  # a new session starts at the effort chosen for it
        self.command = command  # (effort, restarting) -> argv
        self.inputs: dict[str, dict] = {}
        self.stops = 0
        self.asks = 0
        self.controls: dict[str, dict] = {}
        self.mode = "default"  # its permission mode
        self._launch(again=False)

    def _launch(self, *, again: bool) -> None:
        self.ready = threading.Event()
        self.error = None
        self._spawn(self.command(self.settings["effort"], again))
        self._write({"type": "control_request", "request_id": "init",
                     "request": {"subtype": "initialize"}})  # fmt: skip
        if not self.ready.wait(30) or self.error:
            self.close()
            raise ValueError(self.diagnostics.strip() or "claude didn't start; is it signed in?")

    def _control(self, subtype: str, *, changes=None, **fields) -> None:
        self.asks += 1
        key = f"{subtype}-{self.asks}"
        if changes:
            self.controls[key] = changes
            self.pending_settings.update(changes)
        self._write({"type": "control_request", "request_id": key,
                     "request": {"subtype": subtype, **fields}})  # fmt: skip

    def _apply_mode(self) -> None:
        effective = {**self.settings, **self.pending_settings}
        wanted = "plan" if effective["plan"] else "auto" if effective["auto"] else "default"
        if wanted == self.mode:
            for key in ("plan", "auto"):
                if key in self.pending_settings:
                    self.settings[key] = self.pending_settings.pop(key)
        else:
            self._control(
                "set_permission_mode",
                mode=wanted,
                changes={k: effective[k] for k in ("plan", "auto")},
            )

    @_request_locked
    def _read(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "system" and message.get("subtype") == "init":
            self.busy = True  # every turn opens so, a message sent mid-turn's own included
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
                if tool == "AskUserQuestion":
                    self._request({"id": rid, "via": "claude", "call": request.get("tool_use_id"),
                                     "questions": [asks.question(q) for q in given.get("questions") or []
                                                   if isinstance(q, dict)]}, "question")  # fmt: skip
                    return
                from ax.chat_requests import proposed

                preview = proposed(given, self.cwd)
                display = {**given, **({"_patch": preview} if preview else {})}
                plan = given.get("plan") if tool == "ExitPlanMode" else None
                self._request({
                    "id": rid, "tool": tool, "reason": request.get("decision_reason"),
                    "summary": "start on its plan" if plan is not None else
                    _as_request(claude_source._summarize(tool, given, self.cwd)),
                    "detail": None if plan is not None else json.dumps(display, indent=2),
                    "plan": plan,
                }, "approval")  # fmt: skip
            else:
                self.error = f"Claude requested unsupported control {request.get('subtype')!r}; complete it in Claude Code."
                self._write(
                    {
                        "type": "control_response",
                        "response": {
                            "subtype": "error",
                            "request_id": message.get("request_id"),
                            "error": self.error,
                        },
                    }
                )
        elif kind == "control_response":
            response = message.get("response") or {}
            if response.get("request_id") == "init":
                if response.get("subtype") == "error":
                    self.error = response.get("error") or "Claude rejected initialization"
                self._handshake(response.get("response") or {})
                self.ready.set()
            else:
                changed = self.controls.pop(response.get("request_id"), {})
                if response.get("subtype") == "error":
                    self.error = response.get("error") or "Claude rejected the settings change"
                else:
                    self.settings.update(changed)
                    if "plan" in changed or "auto" in changed:
                        self.mode = (
                            "plan"
                            if self.settings["plan"]
                            else "auto"
                            if self.settings["auto"]
                            else "default"
                        )
                for key, value in changed.items():
                    if self.pending_settings.get(key) == value:
                        self.pending_settings.pop(key, None)
        elif kind == "system" and message.get("permissionMode"):
            # Leaving plan mode (its plan approved) shows here; approve for me comes back.
            self.mode = message["permissionMode"]
            if self.mode != "plan" and self.settings["plan"]:
                self.settings["plan"] = False
                threading.Thread(target=self._apply_mode, daemon=True).start()
        elif kind == "result":
            usage = message.get("usage") or {}
            if usage:
                tokens = sum(
                    usage.get(key) or 0
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
                models = message.get("modelUsage") or {}
                model_usage = next(iter(models.values()), {})
                self.context = {
                    "last": {"totalTokens": tokens},
                    "modelContextWindow": model_usage.get("contextWindow"),
                }
            self.busy, self.partial, self.approval, self.question = False, "", None, None
            self.mid_turn = []
            self._clear_requests()
            self.inputs.clear()
            subtype = message.get("subtype") or ""
            if subtype.startswith("error") and subtype != "error_during_execution":
                self.error = message.get("result") or subtype.replace("_", " ")

    def send(self, text: str, images=()) -> None:
        """A message: a new turn, or, while one runs, one Claude reads at its next step or
        runs as the next turn once this one ends, as Claude Code does with what's typed."""
        with self.lock:
            working = self.busy
            waiting = self.approval or self.question
        if waiting and text and not images:
            # "Or tell it something else": the tool it waits on is refused with these words,
            # which Claude reads at once, as Claude Code's "No, and tell Claude what to do".
            self.answer(waiting["id"], False, message=text)
            return
        if not working:
            self._claim()
        content = [{"type": "image", "source": {"type": "base64", "media_type": i["media"],
                                                "data": i["data"]}} for i in images]  # fmt: skip
        content += [{"type": "text", "text": text}] if text else []
        self._write({"type": "user", "message": {"role": "user", "content": content}})
        if working:
            self.mid_turn.append(text or "a picture")

    @_request_locked
    def answer(
        self, request: str, allow: bool, message: str | None = None, response: dict | None = None
    ) -> None:
        """Allow it as asked, or refuse it, with what to do instead when the user said."""
        given = self.inputs.get(request)
        if given is None:
            raise ValueError("that approval is no longer waiting")
        updated = (response or {}).get("updatedInput", given)
        response = ({"behavior": "allow", "updatedInput": updated} if allow
                    else {"behavior": "deny", "message": message or "Refused from the ax app."})  # fmt: skip
        self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": request, "response": response}})  # fmt: skip
        self.inputs.pop(request, None)
        self._answered(request)

    def stop(self) -> None:
        self.stops += 1
        self._write({"type": "control_request", "request_id": f"stop-{self.stops}",
                     "request": {"subtype": "interrupt"}})  # fmt: skip

    @_request_locked
    def answer_question(self, request: str, answers: list[list[str]]) -> None:
        """The answers as the Agent SDK takes them: each question's words to the label
        chosen, several joined with ", ", or the words typed."""
        given = self.inputs.get(request)
        question = self.requests.get(request) or self.question
        if given is None or not question:
            raise ValueError("that question is no longer waiting")
        picked = {q["question"]: ", ".join(a) for q, a in
                  zip(question["questions"], answers, strict=False) if a}  # fmt: skip
        self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": request,
            "response": {"behavior": "allow", "updatedInput": {**given, "answers": picked}}}})  # fmt: skip
        self.inputs.pop(request, None)
        self._answered(request)

    def _handshake(self, given: dict) -> None:
        self.mode = given.get("current_permission_mode") or self.mode
        self.models = claude_models(given)
        self.settings.update(plan=self.mode == "plan", auto=self.mode == "auto")
        if given.get("model"):
            self.settings["model"] = given["model"]

    def configure(self, changes: dict) -> None:
        """Effort only takes effect in a new process, so it restarts between turns; the
        model and permission mode change at once."""
        if self.busy and "effort" in changes and changes["effort"] != self.settings["effort"]:
            self.pending_settings.update(changes)
            return
        if "effort" in changes and changes["effort"] != self.settings["effort"]:
            if self.busy:
                raise ValueError("it is still working: change the effort once it stops")
            previous = dict(self.settings)
            self.settings["effort"] = changes["effort"]
            self.close(release=False)
            self.mode = "default"
            try:
                self._launch(again=True)
            except Exception:
                self.settings.update(previous)
                self.pending_settings.update(changes)
                raise
            self.pending_settings.update({key: previous[key] for key in ("plan", "auto")})
            if self.settings["model"]:  # what was chosen before carries over
                self._control("set_model", model=self.settings["model"])
        if "model" in changes and changes["model"] != self.settings["model"]:
            self._control(
                "set_model",
                model=changes["model"] or "default",
                changes={"model": changes["model"]},
            )
        self.pending_settings.update({k: changes[k] for k in ("plan", "auto") if k in changes})
        self._apply_mode()

    def set_goal(self, objective: str, budget: int | None, images=()) -> None:
        """Claude's own `/goal`: it keeps going until the condition holds."""
        self.send(f"/goal {objective}", images)
        self.goal = {"objective": objective, "status": "set", "tokens_used": None,
                     "token_budget": None, "seconds": None}  # fmt: skip

    def clear_goal(self) -> None:
        """Claude's `/goal clear`: a turn of its own when idle; mid-turn, written as it is,
        for Claude to take once the turn it is in ends, as it takes any queued message."""
        with self.lock:
            working = self.busy
        if working:
            self._write({"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "/goal clear"}]}})  # fmt: skip
        else:
            self.send("/goal clear")
        self.goal = None


def claude_models(given: dict) -> list[dict]:
    """The models Claude's `initialize` answer offers, each with its effort levels."""
    return [
        {"id": m.get("value"), "label": m.get("displayName") or m.get("value"),
         "description": m.get("description") or "", "default": m.get("value") == "default",
         "efforts": list(m.get("supportedEffortLevels") or []), "default_effort": None}
        for m in given.get("models") or [] if m.get("value")
    ]  # fmt: skip


def codex_models(listed: dict) -> list[dict]:
    """The models Codex's `model/list` offers, hidden ones left out."""
    return [
        {"id": m.get("model") or m.get("id"), "label": m.get("displayName") or m.get("model"),
         "description": m.get("description") or "", "default": bool(m.get("isDefault")),
         "efforts": [e.get("reasoningEffort") for e in m.get("supportedReasoningEfforts") or []],
         "default_effort": m.get("defaultReasoningEffort")}
        for m in listed.get("data") or [] if not m.get("hidden")
    ]  # fmt: skip


MODELS_TTL = 3600.0  # seconds a tool's model list is reused; asking costs a process start
_models: dict = {}


def claude_lister() -> list[str]:
    """Claude, asked only for what it offers: no session kept, and no user settings, so
    none of the user's hooks run."""
    return [shutil.which("claude") or "claude", "-p", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--setting-sources", "local"]  # fmt: skip


def _claude_offers(config, command: list[str], *, cwd: str | None = None) -> dict:
    """What Claude's start-up handshake offers (its models, its commands), asked in `cwd`
    or ax's own folder: no model call."""
    hello = json.dumps({"type": "control_request", "request_id": "init",
                        "request": {"subtype": "initialize"}})  # fmt: skip
    folder = cwd or (config.data if config.data.is_dir() else None)
    done = subprocess.run(command, input=hello + "\n", capture_output=True, text=True,
                          timeout=60, cwd=folder, env=job_wake.clean_env(os.environ))  # fmt: skip
    for line in done.stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        response = message.get("response") if isinstance(message, dict) else None
        if isinstance(response, dict) and response.get("request_id") == "init":
            return response.get("response") or {}
    raise ValueError("it gave no model list")


def available_models(config, *, claude=None, codex=None, fresh=False) -> dict:
    """The models each tool offers a new session, asked of each tool at most hourly; a
    tool that can't answer is named in `errors` and offers none."""
    found = _models.get("found")
    if found and not fresh and time.monotonic() - _models["at"] < MODELS_TTL:
        return found
    from ax import live_sessions

    found, errors = {"claude": [], "codex": []}, []
    try:
        found["claude"] = claude_models(_claude_offers(config, claude or claude_lister()))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        errors.append(f"claude: {exc}")
    try:
        server = live_sessions.AppServer(codex or live_sessions.codex_command(config)).start()
        try:
            found["codex"] = codex_models(server.request("model/list", {}) or {})
        finally:
            server.close()
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        errors.append(f"codex: {exc}")
    found["errors"] = errors
    if not errors:
        _models.update(found=found, at=time.monotonic())
    return found


# The transcript says what a tool did; an approval asks for what it would do.
_PRESENT = {"ran": "run", "edited": "edit", "wrote": "write", "searched": "search",
            "listed": "list", "started": "start", "fetched": "fetch", "used": "use",
            "called": "call"}  # fmt: skip


def _as_request(summary: str) -> str:
    first, _, rest = summary.partition(" ")
    return f"{_PRESENT.get(first, first)} {rest}".strip()


def claude_command(sid: str, new: bool = False, effort: str | None = None) -> list[str]:
    """Continue a session headlessly, or start one with this id when `new`, its tools
    asking here before they run, at the effort chosen for it."""
    return [
        shutil.which("claude") or "claude", "-p", "--input-format", "stream-json",
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--session-id" if new else "--resume", sid, "--permission-mode", "default",
        "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
        *(["--effort", effort] if effort else []),
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
        self.opening: dict[tuple[str, str], Future] = {}
        self.failures: dict[tuple[str, str], str] = {}

    def get(self, provider: str, sid: str) -> Driver | None:
        with self.lock:
            found = self.drivers.get((provider, sid))
            if found and not found.alive and not found.busy:
                reason = found.error or "the process ended"
                diagnostics = getattr(found, "diagnostics", "").strip()
                self.failures[(provider, sid)] = reason + (
                    "\n" + diagnostics if diagnostics and diagnostics not in reason else ""
                )
                return None
            return found

    def open(self, provider: str, sid: str, *, cwd=None, name=None, config=None) -> Driver:
        found = self.get(provider, sid)
        if found:
            return found
        key = (provider, sid)
        with self.lock:
            found = self.drivers.get(key)
            if found and found.alive:
                return found
            existing = self.opening.get(key)
            future = existing or Future()
            self.opening[key] = future
        if existing:
            return future.result()
        lease = None
        try:
            dead = self.drivers.get(key)
            if dead:
                dead.close()
            if config:
                folder = config.data / "chat-locks"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / hashlib.sha256(f"{provider}:{sid}".encode()).hexdigest()
                lease = path.open("a")
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError(
                        "Another ax server holds this session; use its server address"
                    ) from None
            if provider == "codex":
                driver: Driver = CodexDriver(sid, name, cwd, self.codex_command())
            else:
                driver = self._claude(sid, name, cwd, new=False)
            driver.lease = lease
            with self.lock:
                self.drivers[key] = driver
                self.failures.pop(key, None)
            future.set_result(driver)
            return driver
        except BaseException as exc:
            if lease:
                lease.close()
            self.failures[key] = str(exc)
            future.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.opening.pop(key, None)

    def _claude(self, sid: str, name, cwd, *, new: bool, effort=None) -> "ClaudeDriver":
        """A restart resumes the session, even one this driver began."""
        return ClaudeDriver(sid, name, cwd, lambda effort, again: self.claude_command(
            sid, new=new and not again, effort=effort), effort=effort)  # fmt: skip

    def start(
        self, provider: str, *, cwd: str, name: str | None, effort=None, config=None
    ) -> Driver:
        """A new session in `cwd`, held by ax from its first message; Claude's at the
        effort given, which only a new process takes."""
        if provider == "codex":
            driver: Driver = CodexDriver(None, name, cwd, self.codex_command())
        else:
            sid = str(uuid.uuid4())
            driver = self._claude(sid, name, cwd, new=True, effort=effort)
        try:
            if config:
                folder = config.data / "chat-locks"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / hashlib.sha256(f"{provider}:{driver.sid}".encode()).hexdigest()
                driver.lease = path.open("a")
                try:
                    fcntl.flock(driver.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError("Another ax server holds this session") from None
            with self.lock:
                self.drivers[(provider, driver.sid)] = driver
            return driver
        except BaseException:
            driver.close()
            raise

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


def hand_back(config, provider: str, sid: str, *, cwd=None, name=None) -> str:
    """Let go of a session ax holds. A Claude one joins the Claude app's sessions, to go on
    with it there (Codex's app lists every thread already). What happened, to say."""
    held = CHATS.get(provider, sid)
    where = cwd or (held.cwd if held else None)
    title = name or (held.name if held else None) or sid[:8]
    CHATS.release(provider, sid)
    if provider == "claude" and where:
        if claude_app.find(config, sid):
            return "Handed back: it's in the Claude app's sessions, to go on with it there."
        if claude_app.register(
            config, sid, cwd=where, title=title, settings=held.settings if held else None
        ):
            return ("Handed back, and in the Claude app's sessions: it shows there once the "
                    "app has restarted, to go on with it there.")  # fmt: skip
    return "Handed back: ax no longer holds it."


def hand_back_all(config) -> None:
    """Let go of every session ax holds, as when ax stops; each is handed back as by hand."""
    for provider, sid in list(CHATS.drivers):
        try:
            hand_back(config, provider, sid)
        except Exception:  # one that can't be added to the app is still let go
            CHATS.release(provider, sid)


_open: dict[str, tuple[float, set]] = {}
_lock = threading.Lock()


def _run(argv: list[str], env) -> tuple[int, str]:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=env)
    return done.returncode, (done.stdout + done.stderr)


def codex_open_in_app(config, tid: str) -> bool | None:
    lock = config.codex_home / "thread-writer-locks" / f"{tid}.lock"
    if not lock.exists():
        return False
    try:
        found = subprocess.run(
            ["lsof", "-t", str(lock)], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if found.returncode not in (0, 1):
        return None
    return bool(found.stdout.strip())


def _claude_agents() -> dict | None:
    """The Claude sessions a process runs, as `claude agents` lists them: each session's id
    with the processes running it (None for a background run). ax's own are among them."""
    now = time.monotonic()
    with _lock:
        cached = _open.get("claude")
    if cached is None or now - cached[0] > OPEN_TTL:
        found: dict = {}
        try:
            out = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True,
                                 timeout=30, check=True).stdout  # fmt: skip
            for row in json.loads(out or "[]"):
                if isinstance(row, dict) and row.get("sessionId"):
                    found.setdefault(row["sessionId"], set()).add(row.get("pid"))
        except (OSError, ValueError, subprocess.SubprocessError):
            found = None
        cached = (now, found)
        with _lock:
            _open["claude"] = cached
    return cached[1]


def claude_open_elsewhere(config, sid: str) -> bool | None:
    """Whether a Claude process (the desktop app, a terminal, a background run) holds it."""
    found = _claude_agents()
    return None if found is None else sid in found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _let_go_if_opened_elsewhere(config, provider: str, sid: str) -> bool:
    """Let go of a Claude session ax runs once a process it didn't start runs it too: the
    Claude app or a terminal has opened it, and two must never write to one session."""
    driver = CHATS.get(provider, sid)
    if provider != "claude" or driver is None:
        return False
    agents = _claude_agents()
    if agents is None:
        return False
    others = agents.get(sid, set()) - driver.pids
    if not any(pid is not None and _alive(pid) for pid in others):
        return False
    hand_back(config, provider, sid)
    return True


def yield_held(config) -> None:
    """Let go of every Claude session the app or a terminal has opened since ax took it."""
    for provider, sid in list(CHATS.drivers):
        _let_go_if_opened_elsewhere(config, provider, sid)


def _joined(config, provider: str, driver: "Driver") -> "Driver":
    """A Claude session ax opens or starts joins the Claude app's sessions at once, so the
    app can go on with it; Hand back adds one that missed it."""
    if provider == "claude" and driver.cwd and not driver.in_app and not driver.pending_settings:
        try:
            listed = claude_app.register(
                config, driver.sid, cwd=driver.cwd, title=driver.name, settings=driver.settings
            )
        except OSError as exc:
            listed = None
            driver.error = f"Desktop registration failed: {exc}"
        driver.in_app = bool(listed)
    return driver


def held() -> list[dict]:
    """The sessions ax holds open, for the Sessions list."""
    found = []
    for (provider, sid), driver in list(CHATS.drivers.items()):
        approval = driver.approval
        asking = driver.question
        state = "waiting" if approval or asking else ("working" if driver.busy else "idle")
        found.append({
            "provider": provider, "id": sid, "name": driver.name, "cwd": driver.cwd,
            "project": Path(driver.cwd).name if driver.cwd else None, "state": state,
            "waiting_for": "approval" if approval else "question" if asking else None,
            "kind": "ax (background)",
            "started": None, "updated": None, "last": None,
        })  # fmt: skip
    return found


_BACKGROUND = ("Running in the background through ax, so the Claude app doesn't show it. Hand "
               "it back to continue it elsewhere, such as `claude --resume {sid}` in a terminal.")  # fmt: skip
_IN_APP = ("Running in the background through ax, and in the Claude app's sessions too (the "
           "app lists new ones once it has restarted): open it there and ax lets go of it.")  # fmt: skip


def _held_note(provider: str, driver: "Driver") -> str:
    if provider == "codex":
        return ("ax holds this thread in the background: hand it back before opening it in "
                "the Codex app.")  # fmt: skip
    return _IN_APP if driver.in_app else _BACKGROUND.format(sid=driver.sid)


def state(config, provider: str, sid: str) -> dict:
    """Read runtime state. Reading a chat never acquires it or consumes messages."""
    pending = chat_store.messages(config, provider, sid)
    take_over = (provider, sid) in CHATS.pending
    error = CHATS.failures.get((provider, sid)) or chat_store.failure(config, provider, sid)
    base = {
        "holder": None,
        "can_send": True,
        "take_over": False,
        "pending": bool(pending) or take_over,
        "outbox": [
            {
                **{k: v for k, v in m.items() if k not in ("body", "images")},
                "attachments": len(m.get("images") or []),
            }
            for m in pending
        ],
        "queued": "\n\n".join(m.get("text", "") for m in pending),
        "busy": False,
        "partial": "",
        "approval": None,
        "question": None,
        "error": error,
        "note": "",
        "settings": None,
        "models": [],
        "goal": None,
        "tasks": None,
        "mid_turn": [],
        "requests": [],
        "ownership": "closed",
        "external_ownership": "closed",
        "ownership_certainty": "confirmed",
        "delivery": ["steer", "queue"],
        "delivery_paused": chat_store.metadata(config, provider, sid).get("delivery_paused", False),
        "api_version": 2,
        "capabilities": {
            "rename": True,
            "archive": True,
            "fork": True,
            "history": True,
            "restore": {
                "available": True,
                "coverage": "Provider file history only; missing checkpoints and shell edits are not recoverable.",
            },
            "compact": {
                "available": True,
                "via": "app-server" if provider == "codex" else "native /compact command",
            },
            "review": {
                "available": provider == "codex",
                "handoff": "Use ax change review and send feedback to the chat."
                if provider == "claude"
                else None,
            },
            "elicitation": {
                "available": provider == "codex",
                "handoff": "Complete MCP elicitation in the provider client when it does not expose a request to ax.",
            },
        },
        "receipts": chat_store.receipts(config, provider, sid),
    }
    driver = CHATS.get(provider, sid)
    if driver:
        return {
            **base,
            **driver.view(),
            "holder": "ax",
            "ownership": "ax",
            "note": _held_note(provider, driver),
        }
    # get() records a newly ended driver's failure without throwing its evidence away.
    base["error"] = CHATS.failures.get((provider, sid)) or error
    if base["error"]:
        chat_store.failure(config, provider, sid, base["error"])
        base["diagnostics"] = base["error"]
        base["error"] = base["error"].splitlines()[0]
    base["external_ownership"] = base["ownership"]
    if provider == "codex":
        opened = codex_open_in_app(config, sid)
        if opened is None:
            return {
                **base,
                "ownership": "unknown",
                "external_ownership": "unknown",
                "ownership_certainty": "unknown",
                "can_send": False,
                "note": "Codex ownership could not be checked. Retry before continuing here.",
            }
        if opened:
            return {
                **base,
                "holder": "codex app",
                "ownership": "open",
                "external_ownership": "open",
                "delivery": ["queue"],
                "note": "Open in Codex: messages queue for its next turn. Steer there, or hand it back to ax.",
            }
    else:
        opened = claude_open_elsewhere(config, sid)
        if opened is None:
            return {
                **base,
                "ownership": "unknown",
                "external_ownership": "unknown",
                "ownership_certainty": "unknown",
                "can_send": False,
                "note": "Claude ownership could not be checked. Retry before continuing here.",
            }
        if opened:
            return {
                **base,
                "holder": "elsewhere",
                "ownership": "open",
                "external_ownership": "open",
                "take_over": True,
                "delivery": ["queue"],
                "note": "Queued messages wait until you close this session in Claude or its terminal.",
            }
    return {**base, "note": "Your message continues this session through ax."}


def _changes(payload: dict) -> dict:
    """The modes a request changes, checked for their kind."""
    found = {k: payload[k] for k in ("plan", "auto", "model", "effort") if k in payload}
    if not found:
        raise ValueError("nothing to change: say plan, auto, model or effort")
    for key in ("plan", "auto"):
        if key in found and not isinstance(found[key], bool):
            raise ValueError(f"{key} is true or false")
    for key in ("model", "effort"):
        if (
            key in found
            and found[key] is not None
            and (not isinstance(found[key], str) or not found[key].strip())
        ):
            raise ValueError(f"say which {key}")
    return found


def _answers(payload: dict) -> list[list[str]]:
    """The answers to a question, one list per question, checked."""
    given = payload.get("answers")
    if not isinstance(given, list) or not all(
        isinstance(a, list) and all(isinstance(x, str) for x in a) for a in given
    ):
        raise ValueError("answers are a list of answers for each question")
    if not any(any(x.strip() for x in a) for a in given):
        raise ValueError("there is no answer to send")
    return [[x.strip() for x in a if x.strip()] for a in given]


def _answer_question(config, provider, sid, payload, cwd, name) -> dict:
    """A question ax holds the session for, or a Codex async one by its reply message."""
    answers = _answers(payload)
    driver = CHATS.get(provider, sid)
    request = payload.get("request")
    if driver and (
        request in driver.requests or (driver.question and driver.question["id"] == request)
    ):
        driver.answer_question(str(request), answers)
        return {"ok": True, "message": "Answered."}
    if provider == "codex" and payload.get("via") == "codex-async":
        call, questions = payload.get("call"), payload.get("questions")
        if not isinstance(call, str) or not isinstance(questions, list):
            raise ValueError("say which question: its call and its questions")
        text = asks.reply_message(call, [str(q) for q in questions], answers)
        return _send(config, provider, sid, text, cwd, name)
    raise ValueError("ax can't reach that question: answer it where the session is open")


def _hold(config, provider: str, sid: str, cwd=None, name=None) -> Driver:
    """The driver for a session whose modes are changing: one ax holds, or opens now."""
    _let_go_if_opened_elsewhere(config, provider, sid)
    driver = CHATS.get(provider, sid)
    if driver:
        return driver
    if provider == "codex" and codex_open_in_app(config, sid) is not False:
        raise ValueError("it's open in the Codex app: set its modes there")
    if provider == "claude" and claude_open_elsewhere(config, sid) is not False:
        raise ValueError("Claude ownership is open or unknown: check it before taking over")
    return _joined(config, provider, CHATS.open(provider, sid, cwd=cwd, name=name, config=config))


def _configure(driver: Driver, changes: dict) -> None:
    """Validate the whole model/effort pair, including resets to the provider default."""
    changes = dict(changes)
    if changes.get("model") and driver.models and driver.model(changes["model"]) is None:
        raise ValueError(f"no model {changes['model']} here")
    model = driver.model(changes.get("model"))
    if "model" in changes and "effort" not in changes:
        changes["effort"] = None
    if (
        changes.get("effort") is not None
        and model
        and model["efforts"]
        and changes["effort"] not in model["efforts"]
    ):
        raise ValueError(f"{model['id']} has no effort {changes['effort']}")
    driver.configure(changes)


def act(config, payload: dict) -> dict:
    """Send, answer an approval, stop, take over or hand back; a ValueError says why not.
    A shared link acts at once, as this Mac does: its token is the only gate."""
    action, provider, sid = payload.get("action"), payload.get("provider"), payload.get("id")
    if provider not in ("claude", "codex"):
        raise ValueError("say which tool: provider is claude or codex")
    if action != "start" and (not isinstance(sid, str) or not sid):
        raise ValueError("say which session: its id")
    folder = _folder(payload.get("cwd")) if action == "start" else None
    images = _images(payload) if action in ("send", "start") else []
    if action in ("send", "start") and not str(payload.get("text") or "").strip() and not images:
        raise ValueError("there is nothing to send: no text and no image")
    changes = _changes(payload) if action == "settings" else {}
    objective = str(payload.get("objective") or "").strip()
    if action == "goal" and not objective:
        raise ValueError("say what the goal is")
    if action == "answer-question":
        _answers(payload)
    cwd, name = payload.get("cwd"), payload.get("name")
    from ax import session_ops

    if action in session_ops.OPERATIONS:
        return session_ops.act(config, payload)
    if action == "start":
        model = str(payload.get("model") or "").strip() or None
        effort = str(payload.get("effort") or "").strip() or None
        modes = {key: payload.get(key) is True for key in ("plan", "auto")}
        return _start(config, provider, folder, str(payload.get("text") or "").strip(), name,
                      images, model, effort, modes, payload.get("goal") is True, message_id=payload.get("client_message_id"))  # fmt: skip
    if action == "review-feedback":
        from ax import session_changes

        comments = payload.get("review_comments") or []
        if not comments:
            raise ValueError("Write a review comment first")
        parts = []
        for comment in comments:
            path = comment.get("path")
            if not isinstance(path, str):
                raise ValueError("Each comment needs a file")
            current = session_changes._on_disk(path)
            revision = (
                hashlib.sha256(current.encode()).hexdigest() if current is not None else "absent"
            )
            if revision != comment.get("revision"):
                raise ValueError(f"{path} changed since review; refresh the diff before sending")
            parts.append(f"{path} ({comment.get('hunk', 'file')}): {comment.get('text', '')}")
        return _send(
            config,
            provider,
            sid,
            "Review feedback:\n\n" + "\n\n".join(parts),
            cwd,
            name,
            message_id=payload.get("client_message_id"),
        )
    if action == "retry":
        _hold(config, provider, sid, cwd, name)
        chat_store.failure(config, provider, sid, clear=True)
        return {"ok": True, "message": "Connected."}
    if action == "send":
        text = str(payload.get("text") or "").strip()
        return _send(
            config,
            provider,
            sid,
            text,
            cwd,
            name,
            images,
            delivery=payload.get("delivery", "steer"),
            message_id=payload.get("client_message_id"),
        )
    if action in ("pending-edit", "pending-cancel", "pending-retry"):
        if action == "pending-retry":
            chat_store.metadata(config, provider, sid, {"delivery_paused": False})
        chat_store.change(
            config,
            provider,
            sid,
            str(payload.get("message_id")),
            action.removeprefix("pending-"),
            payload.get("text"),
        )
        return {"ok": True, "message": "Pending message updated."}
    if action == "answer":
        driver = CHATS.get(provider, sid)
        if driver is None:
            raise ValueError("ax isn't holding that session")
        said = str(payload.get("message") or "").strip() or None
        driver.answer(
            str(payload.get("request")),
            bool(payload.get("allow")),
            said,
            response=payload.get("response"),
        )
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
        if claude_open_elsewhere(config, sid) is None:
            raise ValueError("Claude ownership is unknown; retry the inventory first")
        if claude_open_elsewhere(config, sid):
            CHATS.pending[(provider, sid)] = {"cwd": cwd, "name": name}
            return {"ok": True, "waiting": True, "message": (
                "Close it in the Claude app (it stays on disk). ax continues it here, in the "
                "background, as soon as it's closed.")}  # fmt: skip
        driver = _joined(
            config, provider, CHATS.open(provider, sid, cwd=cwd, name=name, config=config)
        )
        return {"ok": True, "waiting": False, "message": _held_note(provider, driver)}
    if action == "release":
        chat_store.metadata(config, provider, sid, {"delivery_paused": True})
        return {"ok": True, "message": hand_back(config, provider, sid, cwd=cwd, name=name)}
    if action == "open":
        _hold(config, provider, sid, cwd, name)
        return {"ok": True, "message": "ax holds it now."}
    if action == "settings":
        driver = _hold(config, provider, sid, cwd, name)
        _configure(driver, changes)
        return {"ok": True, "settings": dict(driver.settings), "message": "Changed."}
    if action == "goal":
        budget = payload.get("budget")
        if budget is not None and (not isinstance(budget, int) or budget <= 0):
            raise ValueError("a budget is a whole number of tokens")
        _hold(config, provider, sid, cwd, name).set_goal(objective, budget)
        return {"ok": True, "message": "Goal set."}
    if action == "answer-question":
        return _answer_question(config, provider, sid, payload, cwd, name)
    if action == "goal-clear":
        driver = CHATS.get(provider, sid)
        if driver is None:
            raise ValueError("ax isn't holding that session")
        driver.clear_goal()
        return {"ok": True, "message": "Goal cleared."}
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


def _start(config, provider: str, folder: str, text: str, name, images, model=None,
           effort=None, modes=None, goal=False, message_id=None) -> dict:  # fmt: skip
    """A new session in `folder`, held by ax, on the model, effort and modes (plan mode,
    approve for me) chosen for it, its first message sent, or set as its goal."""
    key = chat_store.client_id(message_id)
    signature = hashlib.sha256(
        json.dumps(
            {
                "provider": provider,
                "folder": folder,
                "text": text,
                "model": model,
                "effort": effort,
                "modes": modes,
                "goal": goal,
                "images": [{k: v for k, v in i.items() if k != "bytes"} for i in images],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    existing = chat_store.begin_start(config, provider, key, signature)
    if existing:
        return {
            "ok": True,
            "provider": provider,
            "id": existing,
            "message": "This draft already started that chat.",
        }
    title = name or first_line(text, 60) or "New session"
    driver = None
    try:
        driver = CHATS.start(
            provider,
            cwd=folder,
            name=title,
            effort=effort if provider == "claude" else None,
            config=config,
        )
        chosen = {key: value for key, value in (("model", model), ("effort", effort)) if value}
        chosen.update({key: True for key, on in (modes or {}).items() if on})
        if chosen:
            _configure(driver, chosen)
        driver.initial_settings_key = key
        _joined(config, provider, driver)
        body = {
            "text": text,
            "cwd": folder,
            "name": title,
            "delivery": "steer",
            "goal": goal,
            "settings": chosen,
            "images": [{k: v for k, v in i.items() if k != "bytes"} for i in images],
        }
        chat_store.finish_start(config, provider, key, driver.sid, body)
    except Exception:
        if driver:
            CHATS.release(provider, driver.sid)
        chat_store.fail_start(config, provider, key)
        raise
    dispatch_pending(config, provider, driver.sid)
    return {
        "ok": True,
        "provider": provider,
        "id": driver.sid,
        "message": "Started through ax; the initial message is kept in its outbox until accepted.",
    }


def _deliver(config, provider: str, sid: str, text: str, cwd, name, images=()) -> dict:
    _let_go_if_opened_elsewhere(config, provider, sid)  # never write beside the app
    driver = CHATS.get(provider, sid)
    if images and "bytes" not in images[0] and "data" in images[0]:
        images = _images({"images": list(images)})
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
    if driver is None and provider == "claude" and claude_open_elsewhere(config, sid) is not False:
        raise ValueError("Claude is open elsewhere or its ownership is unknown")
    if driver is None:
        driver = _joined(
            config, provider, CHATS.open(provider, sid, cwd=cwd, name=name, config=config)
        )
    driver.send(text, images)
    return {"ok": True, "via": "ax", "message": "Sent."}


_dispatch = threading.Lock()


def _send(config, provider, sid, text, cwd, name, images=(), *, delivery="steer", message_id=None):
    if delivery not in ("steer", "queue"):
        raise ValueError("delivery is steer or queue")
    body = {
        "text": text,
        "cwd": cwd,
        "name": name,
        "images": [{k: v for k, v in i.items() if k != "bytes"} for i in images],
        "delivery": delivery,
    }
    chat_store.metadata(config, provider, sid, {"delivery_paused": False})
    key = chat_store.enqueue(config, provider, sid, body, message_id)
    dispatch_pending(config, provider, sid)
    found = next(
        m for m in chat_store.messages(config, provider, sid, all_statuses=True) if m["id"] == key
    )
    return {
        "ok": True,
        "message_id": key,
        "status": found["status"],
        "via": "codex app" if provider == "codex" and CHATS.get(provider, sid) is None else "ax",
        "waiting": found["status"] != "sent",
        "message": "Sent."
        if found["status"] == "sent"
        else "Kept in your outbox; if open in Claude, it continues as soon as it's closed.",
    }


def dispatch_pending(config, provider=None, sid=None):
    """A single dispatcher claims messages; reads of session state never dispatch."""
    if not _dispatch.acquire(blocking=False):
        return
    try:
        for (tool, session), pending in list(CHATS.pending.items()):
            if tool == "claude" and claude_open_elsewhere(config, session) is False:
                try:
                    _joined(
                        config,
                        tool,
                        CHATS.open(
                            tool,
                            session,
                            cwd=pending.get("cwd"),
                            name=pending.get("name"),
                            config=config,
                        ),
                    )
                except Exception as exc:
                    chat_store.failure(config, tool, session, str(exc))
                else:
                    CHATS.pending.pop((tool, session), None)
        with chat_store.connect(config) as db:
            keys = [
                (r[0], r[1])
                for r in db.execute(
                    "SELECT DISTINCT provider,sid FROM outbox WHERE status='queued'"
                )
            ]
        for tool, session in keys:
            if chat_store.metadata(config, tool, session).get("delivery_paused"):
                continue
            if (
                tool == "codex"
                and CHATS.get(tool, session) is None
                and codex_open_in_app(config, session) is None
            ):
                continue
            if provider is not None and (tool, session) != (provider, sid):
                continue
            if (
                tool == "claude"
                and CHATS.get(tool, session) is None
                and claude_open_elsewhere(config, session) is not False
            ):
                continue
            for message in chat_store.messages(config, tool, session):
                if message["status"] != "queued":
                    break
                driver = CHATS.get(tool, session)
                if driver and driver.busy and message["delivery"] == "queue":
                    break
                if not chat_store.claim(config, tool, session, message["id"]):
                    continue
                # Initialization fails before any input can reach a provider.
                try:
                    if driver is None and not (
                        tool == "codex" and codex_open_in_app(config, session)
                    ):
                        driver = _joined(
                            config,
                            tool,
                            CHATS.open(
                                tool,
                                session,
                                cwd=message.get("cwd"),
                                name=message.get("name"),
                                config=config,
                            ),
                        )
                    if (
                        message.get("settings")
                        and getattr(driver, "initial_settings_key", None) != message["id"]
                    ):
                        _configure(driver, message["settings"])
                        driver.initial_settings_key = message["id"]
                    if (
                        isinstance(driver, ClaudeDriver)
                        and driver.pending_settings
                        and not driver.busy
                    ):
                        driver.configure(dict(driver.pending_settings))
                except Exception as exc:
                    chat_store.settle(config, tool, session, message["id"], "failed", str(exc))
                    chat_store.failure(config, tool, session, str(exc))
                    break
                try:
                    if message.get("goal"):
                        pictures = _images({"images": message.get("images") or []})
                        if tool == "codex":
                            pictures = _saved(config, pictures)
                        driver.set_goal(message.get("text", ""), None, pictures)
                    else:
                        _deliver(
                            config,
                            tool,
                            session,
                            message.get("text", ""),
                            message.get("cwd"),
                            message.get("name"),
                            message.get("images") or [],
                        )
                except Exception as exc:
                    chat_store.settle(config, tool, session, message["id"], "uncertain", str(exc))
                    break
                chat_store.settle(config, tool, session, message["id"], "sent")
                chat_store.failure(config, tool, session, clear=True)
    finally:
        _dispatch.release()


def maintain(config, stop):
    # A previous server may have died after writing input but before recording its ack.
    chat_store.recover(config)
    while not stop.wait(1):
        try:
            yield_held(config)
            for driver in list(CHATS.drivers.values()):
                if (
                    driver.provider == "claude"
                    and not driver.in_app
                    and not driver.pending_settings
                ):
                    _joined(config, "claude", driver)
                if (
                    isinstance(driver, ClaudeDriver)
                    and not driver.busy
                    and "effort" in driver.pending_settings
                    and not driver.controls
                ):
                    driver.configure(dict(driver.pending_settings))
            dispatch_pending(config)
        except Exception:
            continue  # each message retains its own failure; the next inventory can recover

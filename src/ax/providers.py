"""Two fixed inexpensive runners and delivery to the original native conversation."""

import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from ax.db import connect, event
from ax.redact import redact

MODELS = {"claude": "haiku", "codex": "gpt-6-luna"}
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "concern": {"type": "boolean"},
        "assessment": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["concern", "assessment", "evidence"],
    "additionalProperties": False,
}
HANDOFF_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def infer_provider(caller):
    if not isinstance(caller, str) or not re.fullmatch(r"(claude|codex):[A-Za-z0-9._-]+", caller):
        raise ValueError("run from Claude/Codex, or supply --caller PROVIDER:SESSION")
    return caller.split(":", 1)[0]


def caller_context(explicit=None):
    if explicit:
        caller = explicit
    elif os.environ.get("CLAUDE_CODE_SESSION_ID") and os.environ.get("CODEX_THREAD_ID"):
        raise ValueError("ambiguous caller environment; supply --caller PROVIDER:SESSION")
    elif os.environ.get("CLAUDE_CODE_SESSION_ID"):
        caller = "claude:" + os.environ["CLAUDE_CODE_SESSION_ID"]
    elif os.environ.get("CODEX_THREAD_ID"):
        caller = "codex:" + os.environ["CODEX_THREAD_ID"]
    else:
        caller = os.environ.get("AX_CALLER")
    infer_provider(caller)
    result = {"caller": caller}
    if caller == "claude:" + os.environ.get("CLAUDE_CODE_SESSION_ID", ""):
        result["inbox"] = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET")
        result["inbox_token"] = os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN")
    return result


def clean_env():
    env = dict(os.environ)
    for key in (
        "CODEX_THREAD_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "AX_CALLER",
    ):
        env.pop(key, None)
    return env


def execute(command, prompt, cwd, timeout=90):
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=clean_env(),
        start_new_session=True,
    )
    try:
        out, err = process.communicate(prompt, timeout=timeout)
        if process.returncode:
            raise RuntimeError(redact((err or out)[-1500:]) or "provider call failed")
        return out
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def model_call(config, provider, prompt, purpose):
    model = MODELS[provider]
    binary = shutil.which(provider)
    if not binary:
        raise RuntimeError(f"{provider} CLI is unavailable")
    schema = REVIEW_SCHEMA if purpose == "supervision" else HANDOFF_SCHEMA
    started = time.time()
    usage = {}
    cost = None
    state = "failed"
    try:
        with tempfile.TemporaryDirectory(prefix="review-", dir=config.data) as folder:
            path = Path(folder)
            schema_path, output_path = path / "schema.json", path / "result.json"
            schema_path.write_text(json.dumps(schema))
            if provider == "claude":
                command = [
                    binary,
                    "-p",
                    "--model",
                    model,
                    "--effort",
                    "low",
                    "--tools",
                    "",
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                    "--disable-slash-commands",
                    "--no-session-persistence",
                    "--output-format",
                    "json",
                    "--max-budget-usd",
                    "0.15",
                    "--json-schema",
                    json.dumps(schema),
                ]
                response = json.loads(execute(command, prompt, folder))
                usage, cost = response.get("usage", {}), response.get("total_cost_usd")
                if response.get("is_error"):
                    raise RuntimeError("Claude returned an unsuccessful model result")
                result = response.get("structured_output")
                if not isinstance(result, dict):
                    result = json.loads(response.get("result", "{}"))
            else:
                command = [
                    binary,
                    "exec",
                    "-m",
                    model,
                    "-c",
                    'model_reasoning_effort="low"',
                    "--sandbox",
                    "read-only",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "--ignore-user-config",
                    "--disable",
                    "shell_tool",
                    "--disable",
                    "multi_agent",
                    "--disable",
                    "apps",
                    "--disable",
                    "plugins",
                    "--disable",
                    "hooks",
                    "--json",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                    "-",
                ]
                raw = execute(command, prompt, folder)
                for line in raw.splitlines():
                    with contextlib.suppress(ValueError):
                        item = json.loads(line)
                        if item.get("type") == "turn.completed":
                            usage = item.get("usage", {})
                result = json.loads(output_path.read_text())
            if not isinstance(result, dict):
                raise ValueError("provider returned no structured result")
            if purpose == "supervision":
                if (
                    type(result.get("concern")) is not bool
                    or not isinstance(result.get("assessment"), str)
                    or not isinstance(result.get("evidence"), list)
                    or any(not isinstance(x, str) for x in result["evidence"])
                ):
                    raise ValueError("invalid supervision result")
            elif not isinstance(result.get("summary"), str):
                raise ValueError("invalid handoff result")
            state = "completed"
            return {**result, "reviewer": model, "usage": usage, "cost_usd": cost}
    finally:
        with connect(config) as db:
            event(
                db,
                None,
                "model_call",
                {
                    "provider": provider,
                    "model": model,
                    "purpose": purpose,
                    "started": started,
                    "seconds": time.time() - started,
                    "status": state,
                    "usage": usage,
                    "cost_usd": cost,
                },
            )


class Unavailable(RuntimeError):
    """Delivery has not started; a later retry is safe."""


def deliver(task, text):
    provider, sid = task["owner"].split(":", 1)
    if provider == "claude":
        path, token = task.get("inbox"), task.get("inbox_token")
        if not path or not token or not Path(path).is_socket():
            raise Unavailable(
                "Claude caller inbox is unavailable; run an ax command in that session to rebind"
            )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            try:
                sock.connect(path)
            except OSError as exc:
                raise Unavailable(str(exc)) from exc
            lines = [
                {"type": "auth", "token": token},
                {"type": "user", "message": {"role": "user", "content": text}},
            ]
            sock.sendall("".join(json.dumps(x) + "\n" for x in lines).encode())
            sock.shutdown(socket.SHUT_WR)
            sock.recv(1)
    else:
        binary = shutil.which("codex")
        if not binary:
            raise Unavailable("Codex CLI is unavailable")
        result = subprocess.run(
            [binary, "queue", "--thread", sid, "--message", text, "--resume"],
            capture_output=True,
            text=True,
            timeout=15,
            env=clean_env(),
        )
        if result.returncode:
            raise RuntimeError(
                redact(result.stderr[-1000:]) or "Codex queue did not acknowledge delivery"
            )


def escalate(config, task, assessment, evidence):
    eid = str(uuid.uuid4())
    text = redact(
        f"[ax task {task['id']}; escalation {eid}]\n"
        f"Purpose: {task['purpose']}\nConcern: {assessment}\nEvidence: "
        + "; ".join(evidence)
        + "\nInspect the task and decide the next action. This is a supervision report, not user approval."
    )
    with connect(config) as db:
        db.execute(
            "INSERT INTO escalations(id,task,text,status,next_attempt) VALUES(?,?,?,'pending',?)",
            (eid, task["id"], text, time.time()),
        )
        event(
            db,
            task["id"],
            "attention_required",
            {"assessment": assessment, "evidence": evidence, "escalation": eid},
        )
    return eid


def flush_escalations(config):
    with connect(config) as db:
        rows = db.execute(
            "SELECT * FROM escalations WHERE status='pending' AND next_attempt<=?", (time.time(),)
        ).fetchall()
    for row in rows:
        with connect(config) as db:
            claimed = db.execute(
                "UPDATE escalations SET status='dispatching' WHERE id=? AND status='pending'",
                (row["id"],),
            ).rowcount
            if not claimed:
                continue
            task = dict(db.execute("SELECT * FROM tasks WHERE id=?", (row["task"],)).fetchone())
        status, error = "accepted", None
        try:
            deliver(task, row["text"])
        except Unavailable as exc:
            status, error = "pending", str(exc)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            status, error = "uncertain", str(exc)
        with connect(config) as db:
            db.execute(
                "UPDATE escalations SET status=?,error=?,attempts=attempts+1,next_attempt=? WHERE id=?",
                (status, error, time.time() + 60, row["id"]),
            )
            if status != "pending" or row["attempts"] == 0:
                event(
                    db,
                    row["task"],
                    "escalation_delivery",
                    {"id": row["id"], "status": status, "error": error},
                )

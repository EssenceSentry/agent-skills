"""Wake the agent session that registered a job, with a short note on how it ended.

The note goes in as a new turn of that session:
- Codex, thread open in the app: `codex queue --thread <thread> --message <note>`.
  An open thread has one writer, the app, so `codex exec resume` is refused ("already
  has an active writer"); the queue hands the note to the app, which delivers it as
  the thread's next turn. A thread is open when a process holds its lock file under
  ~/.codex/thread-writer-locks; a refused resume falls back to the queue as well.
- Codex, thread closed: `codex exec resume <thread> <note>` runs one turn without a
  terminal, in the folder the job was registered from.
- Claude Code, session open: the note goes to the session's inbox, the socket Claude
  Code opens for messages from other sessions; it arrives as one, during or between
  turns. Claude Code hands each process a session starts the socket and its token
  (CLAUDE_CODE_MESSAGING_SOCKET, _TOKEN) to message it back; ax's follower starts from
  the agent's shell, so it holds them. A process that doesn't, such as a follower the
  background service restarted, can't reach the inbox, and the wake fails so the user
  gets a push. It never resumes an open session: Claude Code would start a copy of it
  that works on its own, beside the session, on the same files.
- Claude Code, session closed: `claude --bg --resume <session> <note>` continues it in
  the background. Should the session turn out open after all, Claude Code starts a
  copy and says so; the wake reports it so the user can be told where the turn went.
"""

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
from pathlib import Path

from ax import jobs

AGENTS = ("claude", "codex")
_SESSION = {"claude": "claude_session", "codex": "codex_thread"}
# Variables that tie a process to the session that started it: its ids, its messaging
# socket and token, and what the desktop app or SDK set up for that one session. A
# woken agent must start as a session of its own. This is a list, not a prefix:
# credentials and settings a user exports (CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CODE_USE_*,
# CLAUDE_CODE_SKIP_*_AUTH, CLAUDE_CODE_MAX_OUTPUT_TOKENS) share the prefix and must
# survive.
_SESSION_NAMES = {
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CODEX_THREAD_ID", "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED", "AX_JOB_FILE",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SIMPLE",
    "CLAUDE_CODE_DESKTOP_APP_VERSION", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH",
    "CLAUDE_CODE_OAUTH_SCOPES", "CLAUDE_CODE_ACCOUNT_UUID", "CLAUDE_CODE_ORGANIZATION_UUID",
    "CLAUDE_CODE_USER_EMAIL", "CLAUDE_CODE_TERMINAL_MCP_TOOLS", "CLAUDE_CODE_REPORT_FINDINGS",
    "CLAUDE_CODE_STARTUP_FAILURE_RESULTS", "CLAUDE_CODE_DISABLE_CRON",
    "CLAUDE_CODE_DISABLE_TERMINAL_TITLE", "CLAUDE_CODE_EAGER_FLUSH",
    "CLAUDE_CODE_EMIT_STARTUP_TIMING", "CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES",
    "CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL", "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING",
}  # fmt: skip
_SESSION_PREFIXES = ("CLAUDE_AGENT_SDK_", "CLAUDE_PREVIEW_")
# What a Claude session or Codex thread id looks like; anything else, such as a value
# starting with "-", could be read as a flag of the resumed command.
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class WakeError(RuntimeError):
    pass


def _diagnosis(config, job) -> str | None:
    found = [
        e for e in jobs.events(config, job.key, latest=True, limit=50) if e["type"] == "diagnosis"
    ]
    return found[-1]["data"].get("text") if found else None


def packet(config, job, note: str | None = None) -> str:
    """The note the woken agent reads: what happened and where to look, in a few lines.
    `note` says what a health check found in a job that is still running. Its
    description then reads as what the job does, not as what to do now: the next steps
    it names wait for the job to end."""
    if note:
        lines = [f"[ax job] {note}"]
        if job.label:
            lines.append(f"What it does, and what follows once it ends: {job.label}")
    else:
        lines = [f"[ax job] {job.key} {job.status}" + (f": {job.message}" if job.message else "")]
        lines.append(
            job.label or "(no description: add one with `ax job describe KEY --label ...`)"
        )
    diagnosis = None if note else _diagnosis(config, job)
    if diagnosis:
        lines.append(f"Diagnosis: {diagnosis}")
    if job.done is not None or job.total is not None:
        lines.append(f"progress: {jobs.progress_text(job)}")
    if job.stage:
        lines.append(f"last stage: {job.stage}")
    if job.check_error:
        lines.append(f"last check error: {job.check_error}")
    folder = jobs.events_path(config, job.key).parent
    if (folder / "output.log").exists():
        lines.append(f"output: {folder / 'output.log'}")
    if note:
        lines.append(
            f"Details: ax job show {job.key}. This is an automatic notice from a job you "
            "registered. It has not finished, so don't start what follows it: decide "
            "whether to keep waiting or stop it, and tell the user if they should know."
        )
    else:
        lines.append(
            f"Details: ax job show {job.key}. This is an automatic notice from the job you "
            "registered; carry on with whatever was waiting on it."
        )
    return "\n".join(lines)


def choose(job, agent: str = "auto") -> tuple[str, str]:
    """The agent to wake and its session id."""
    if agent == "auto":
        found = [name for name in AGENTS if job.agent.get(_SESSION[name])]
        if not found:
            raise WakeError(
                f"{job.key} records no agent session; register it from Claude Code or Codex"
            )
        agent = "codex" if "codex" in found else found[0]
    if agent not in AGENTS:
        raise WakeError(f"unknown agent {agent!r}; choose auto, claude or codex")
    session = job.agent.get(_SESSION[agent])
    if not session:
        raise WakeError(f"{job.key} records no {agent} session")
    if not isinstance(session, str) or not _SESSION_ID.fullmatch(session):
        raise WakeError(f"{job.key} records a {agent} session id that doesn't look like one")
    return agent, session


def command(agent: str, session: str, note: str, binary: str, *, queue: bool = False) -> list[str]:
    if agent == "codex" and queue:
        return [binary, "queue", "--thread", session, "--message", note]
    if agent == "codex":
        return [binary, "exec", "resume", "--skip-git-repo-check", session, note]
    return [binary, "--bg", "--resume", session, note]


def codex_held(config, thread: str) -> bool:
    """Whether a running process (the Codex app) holds the thread open."""
    lock = config.codex_home / "thread-writer-locks" / f"{thread}.lock"
    if not lock.exists():
        return False
    try:
        found = subprocess.run(
            ["lsof", "-t", str(lock)], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(found.stdout.strip())


def _inbox(job, environ) -> tuple[str, str] | None:
    """The inbox socket and token of the job's Claude session, when this process
    descends from that session."""
    session = job.agent.get(_SESSION["claude"])
    path = environ.get("CLAUDE_CODE_MESSAGING_SOCKET")
    token = environ.get("CLAUDE_CODE_MESSAGING_TOKEN")
    if session and path and token and environ.get("CLAUDE_CODE_SESSION_ID") == session:
        return path, token
    return None


def deliver(path: str, token: str, note: str, *, timeout: float = 5.0) -> None:
    """Hand the note to a Claude session's inbox, in the form Claude Code documents for
    the processes it starts. Raises OSError when the session isn't listening."""
    lines = [{"type": "auth", "token": token},
             {"type": "user", "message": {"role": "user", "content": note}}]  # fmt: skip
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall("".join(json.dumps(line) + "\n" for line in lines).encode())
        sock.shutdown(socket.SHUT_WR)
        sock.recv(1)  # the session closes the connection once it has read the lines


def open_sessions(binary: str) -> set[str] | None:
    """The Claude sessions open now, interactive or background; None when unknown."""
    try:
        done = subprocess.run([binary, "agents", "--json"], capture_output=True, text=True,
                              timeout=30)  # fmt: skip
        return {s["sessionId"] for s in json.loads(done.stdout) if s.get("sessionId")}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
        return None


def _run_now(argv, *, cwd, env) -> tuple[int, str]:
    done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def clean_env(environ) -> dict:
    return {
        name: value
        for name, value in environ.items()
        if name not in _SESSION_NAMES and not name.startswith(_SESSION_PREFIXES)
    }


def _spawn(argv, *, cwd, log, env) -> subprocess.Popen:
    with open(log, "ab") as out:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _last_line(log: str, offset: int = 0) -> str:
    """The last line this launch wrote: wake.log is shared by every wake of the job."""
    try:
        with open(log, "rb") as f:
            f.seek(offset)
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def plan(
    config, job, agent: str = "auto", *, which=shutil.which, require=True, note=None, held=None
) -> dict:
    """What waking would run, without running it: the queue for a Codex thread the app
    holds open, else a resume."""
    agent, session = choose(job, agent)
    binary = which(agent)
    if not binary and require:
        raise WakeError(f"{agent} is not on PATH, so its session can't be resumed")
    binary = binary or agent
    held = held or (lambda thread: codex_held(config, thread))
    queue = agent == "codex" and held(session)
    argv = command(agent, session, packet(config, job, note), binary, queue=queue)
    cwd = job.cwd if job.cwd and os.path.isdir(job.cwd) else None
    log = jobs.events_path(config, job.key).parent / "wake.log"
    return {"agent": agent, "session": session, "argv": argv, "cwd": cwd, "log": str(log),
            "via": "queue" if queue else "resume"}  # fmt: skip


def wake(
    config,
    job,
    agent: str = "auto",
    *,
    spawn=_spawn,
    run=_run_now,
    which=shutil.which,
    held=None,
    environ=None,
    settle: float = 5.0,
    note: str | None = None,
    send=deliver,
    listed=open_sessions,
) -> dict:
    """Deliver the note to the agent's conversation and record how it went on the job.

    A refusal comes back within a second or two (an untrusted folder, an unknown
    session, a thread another process writes), so a background launch is given
    `settle` seconds to fail before it counts.
    """
    found = plan(config, job, agent, which=which, note=note, held=held)
    agent = found["agent"]
    environ = os.environ if environ is None else environ
    env = clean_env(environ)
    log = Path(found["log"])
    if found["via"] == "queue":
        return _queued(config, job, found, run, env)
    if agent == "claude":
        inbox = _inbox(job, environ)
        if inbox:
            try:
                send(*inbox, found["argv"][-1])
            except OSError:
                pass  # closed, or reopened on another socket; see whether it is open
            else:
                found |= {"via": "inbox", "copy": None}
                _record(config, job, found)
                return found
        if found["session"] in (listed(found["argv"][0]) or ()):
            raise WakeError(
                "its Claude session is open, but only a process started from it can reach "
                "its inbox, and resuming it would start a copy that works on its own"
            )
    offset = log.stat().st_size if log.exists() else 0
    child = spawn(found["argv"], cwd=found["cwd"], log=found["log"], env=env)
    try:
        code = child.wait(timeout=settle)
    except subprocess.TimeoutExpired:
        code = None
    said = _since(found["log"], offset)
    if code:
        if agent == "codex" and "active writer" in said:
            return _queued(config, job, found, run, env)
        last = _last_line(found["log"], offset)
        raise WakeError(f"{agent} exited with {code}" + (f": {last}" if last else ""))
    # Claude Code: "…is already running in the background, so this started a copy as 42dd3085."
    copy = re.search(r"(?i)\bcopy as (\w+)", said) if agent == "claude" else None
    found |= {"pid": child.pid, "via": "resume", "copy": copy.group(1) if copy else None}
    _record(config, job, found)
    return found


def _since(log: str, offset: int) -> str:
    try:
        with open(log, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _queued(config, job, found: dict, run, env) -> dict:
    """Hand the note to the Codex app that holds the thread open."""
    note = found["argv"][-1]
    argv = command("codex", found["session"], note, found["argv"][0], queue=True)
    code, said = run(argv, cwd=found["cwd"], env=env)
    with open(found["log"], "a") as f:
        f.write(said)
    if code:
        last = [line for line in said.splitlines() if line.strip()]
        raise WakeError(f"codex queue exited with {code}" + (f": {last[-1]}" if last else ""))
    found |= {"argv": argv, "via": "queue", "copy": False}
    _record(config, job, found)
    return found


def _record(config, job, found: dict) -> None:
    keys = ("agent", "session", "pid", "log", "via", "copy")
    jobs.record_event(config, job.key, "woke", {k: found[k] for k in keys if k in found})


def describe(found: dict) -> str:
    return shlex.join(found["argv"][:-1]) + " <note>"

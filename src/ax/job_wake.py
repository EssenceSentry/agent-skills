"""Wake the agent session that registered a job, with a short note on how it ended.

The note goes in as a new turn of that session:
- Codex: `codex exec resume <thread> <note>` runs one turn without a terminal, in
  the folder the job was registered from, which need not be a git repository.
- Claude Code: `claude --bg --resume <session> <note>` continues the session in the
  background, or a copy of it when the session is still open (Claude Code says so).

A Claude session that is still open is better woken by running `ax job wait KEY` as
a background command, which returns into that session; the jobs skill says so. This
module is for sessions that have ended, such as overnight runs.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ax import jobs

AGENTS = ("claude", "codex")
_SESSION = {"claude": "claude_session", "codex": "codex_thread"}
# Variables that tie a process to the session that started it: its session id, its
# messaging socket and token, the desktop entrypoint and the SDK's settings for it. A
# woken agent must start as a session of its own.
_SESSION_PREFIXES = ("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_", "CLAUDE_PREVIEW_")
_SESSION_NAMES = {
    "CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CODEX_THREAD_ID", "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED", "AX_JOB_FILE",
}  # fmt: skip
# Provider choices a user sets for every session, kept despite their prefix.
_KEEP = {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"}


class WakeError(RuntimeError):
    pass


def packet(config, job) -> str:
    """The note the woken agent reads: what happened and where to look, in a few lines."""
    lines = [f"[ax job] {job.key} {job.status}" + (f": {job.message}" if job.message else "")]
    if job.label:
        lines.append(job.label)
    if job.done is not None or job.total is not None:
        lines.append(f"progress: {jobs.progress_text(job)}")
    if job.stage:
        lines.append(f"last stage: {job.stage}")
    if job.check_error:
        lines.append(f"last check error: {job.check_error}")
    folder = jobs.events_path(config, job.key).parent
    if (folder / "output.log").exists():
        lines.append(f"output: {folder / 'output.log'}")
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
    return agent, session


def command(agent: str, session: str, note: str, binary: str) -> list[str]:
    if agent == "codex":
        return [binary, "exec", "resume", "--skip-git-repo-check", session, note]
    return [binary, "--bg", "--resume", session, note]


def clean_env(environ) -> dict:
    return {
        name: value
        for name, value in environ.items()
        if name in _KEEP or (name not in _SESSION_NAMES and not name.startswith(_SESSION_PREFIXES))
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


def _last_line(log: str) -> str:
    try:
        text = Path(log).read_text(errors="replace")
    except OSError:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def plan(config, job, agent: str = "auto", *, which=shutil.which, require=True) -> dict:
    """What waking would run, without running it."""
    agent, session = choose(job, agent)
    binary = which(agent)
    if not binary and require:
        raise WakeError(f"{agent} is not on PATH, so its session can't be resumed")
    binary = binary or agent
    argv = command(agent, session, packet(config, job), binary)
    cwd = job.cwd if job.cwd and os.path.isdir(job.cwd) else None
    log = jobs.events_path(config, job.key).parent / "wake.log"
    return {"agent": agent, "session": session, "argv": argv, "cwd": cwd, "log": str(log)}


def wake(
    config,
    job,
    agent: str = "auto",
    *,
    spawn=_spawn,
    which=shutil.which,
    environ=None,
    settle: float = 5.0,
) -> dict:
    """Start the agent's resumed turn in the background and record it on the job.

    A refusal comes back within a second or two (an untrusted folder, an unknown
    session), so the launch is given `settle` seconds to fail before it counts.
    """
    found = plan(config, job, agent, which=which)
    agent = found["agent"]
    env = clean_env(os.environ if environ is None else environ)
    child = spawn(found["argv"], cwd=found["cwd"], log=found["log"], env=env)
    try:
        code = child.wait(timeout=settle)
    except subprocess.TimeoutExpired:
        code = None
    if code:
        raise WakeError(f"{agent} exited with {code}: {_last_line(found['log'])}")
    found["pid"] = child.pid
    jobs.record_event(
        config,
        job.key,
        "woke",
        {k: found[k] for k in ("agent", "session", "pid", "log")},
    )
    return found


def describe(found: dict) -> str:
    return shlex.join(found["argv"][:-1]) + " <note>"

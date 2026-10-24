import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from ax import job_follow, job_wake, jobs
from ax.cli import app


class Spawned:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, *, cwd, log, env):
        self.calls.append({"argv": argv, "cwd": cwd, "log": log, "env": env})
        return 4242


def on_path(name):
    return f"/bin/{name}"


def ended_job(env, key="score", agent=None, status="done", message=None):
    jobs.new(env.config, key, total=10, unit="rows", label="Score rows", env=agent or {})
    end = {"status": status, **({"message": message} if message else {})}
    with open(jobs.events_path(env.config, key), "a") as f:
        f.write(json.dumps({"done": 10}) + "\n" + json.dumps(end) + "\n")
    return jobs.refresh(env.config, key)


def test_the_packet_says_what_happened_and_where_to_look(env):
    job = ended_job(env, status="failed", message="disk full")
    text = job_wake.packet(env.config, job)
    assert text.startswith("[ax job]")
    assert "score" in text and "failed" in text and "disk full" in text
    assert "10/10 rows" in text and "ax job show score" in text


def test_auto_wakes_the_session_that_registered_the_job(env):
    spawn = Spawned()
    codex = ended_job(env, "a", agent={"CODEX_THREAD_ID": "th-1"})
    woke = job_wake.wake(env.config, codex, spawn=spawn, which=on_path)
    assert spawn.calls[0]["argv"][:4] == ["/bin/codex", "exec", "resume", "th-1"]
    assert spawn.calls[0]["argv"][4].startswith("[ax job]")
    assert woke["agent"] == "codex" and woke["pid"] == 4242
    claude = ended_job(env, "b", agent={"CLAUDE_CODE_SESSION_ID": "s-1"})
    job_wake.wake(env.config, claude, spawn=spawn, which=on_path)
    assert spawn.calls[1]["argv"][:4] == ["/bin/claude", "--bg", "--resume", "s-1"]
    assert spawn.calls[1]["cwd"] == claude.cwd
    recorded = [e["data"] for e in jobs.events(env.config, "b") if e["type"] == "woke"]
    assert recorded and recorded[0]["agent"] == "claude"


def test_the_woken_agent_does_not_inherit_the_old_session(env):
    spawn = Spawned()
    job = ended_job(env, agent={"CLAUDE_CODE_SESSION_ID": "s-1"})
    parent = {
        "PATH": "/bin", "HOME": "/home/me", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s-1",
        "CLAUDE_CODE_SIMPLE": "1", "CLAUDE_CODE_USE_BEDROCK": "1", "CODEX_THREAD_ID": "t",
        "AX_JOB_FILE": "/x", "ANTHROPIC_API_KEY": "k",
    }  # fmt: skip
    job_wake.wake(env.config, job, spawn=spawn, which=on_path, environ=parent)
    child = spawn.calls[0]["env"]
    assert set(child) == {"PATH", "HOME", "CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_API_KEY"}


def test_a_job_without_a_session_or_cli_cannot_be_woken(env):
    job = ended_job(env, agent={})
    with pytest.raises(job_wake.WakeError, match="no agent session"):
        job_wake.wake(env.config, job, spawn=Spawned(), which=on_path)
    job = ended_job(env, "c", agent={"CODEX_THREAD_ID": "th-1"})
    with pytest.raises(job_wake.WakeError, match="codex is not on PATH"):
        job_wake.wake(env.config, job, spawn=Spawned(), which=lambda name: None)
    with pytest.raises(job_wake.WakeError, match="no claude session"):
        job_wake.wake(env.config, job, "claude", spawn=Spawned(), which=on_path)


class Timeline:
    def __init__(self, path, script):
        self.now, self.path, self.script, self.sleeps = (
            datetime.now(UTC).timestamp(),
            path,
            script,
            0,
        )

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        with open(self.path, "a") as f:
            for line in self.script.get(self.sleeps, []):
                f.write(json.dumps(line) + "\n")


def test_the_follower_wakes_the_agent_once_when_the_job_ends(env):
    jobs.new(env.config, "score", env={"CODEX_THREAD_ID": "th-1"})
    timeline = Timeline(jobs.events_path(env.config, "score"), {2: [{"status": "done"}]})
    woken = []
    options = job_follow.FollowOptions(dashboard=False, interval=5, linger=30, wake="auto")
    job_follow.follow(
        env.config, "score", options,
        waker=lambda job: woken.append(job.status), clock=timeline, sleep=timeline.sleep,
    )  # fmt: skip
    assert woken == ["done"]


def test_a_failed_wake_is_recorded_and_the_follower_carries_on(env):
    jobs.new(env.config, "score", env={})
    timeline = Timeline(jobs.events_path(env.config, "score"), {1: [{"status": "done"}]})
    options = job_follow.FollowOptions(dashboard=False, interval=5, linger=10, wake="auto")
    status = job_follow.follow(env.config, "score", options, clock=timeline, sleep=timeline.sleep)
    failed = [e["data"] for e in jobs.events(env.config, "score") if e["type"] == "wake_failed"]
    assert status == "done" and "no agent session" in failed[0]["error"]


def test_cli_wake_dry_run_prints_the_command(env):
    ended_job(env, agent={"CODEX_THREAD_ID": "th-1"})
    result = CliRunner().invoke(
        app, ["job", "wake", "score", "--dry-run"], env={"AX_CONFIG": str(env.config_path)}
    )
    assert result.exit_code == 0, result.output
    assert "codex exec resume th-1" in result.output

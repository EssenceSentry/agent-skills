import json
import subprocess
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from ax import job_follow, job_wake, jobs
from ax.cli import app


class Child:
    def __init__(self, code=None):
        self.pid, self.code = 4242, code

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired("agent", timeout)
        return self.code


class Spawned:
    """Records each launch; the child keeps running unless `code` says it exited."""

    def __init__(self, code=None, output=""):
        self.calls, self.code, self.output = [], code, output

    def __call__(self, argv, *, cwd, log, env):
        self.calls.append({"argv": argv, "cwd": cwd, "log": log, "env": env})
        with open(log, "a") as f:
            f.write(self.output)
        return Child(self.code)


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
    # Codex refuses an untrusted folder outside git unless told; the job's folder may be one.
    argv = spawn.calls[0]["argv"]
    assert argv[:5] == ["/bin/codex", "exec", "resume", "--skip-git-repo-check", "th-1"]
    assert argv[5].startswith("[ax job]")
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


def test_an_agent_that_exits_at_once_reports_why(env):
    job = ended_job(env, agent={"CLAUDE_CODE_SESSION_ID": "s-1"})
    spawn = Spawned(code=1, output="Workspace not trusted. Run `claude` in /x once.\n")
    with pytest.raises(job_wake.WakeError, match="Workspace not trusted"):
        job_wake.wake(env.config, job, spawn=spawn, which=on_path)
    assert not [e for e in jobs.events(env.config, "score") if e["type"] == "woke"]


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
    assert "exec resume --skip-git-repo-check th-1 <note>" in result.output


def test_credentials_and_settings_survive_while_session_ties_are_dropped(env):
    from ax.job_wake import clean_env

    parent = {
        "CLAUDE_CODE_OAUTH_TOKEN": "t", "CLAUDE_CODE_SKIP_BEDROCK_AUTH": "1",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "9", "CLAUDE_CODE_CLIENT_CERT": "/c.pem",
        "CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_CODE_MESSAGING_TOKEN": "m",
        "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/s.sock", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
        "CLAUDE_CODE_HOST_SESSION_ID": "h", "CLAUDE_CODE_EXECPATH": "/x", "CLAUDECODE": "1",
        "CLAUDE_AGENT_SDK_VERSION": "1", "CODEX_THREAD_ID": "t", "AX_JOB_FILE": "/j",
    }  # fmt: skip
    assert set(clean_env(parent)) == {
        "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_CLIENT_CERT",
    }  # fmt: skip


@pytest.mark.parametrize(
    "session", ["--dangerously-bypass-approvals-and-sandbox", "-x", "a b", "", "x" * 200]
)
def test_a_session_id_that_could_be_a_flag_is_refused(env, session):
    job = ended_job(env, agent={"CODEX_THREAD_ID": session} if session else {})
    with pytest.raises(job_wake.WakeError):
        job_wake.wake(env.config, job, "codex", spawn=Spawned(), which=on_path)


def test_a_failed_wake_reports_only_its_own_output(env):
    job = ended_job(env, agent={"CODEX_THREAD_ID": "01a17008-c339-7de3-93b5-5863a8c2445d"})
    log = jobs.events_path(env.config, "score").parent / "wake.log"
    log.write_text("an old error from the last wake\n")
    with pytest.raises(job_wake.WakeError) as raised:
        job_wake.wake(env.config, job, spawn=Spawned(code=1, output=""), which=on_path)
    assert "old error" not in str(raised.value) and "exited with 1" in str(raised.value)


class Ran:
    """Records quick commands run to completion (codex queue)."""

    def __init__(self, code=0, output="Queued message m-1 for thread th-1."):
        self.calls, self.code, self.output = [], code, output

    def __call__(self, argv, *, cwd, env):
        self.calls.append(argv)
        return self.code, self.output


def test_an_open_codex_thread_gets_the_note_through_codex_queue(env):
    spawn, ran = Spawned(), Ran()
    job = ended_job(env, "a", agent={"CODEX_THREAD_ID": "th-1"})
    woke = job_wake.wake(env.config, job, spawn=spawn, run=ran, which=on_path,
                         held=lambda thread: thread == "th-1")  # fmt: skip
    assert spawn.calls == [] and woke["via"] == "queue"
    [argv] = ran.calls
    assert argv[:5] == ["/bin/codex", "queue", "--thread", "th-1", "--message"]
    assert argv[5].startswith("[ax job] a done")
    [event] = [e for e in jobs.events(env.config, "a") if e["type"] == "woke"]
    assert event["data"]["via"] == "queue"


def test_a_thread_another_process_writes_falls_back_to_the_queue(env):
    busy = "Error: thread/resume failed: thread th-1 already has an active writer (code -32600)\n"
    spawn, ran = Spawned(code=1, output=busy), Ran()
    job = ended_job(env, "a", agent={"CODEX_THREAD_ID": "th-1"})
    woke = job_wake.wake(env.config, job, spawn=spawn, run=ran, which=on_path,
                         held=lambda thread: False)  # fmt: skip
    assert len(spawn.calls) == 1 and woke["via"] == "queue" and ran.calls[0][1] == "queue"


def test_a_refused_queue_is_a_wake_error(env):
    job = ended_job(env, "a", agent={"CODEX_THREAD_ID": "th-1"})
    with pytest.raises(job_wake.WakeError, match="no such thread"):
        job_wake.wake(env.config, job, spawn=Spawned(), run=Ran(1, "Error: no such thread"),
                      which=on_path, held=lambda thread: True)  # fmt: skip


def test_a_claude_session_still_open_is_woken_as_a_copy_and_says_so(env):
    # Claude Code 2.1's own words, seen in a live test.
    said = ("note: session 23264217 is already running in the background, so this started a "
            "copy as 42dd3085. `claude attach 23264217` opens the original.\n")  # fmt: skip
    spawn = Spawned(output=said)
    job = ended_job(env, "c", agent={"CLAUDE_CODE_SESSION_ID": "sess-1"})
    woke = job_wake.wake(env.config, job, spawn=spawn, which=on_path, settle=0)
    assert woke["copy"] == "42dd3085" and woke["via"] == "resume"
    [event] = [e for e in jobs.events(env.config, "c") if e["type"] == "woke"]
    assert event["data"]["copy"] == "42dd3085"


def test_the_packet_carries_the_failure_diagnosis(env):
    job = ended_job(env, status="failed", message="exit 1")
    jobs.record_event(env.config, "score", "diagnosis", {"text": "DuckDB API mismatch in mine()"})
    assert "Diagnosis: DuckDB API mismatch in mine()" in job_wake.packet(env.config, job)


def test_ax_job_describe_sets_the_description(env):
    jobs.new(env.config, "score", env={})
    result = CliRunner().invoke(app, ["job", "describe", "score", "--label", "Score the rows"],
                                env={"AX_CONFIG": str(env.config_path)})  # fmt: skip
    assert result.exit_code == 0, result.output
    assert jobs.get(env.config, "score").label == "Score the rows"
    assert any(e["type"] == "described" for e in jobs.events(env.config, "score"))


def test_the_plan_shows_the_queue_for_an_open_codex_thread(env):
    job = ended_job(env, "a", agent={"CODEX_THREAD_ID": "th-1"})
    found = job_wake.plan(env.config, job, which=on_path, held=lambda thread: True)
    assert found["via"] == "queue" and found["argv"][1:4] == ["queue", "--thread", "th-1"]
    assert job_wake.plan(env.config, job, which=on_path, held=lambda t: False)["via"] == "resume"


def test_a_note_on_a_running_job_does_not_say_carry_on(env):
    jobs.new(env.config, "score", label="Score rows; then build the report", env={})
    job = jobs.get(env.config, "score")
    note = job_wake.packet(env.config, job, jobs.still_running(job, "every row errors"))
    assert note.startswith("[ax job] Every row errors. score is still running")
    assert "What it does, and what follows once it ends: Score rows" in note
    assert "don't start what follows it" in note and "carry on" not in note

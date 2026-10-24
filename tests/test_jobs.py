import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from ax import jobs
from ax.cli import app

runner = CliRunner()


class FakeClock:
    """A clock that only moves when waited on, so wait() runs instantly in tests."""

    def __init__(self, start=None):
        self.now = start if start is not None else datetime.now(UTC).timestamp()

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def append(path, *lines):
    with open(path, "a") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_new_job_has_an_events_file_and_starts_running(env):
    job = jobs.new(env.config, "score", total=500, unit="rows")
    path = jobs.events_path(env.config, "score")
    assert path.exists() and path.parent.name == "score"
    assert (job.status, job.total, job.unit, job.done) == ("running", 500, "rows", None)
    assert jobs.get(env.config, "score").kind == "events"


def test_progress_stage_and_status_lines_update_the_job(env):
    jobs.new(env.config, "score")
    path = jobs.events_path(env.config, "score")
    append(path, {"done": 10, "total": 40}, {"stage": "scoring"}, {"done": 25})
    job = jobs.refresh(env.config, "score")
    assert (job.done, job.total, job.stage, job.status) == (25, 40, "scoring", "running")
    append(path, {"status": "done", "message": "wrote 40 rows"})
    job = jobs.refresh(env.config, "score")
    assert (job.status, job.message) == ("done", "wrote 40 rows")
    assert job.finished is not None
    types = [e["type"] for e in jobs.events(env.config, "score")]
    assert types[0] == "created" and "stage" in types and types[-1] == "status"


def test_a_line_without_its_newline_waits_for_the_next_read(env):
    jobs.new(env.config, "score")
    path = jobs.events_path(env.config, "score")
    with open(path, "a") as f:
        f.write('{"done": 5')
    assert jobs.refresh(env.config, "score").done is None
    with open(path, "a") as f:
        f.write("}\n")
    assert jobs.refresh(env.config, "score").done == 5


def test_an_exit_code_ends_the_job(env):
    jobs.new(env.config, "ok")
    append(jobs.events_path(env.config, "ok"), {"exit": 0})
    assert jobs.refresh(env.config, "ok").status == "done"
    jobs.new(env.config, "bad")
    append(jobs.events_path(env.config, "bad"), {"exit": 3})
    job = jobs.refresh(env.config, "bad")
    assert job.status == "failed" and "3" in job.message


def test_a_bad_line_is_recorded_without_stopping_the_job(env):
    jobs.new(env.config, "score")
    append(jobs.events_path(env.config, "score"), "not json", {"done": 2})
    job = jobs.refresh(env.config, "score")
    assert (job.status, job.done) == ("running", 2)
    assert any(e["type"] == "bad_line" for e in jobs.events(env.config, "score"))


def test_lines_after_the_end_do_not_reopen_a_job(env):
    jobs.new(env.config, "score")
    append(jobs.events_path(env.config, "score"), {"status": "failed"}, {"done": 9})
    job = jobs.refresh(env.config, "score")
    assert (job.status, job.done) == ("failed", None)


@pytest.mark.parametrize("key", ["../escape", "", "a/b", ".hidden", "x" * 101])
def test_keys_must_be_safe_folder_names(env, key):
    with pytest.raises(ValueError):
        jobs.new(env.config, key)


def test_registering_the_same_key_again_returns_the_job(env):
    first = jobs.new(env.config, "score", total=5)
    again = jobs.new(env.config, "score", total=5)
    assert again.created == first.created
    with pytest.raises(ValueError, match="already"):
        jobs.watch(env.config, "pid", "123", key="score")


def test_the_launching_agent_session_is_recorded(env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    monkeypatch.setenv("CODEX_THREAD_ID", "t-2")
    job = jobs.new(env.config, "score")
    assert job.agent == {"claude_session": "s-1", "codex_thread": "t-2"}


def test_forget_drops_the_job_and_its_folder(env):
    jobs.new(env.config, "score")
    folder = jobs.events_path(env.config, "score").parent
    jobs.forget(env.config, "score")
    assert jobs.get(env.config, "score") is None and not folder.exists()


def test_list_hides_finished_jobs_unless_asked(env):
    jobs.new(env.config, "live")
    jobs.new(env.config, "over")
    append(jobs.events_path(env.config, "over"), {"status": "done"})
    assert [j.key for j in jobs.list_jobs(env.config)] == ["live"]
    assert {j.key for j in jobs.list_jobs(env.config, include_finished=True)} == {"live", "over"}


def test_wait_returns_when_the_job_ends(env):
    jobs.new(env.config, "score")
    path = jobs.events_path(env.config, "score")
    clock = FakeClock()

    def sleep(seconds):
        clock.sleep(seconds)
        append(path, {"status": "done"})

    outcome, job = jobs.wait(env.config, "score", interval=5, clock=clock, sleep=sleep)
    assert (outcome, job.status) == ("done", "done")


def test_wait_times_out_and_reports_stalls(env):
    jobs.new(env.config, "score")
    clock = FakeClock()
    outcome, _ = jobs.wait(
        env.config, "score", timeout=30, interval=10, clock=clock, sleep=clock.sleep
    )
    assert outcome == "timeout" and clock.now >= 30
    late = FakeClock(datetime.now(UTC).timestamp() + 3600)
    outcome, _ = jobs.wait(env.config, "score", stall_after=600, clock=late, sleep=late.sleep)
    assert outcome == "stalled"


def test_wait_returns_a_final_status_it_was_not_asked_for(env):
    # A stopped job can never fail, so waiting for "failed" must not hang.
    jobs.new(env.config, "score")
    append(jobs.events_path(env.config, "score"), {"status": "stopped"})
    outcome, _ = jobs.wait(env.config, "score", until={"failed"})
    assert outcome == "stopped"


def test_waiting_for_stalled_turns_on_stall_detection(env):
    jobs.new(env.config, "score")
    late = FakeClock(datetime.now(UTC).timestamp() + 7200)
    outcome, _ = jobs.wait(env.config, "score", until={"stalled"}, clock=late, sleep=late.sleep)
    assert outcome == "stalled"


def test_wait_on_an_unknown_job_raises(env):
    with pytest.raises(KeyError):
        jobs.wait(env.config, "nope", timeout=0)


def cli(env, *args, **kw):
    return runner.invoke(app, ["job", *args], env={"AX_CONFIG": str(env.config_path)}, **kw)


def test_cli_new_prints_the_events_file_for_shell_use(env):
    result = cli(env, "new", "score", "--total", "3")
    assert result.exit_code == 0, result.output
    path = result.output.strip()
    assert path.endswith("score/events.jsonl")
    append(path, {"done": 3})
    shown = json.loads(cli(env, "show", "score", "--json").output)
    assert (shown["key"], shown["done"], shown["total"]) == ("score", 3, 3)


def test_cli_list_and_wait_exit_codes(env):
    cli(env, "new", "a")
    cli(env, "new", "b")
    listed = json.loads(cli(env, "ls", "--json").output)
    assert {j["key"] for j in listed} == {"a", "b"}
    assert cli(env, "wait", "a", "--timeout", "0").exit_code == 124
    append(jobs.events_path(env.config, "a"), {"exit": 0})
    append(jobs.events_path(env.config, "b"), {"exit": 2})
    done = cli(env, "wait", "a", "--json")
    assert done.exit_code == 0 and json.loads(done.output)["outcome"] == "done"
    assert cli(env, "wait", "b").exit_code == 1
    assert cli(env, "wait", "nope").exit_code == 69


def test_cli_forget(env):
    cli(env, "new", "a")
    assert cli(env, "forget", "a").exit_code == 0
    assert cli(env, "show", "a").exit_code == 69


def test_latest_events_come_back_in_order(env):
    jobs.new(env.config, "score")
    append(jobs.events_path(env.config, "score"), *({"done": n} for n in range(1, 6)))
    jobs.refresh(env.config, "score")
    latest = jobs.events(env.config, "score", limit=2, latest=True)
    assert [e["data"]["done"] for e in latest] == [4, 5]

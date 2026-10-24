import json
import os
import plistlib
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest

from ax import glue, job_follow, job_service, job_sources, jobs


def dead_pid() -> int:
    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


def follower_file(env, key, pid, **options):
    info = {
        "pid": pid,
        "link": "http://127.0.0.1:1/?token=x",
        "options": asdict(job_follow.FollowOptions(**options)),
    }
    job_follow.follower_path(env.config, key).write_text(json.dumps(info))


class Starts:
    def __init__(self):
        self.calls = []

    def __call__(self, config, key, args):
        self.calls.append((key, args))
        return {"pid": 1, "link": "http://x"}


def append(env, key, line):
    with open(jobs.events_path(env.config, key), "a") as f:
        f.write(json.dumps(line) + "\n")


def test_tick_refreshes_jobs_nobody_follows(env):
    jobs.new(env.config, "a")
    append(env, "a", {"done": 3})
    found = job_service.tick(env.config, start=Starts())
    assert jobs.get(env.config, "a").done == 3 and found["refreshed"] == ["a"]


def test_tick_leaves_a_followed_job_to_its_follower(env):
    jobs.new(env.config, "b")
    follower_file(env, "b", os.getpid())
    append(env, "b", {"done": 3})
    found = job_service.tick(env.config, start=Starts())
    assert jobs.get(env.config, "b").done is None and found["followed"] == ["b"]


def aws_job(env, key, **spec):
    return jobs._register(
        env.config, key, "sagemaker", key, label=None, cwd=None, env={},
        spec={"name": key, "type": "processing", "region": "us-east-1", **spec},
    )  # fmt: skip


def test_tick_checks_aws_only_with_a_profile_it_can_use(env, monkeypatch):
    # Credentials an agent exported in its shell are not visible to launchd.
    aws_job(env, "envcreds")
    aws_job(env, "named", profile="ds")
    checked = []
    monkeypatch.setattr(job_sources, "check", lambda job, now: checked.append(job.key) or [])
    found = job_service.tick(env.config, start=Starts())
    assert checked == ["named"] and found["unchecked"] == ["envcreds"]


def test_tick_restarts_a_follower_that_died(env):
    jobs.new(env.config, "c")
    follower_file(env, "c", dead_pid(), share="cloudflare", notify=True, wake="auto", every=600)
    starts = Starts()
    found = job_service.tick(env.config, start=starts)
    [(key, args)] = starts.calls
    assert key == "c" and found["revived"] == ["c"]
    assert args[args.index("--share") + 1] == "cloudflare" and "--notify" in args
    assert args[args.index("--wake") + 1] == "auto" and "--resumed" in args
    assert args[args.index("--every") + 1] == "10.0"  # minutes on the command line
    assert any(e["type"] == "follower_revived" for e in jobs.events(env.config, "c"))


def test_revival_gives_up_after_three_tries(env):
    jobs.new(env.config, "d")
    for _ in range(3):
        jobs.record_event(env.config, "d", "follower_revived", {})
    follower_file(env, "d", dead_pid())
    starts = Starts()
    found = job_service.tick(env.config, start=starts)
    assert not starts.calls and found["gave_up"] == ["d"]


def test_a_job_that_ended_while_its_follower_was_down_still_gets_its_follower(env):
    jobs.new(env.config, "e")
    append(env, "e", {"status": "done"})
    jobs.refresh(env.config, "e")
    follower_file(env, "e", dead_pid(), notify=True)
    starts = Starts()
    job_service.tick(env.config, start=starts)
    assert [key for key, _ in starts.calls] == ["e"]


def test_a_follower_file_left_by_a_long_finished_job_is_removed(env):
    jobs.new(env.config, "old")
    long_ago = jobs.now_iso(datetime.now(UTC) - timedelta(days=2))
    with jobs.connect(env.config) as db:
        db.execute("UPDATE jobs SET status = 'done', finished = ? WHERE key = 'old'", (long_ago,))
    follower_file(env, "old", dead_pid())
    starts = Starts()
    job_service.tick(env.config, start=starts)
    assert not starts.calls and not job_follow.follower_path(env.config, "old").exists()


def test_options_round_trip_through_the_command_line(env):
    options = job_follow.FollowOptions(
        share="lan", notify=True, every=300, notify_stages=True, stall_after=1200, linger=30,
        show_log=True, interval=2, port=8123, wake="codex",
    )  # fmt: skip
    args = job_follow.options_args(options)
    assert args[args.index("--every") + 1] == "5.0"
    assert args[args.index("--stall-after") + 1] == "20.0"
    assert {"--notify", "--notify-stages", "--show-log"} <= set(args)


class Timeline:
    def __init__(self):
        self.now = datetime.now(UTC).timestamp()

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_a_resumed_follower_does_not_repeat_what_was_sent(env):
    jobs.new(env.config, "f", env={"CODEX_THREAD_ID": "t"})
    append(env, "f", {"status": "done"})
    jobs.refresh(env.config, "f")
    jobs.record_event(env.config, "f", "notified", {"title": "f done"})
    jobs.record_event(env.config, "f", "woke", {"agent": "codex"})
    sent, woken = [], []
    clock = Timeline()
    options = job_follow.FollowOptions(
        dashboard=False, notify=True, linger=10, interval=5, wake="auto", resumed=True
    )
    job_follow.follow(
        env.config, "f", options, notifier=lambda m: sent.append(m["title"]),
        waker=woken.append, clock=clock, sleep=clock.sleep,
    )  # fmt: skip
    assert sent == [] and woken == []


def test_the_service_runs_the_background_poll_every_minute(env):
    [change] = glue.plan_jobs_service(env.config, ax="/bin/ax", launch_agents=env.root / "LA")
    plist = plistlib.loads(change.after.encode())
    assert plist["Label"] == "com.ax.jobs" and plist["StartInterval"] == 60
    assert plist["ProgramArguments"] == ["/bin/ax", "job", "poll", "--background", "--quiet"]


@pytest.mark.parametrize("flag", ["--remove", None])
def test_cli_service_is_a_dry_run_by_default(env, monkeypatch, flag):
    from typer.testing import CliRunner

    from ax.cli import app

    monkeypatch.setattr(glue, "launch_agents_dir", lambda: env.root / "LaunchAgents")
    args = ["job", "service", *([flag] if flag else [])]
    result = CliRunner().invoke(app, args, env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 0, result.output
    assert "would" in result.output and not (env.root / "LaunchAgents").exists()

"""The job API agents use: a key and a label, and nothing else to decide. Every job gets a
follower that wakes the agent that registered it, Haiku looks at a job every 5 minutes once
it has run 10, and old options still work, with a note on what happens now."""

import json
import os
import re
import sys
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from ax import job_follow, job_sources, job_triage, jobs
from ax.cli import app

SESSION = {"CLAUDE_CODE_SESSION_ID": "s-1"}
PASS = [sys.executable, "-c", "pass"]


def cli(env, *args, extra=None):
    environ = {"AX_CONFIG": str(env.config_path), "CLAUDE_CODE_SESSION_ID": "",
               "CODEX_THREAD_ID": "", **(extra or {})}  # fmt: skip
    return CliRunner().invoke(app, ["job", *args], env=environ)


@pytest.fixture
def followers(monkeypatch):
    started = []

    def start(config, key, args):
        started.append((key, args))
        return {"link": "http://127.0.0.1:1/"}

    monkeypatch.setattr(job_follow, "start_detached", start)
    return started


def finish(env, key):
    return jobs.wait(env.config, key, timeout=20, interval=0.1)


# A key and a label, always


def test_run_needs_a_key_and_a_label(env, followers):
    result = cli(env, "run", "--label", "Nothing much", "--", *PASS)
    assert result.exit_code == 2 and "--key" in result.stderr
    result = cli(env, "run", "--key", "k", "--", *PASS)
    assert result.exit_code == 2 and "--label" in result.stderr
    assert "what you'll do next" in result.stderr
    assert jobs.get(env.config, "k") is None and followers == []  # nothing was started


def test_watch_and_new_need_a_key_and_a_label(env, followers):
    me = str(os.getpid())
    assert "--key" in cli(env, "watch", "pid", me, "--label", "This test").stderr
    assert "--label" in cli(env, "watch", "pid", me, "--key", "me").stderr
    assert jobs.get(env.config, "me") is None
    assert cli(env, "watch", "pid", me, "--key", "me", "--label", "This test").exit_code == 0
    assert "--label" in cli(env, "new", "--key", "feed").stderr
    result = cli(env, "new", "--key", "feed", "--label", "Feed rows; then score them")
    assert result.exit_code == 0 and result.stdout.strip().endswith("feed/events.jsonl")
    result = cli(env, "new", "feed2", "--label", "Positional keys still work")
    assert result.exit_code == 0, result.output


# A follower for every job


def test_every_job_gets_a_follower_that_wakes_its_agent(env, followers):
    result = cli(env, "run", "--key", "k", "--label", "Run nothing; then stop", "--", *PASS,
                 extra=SESSION)  # fmt: skip
    assert result.exit_code == 0, result.output
    key, args = followers[-1]
    assert key == "k" and args[args.index("--wake") + 1] == "auto"
    assert "--check-every" not in args  # the default schedule
    assert cli(env, "new", "--key", "plain", "--label", "From a terminal").exit_code == 0
    key, args = followers[-1]
    assert key == "plain" and "--wake" not in args  # nobody to wake: the phone is told


def test_a_follower_that_will_not_start_is_a_warning_not_a_failed_job(env, monkeypatch):
    def broken(config, key, args):
        raise RuntimeError("the follower stopped: boom")

    monkeypatch.setattr(job_follow, "start_detached", broken)
    result = cli(env, "run", "--key", "k", "--label", "Run nothing", "--", *PASS, extra=SESSION)
    assert result.exit_code == 0 and result.stdout.strip() == "k"
    assert "no follower" in result.stderr and "ax job wait k" in result.stderr


def test_old_options_still_work_with_a_note(env, followers):
    result = cli(env, "run", "--key", "k", "--label", "Run nothing", "--wake", "auto",
                 "--expect", "25m", "--share", "cloudflare", "--notify", "--show-log", "--",
                 *PASS, extra=SESSION)  # fmt: skip
    assert result.exit_code == 0, result.output
    note = result.stderr
    for flag in ("--wake", "--expect", "--share", "--notify", "--show-log"):
        assert flag in note
    assert "no longer" in note
    key, args = followers[-1]
    assert args[args.index("--share") + 1] == "none" and "--notify" not in args
    assert jobs.expected(env.config, "k") is None
    assert finish(env, "k")[0] == "done"
    result = cli(env, "new", "--key", "n", "--label", "Feed", "--wake", "none", extra=SESSION)
    assert result.exit_code == 0 and "--wake" in result.stderr


def commands(text):
    """The command names a --help lists."""
    tail = text.split("Commands", 1)[1] if "Commands" in text else ""
    return {m.group(1) for m in re.finditer(r"^[\W_]*([a-z][a-z-]*)\s{2,}", tail, re.M)}


def flags(text):
    return set(re.findall(r"(?<![\w-])--[a-z][a-z-]*(?![\w-])", text))


def test_help_shows_only_what_agents_need(env):
    shown = commands(cli(env, "--help").stdout)
    assert {"run", "watch", "new", "wait", "show", "ls", "wake-at", "check"} <= shown
    assert not shown & {"follow", "unfollow", "describe", "wake", "poll", "service",
                        "eta-report", "forget"}  # fmt: skip
    assert flags(cli(env, "run", "--help").stdout) == {"--key", "--label", "--wake-at", "--json",
                                                       "--help"}  # fmt: skip
    assert flags(cli(env, "watch", "--help").stdout) == {"--key", "--label", "--wake-at",
                                                         "--json", "--help"}  # fmt: skip
    assert flags(cli(env, "new", "--help").stdout) == {"--key", "--label", "--json", "--help"}
    assert flags(cli(env, "wait", "--help").stdout) == {"--timeout", "--json", "--help"}


def test_hidden_commands_and_options_still_work(env, followers):
    jobs.new(env.config, "k")
    assert cli(env, "describe", "k", "--label", "Now described").exit_code == 0
    assert jobs.get(env.config, "k").label == "Now described"
    result = cli(env, "wait", "k", "--timeout", "1", "--interval", "0.1", "--until", "done")
    assert result.exit_code == 124
    assert cli(env, "forget", "k").exit_code == 0


# Haiku's looks: from 10 minutes into the job, every 5 minutes


class Timeline:
    def __init__(self, path, script):
        self.now = datetime.now(UTC).timestamp()
        self.start = self.now
        self.path = path
        self.script = script
        self.sleeps = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        with open(self.path, "a") as f:
            for line in self.script.get(self.sleeps, []):
                f.write(json.dumps(line) + "\n")


def follow(env, script, options=None, timeline=None, **hooks):
    timeline = timeline or Timeline(jobs.events_path(env.config, "score"), script)
    options = options or job_follow.FollowOptions(dashboard=False, interval=60, linger=60)
    job_follow.follow(env.config, "score", options, clock=timeline, sleep=timeline.sleep,
                      **hooks)  # fmt: skip
    return timeline


def test_haiku_looks_once_a_job_has_run_10_minutes_then_every_5(env):
    from ax.job_triage import Look

    jobs.new(env.config, "score")
    seen = []
    timeline = Timeline(jobs.events_path(env.config, "score"), {25: [{"status": "done"}]})
    follow(env, {}, timeline=timeline, diagnoser=lambda job: None,
           checker=lambda job: seen.append(timeline.now) or Look("Scoring."))  # fmt: skip
    assert [round((t - timeline.start) / 60) for t in seen] == [10, 15, 20]


def test_an_interval_someone_asks_for_replaces_the_schedule(env):
    from ax.job_triage import Look

    jobs.new(env.config, "score")
    job_follow.set_check(env.config, "score", every=120)  # `ax job check score --every 2m`
    seen = []
    timeline = follow(env, {7: [{"status": "done"}]},
                      checker=lambda job: seen.append(len(seen)) or Look("Scoring."),
                      diagnoser=lambda job: None)  # fmt: skip
    assert len(seen) == 3 and timeline.sleeps >= 7  # at 2, 4 and 6 minutes
    jobs.forget(env.config, "score")
    jobs.new(env.config, "score")
    job_follow.set_check(env.config, "score", every=0)  # `--every 0` stops them
    seen.clear()
    follow(env, {15: [{"status": "done"}]}, checker=lambda job: seen.append(1) or Look("x"),
           diagnoser=lambda job: None)  # fmt: skip
    assert seen == []


def test_the_default_interval_is_shown_as_5_minutes(env, followers):
    jobs.new(env.config, "score")
    path = job_follow.follower_path(env.config, "score")
    path.write_text(json.dumps({"pid": os.getpid(), "options": {"check_every": None}}))
    assert job_follow.check_every(env.config, "score") == 300
    job_follow.set_check(env.config, "score", every=0)
    assert job_follow.check_every(env.config, "score") is None


# Failures nobody will be woken for


def test_a_failure_with_no_agent_is_diagnosed_and_pushed_to_the_phone(env, monkeypatch):
    jobs.new(env.config, "score")  # registered from a terminal: no session to wake
    monkeypatch.setattr(job_triage, "diagnose", lambda config, job: "The disk is full.")
    alerts = []
    follow(env, {1: [{"status": "failed", "message": "exited with code 1"}]},
           alerter=alerts.append)  # fmt: skip
    [alert] = alerts
    assert alert["title"] == "score failed"
    assert "exited with code 1" in alert["message"] and "The disk is full." in alert["message"]
    assert jobs.latest_event(env.config, "score", "diagnosis")["text"] == "The disk is full."


def test_a_job_that_succeeds_with_no_agent_sends_nothing(env, monkeypatch):
    jobs.new(env.config, "score")
    monkeypatch.setattr(job_triage, "diagnose", lambda config, job: pytest.fail("no diagnosis"))
    alerts = []
    follow(env, {1: [{"status": "done"}]}, alerter=alerts.append)
    assert alerts == []


# What ax works out itself


def test_a_sagemaker_jobs_type_is_found_by_asking(env, monkeypatch):
    asked = []

    def fake(args, *, region=None, profile=None):
        asked.append(args[1])
        if args[1] == "describe-training-job":
            return {"TrainingJobStatus": "InProgress", "SecondaryStatus": "Training"}
        raise job_sources.AwsError("ValidationException: Could not find requested job")

    monkeypatch.setattr(job_sources, "run_aws", fake)
    job = jobs.watch(env.config, "sagemaker", "train-1")
    assert (job.status, job.stage, job.spec["type"]) == ("running", "Training", "training")
    assert asked == ["describe-processing-job", "describe-training-job"]
    asked.clear()
    jobs.refresh(env.config, "train-1", now=datetime.now(UTC).replace(year=2100))
    assert asked == ["describe-training-job"]  # found once, then asked directly


def test_a_sagemaker_job_of_no_type_is_a_check_error(env, monkeypatch):
    def fake(args, *, region=None, profile=None):
        raise job_sources.AwsError("ValidationException: Could not find requested job")

    monkeypatch.setattr(job_sources, "run_aws", fake)
    job = jobs.watch(env.config, "sagemaker", "nope-1")
    assert job.status == "running"
    assert "no processing, training or transform job named nope-1" in job.check_error


def test_the_aws_profile_comes_from_the_shell(env, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "ds")
    monkeypatch.setattr(job_sources, "run_aws",
                        lambda args, **kw: {"ProcessingJobStatus": "InProgress"})  # fmt: skip
    job = jobs.watch(env.config, "sagemaker", "merge-1")
    assert job.spec["profile"] == "ds"


def test_runwatch_is_found_in_the_projects_venv(env, tmp_path, monkeypatch):
    import stat

    monkeypatch.delenv("AX_RUNWATCH", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    project = tmp_path / "project"
    binary = project / ".venv" / "bin" / "runwatch"
    binary.parent.mkdir(parents=True)
    binary.write_text(f"#!{sys.executable}\nprint('{{\"run\": {{}}}}')\n")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    run = project / ".runwatch" / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "runwatch.sqlite3").write_text("")
    _, spec = job_sources.prepare("runwatch", str(run), {}, str(project))
    assert spec["binary"] == str(binary.resolve())

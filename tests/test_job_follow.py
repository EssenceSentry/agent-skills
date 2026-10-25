import json
import os
from datetime import UTC, datetime

import pytest

from ax import job_follow, jobs


class Timeline:
    """A fake clock whose sleeps also append scripted lines to the job's events file."""

    def __init__(self, path, script):
        self.now = datetime.now(UTC).timestamp()
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


def collect():
    sent = []

    def notifier(message):
        sent.append(message)
        return None

    return sent, notifier


def options(**kw):
    return job_follow.FollowOptions(dashboard=False, notify=True, interval=5, **kw)


def test_the_follower_reports_start_progress_and_the_end(env):
    jobs.new(env.config, "score", total=4)
    path = jobs.events_path(env.config, "score")
    timeline = Timeline(
        path, {1: [{"done": 1}], 3: [{"done": 2}], 6: [{"done": 4}, {"status": "done"}]}
    )
    sent, notifier = collect()
    outcome = job_follow.follow(
        env.config, "score", options(every=10, linger=10),
        notifier=notifier, clock=timeline, sleep=timeline.sleep,
    )  # fmt: skip
    titles = [m["title"] for m in sent]
    assert outcome == "done"
    assert titles[0] == "score started" and titles[-1] == "score done"
    assert "score: 50%" in titles
    assert not (path.parent / "follower.json").exists()


def test_the_dashboard_lingers_after_the_job_ends(env):
    jobs.new(env.config, "score")
    path = jobs.events_path(env.config, "score")
    timeline = Timeline(path, {1: [{"status": "done"}]})
    sent, notifier = collect()
    job_follow.follow(
        env.config, "score", options(linger=60),
        notifier=notifier, clock=timeline, sleep=timeline.sleep,
    )  # fmt: skip
    assert timeline.sleeps >= 60 / 5


def test_stage_changes_are_sent_only_when_asked(env):
    jobs.new(env.config, "score")
    path = jobs.events_path(env.config, "score")
    script = {1: [{"stage": "download"}], 2: [{"stage": "score"}], 3: [{"status": "done"}]}
    for notify_stages, expected in ((False, 0), (True, 2)):
        jobs.forget(env.config, "score")
        jobs.new(env.config, "score")
        timeline = Timeline(path, script)
        sent, notifier = collect()
        job_follow.follow(
            env.config, "score", options(every=0, linger=0, notify_stages=notify_stages),
            notifier=notifier, clock=timeline, sleep=timeline.sleep,
        )  # fmt: skip
        assert sum(": download" in m["title"] or ": score" in m["title"] for m in sent) == expected


def test_a_stall_is_reported_once(env):
    jobs.new(env.config, "score")
    path = jobs.events_path(env.config, "score")
    timeline = Timeline(path, {40: [{"status": "done"}]})
    sent, notifier = collect()
    job_follow.follow(
        env.config, "score", options(every=0, linger=0, stall_after=60),
        notifier=notifier, clock=timeline, sleep=timeline.sleep,
    )  # fmt: skip
    assert [m["title"] for m in sent].count("score stalled") == 1


def test_a_failed_notification_is_recorded_and_the_follower_goes_on(env):
    jobs.new(env.config, "score")
    path = jobs.events_path(env.config, "score")
    timeline = Timeline(path, {1: [{"status": "done"}]})
    outcome = job_follow.follow(
        env.config, "score", options(linger=0),
        notifier=lambda message: "ntfy is down", clock=timeline, sleep=timeline.sleep,
    )  # fmt: skip
    assert outcome == "done"
    failures = [e for e in jobs.events(env.config, "score") if e["type"] == "notify_failed"]
    assert failures and failures[0]["data"]["error"] == "ntfy is down"


def test_a_live_follower_is_reused_not_doubled(env):
    jobs.new(env.config, "score")
    folder = jobs.events_path(env.config, "score").parent
    (folder / "follower.json").write_text(
        json.dumps({"pid": os.getpid(), "link": "http://127.0.0.1:1/?token=t"})
    )
    with pytest.raises(job_follow.AlreadyFollowing) as found:
        job_follow.follow(env.config, "score", options())
    assert found.value.info["link"] == "http://127.0.0.1:1/?token=t"
    # A follower file left by a dead process doesn't block a new follower.
    (folder / "follower.json").write_text(json.dumps({"pid": 999999, "link": "x"}))
    assert job_follow.running(env.config, "score") is None


def test_following_an_unknown_job_raises(env):
    with pytest.raises(KeyError):
        job_follow.follow(env.config, "nope", options())


def _get_json(link_base, path, token):
    import urllib.request

    with urllib.request.urlopen(f"{link_base}{path}?token={token}", timeout=5) as response:
        return json.loads(response.read())


def test_the_follower_serves_the_dashboard_while_it_runs(env):
    import threading
    from urllib.parse import parse_qs, urlsplit

    jobs.new(env.config, "score", total=2)
    result = {}
    opts = job_follow.FollowOptions(interval=0.1, linger=0)
    thread = threading.Thread(
        target=lambda: result.update(status=job_follow.follow(env.config, "score", opts))
    )
    thread.start()
    try:
        info = None
        for _ in range(100):
            info = job_follow.running(env.config, "score")
            if info:
                break
            thread.join(0.05)
        link = urlsplit(info["link"])
        token = parse_qs(link.query)["token"][0]
        base = f"{link.scheme}://{link.netloc}"
        with open(jobs.events_path(env.config, "score"), "a") as f:
            f.write(json.dumps({"done": 1}) + "\n")
        for _ in range(50):
            if _get_json(base, "/api/job", token)["done"] == 1:
                break
            thread.join(0.05)
        assert _get_json(base, "/api/job", token)["done"] == 1
    finally:
        with open(jobs.events_path(env.config, "score"), "a") as f:
            f.write(json.dumps({"status": "done"}) + "\n")
        thread.join(10)
    assert result["status"] == "done" and job_follow.running(env.config, "score") is None


def cli(env, *args):
    from typer.testing import CliRunner

    from ax.cli import app

    return CliRunner().invoke(app, ["job", *args], env={"AX_CONFIG": str(env.config_path)})


def test_cli_starts_a_detached_follower_and_unfollow_stops_it(env, monkeypatch):
    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    result = cli(env, "new", "score", "--share", "none")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip().endswith("score/events.jsonl")
    assert "dashboard: http://127.0.0.1:" in result.stderr
    info = job_follow.running(env.config, "score")
    assert info and info["pid"] != os.getpid()
    again = cli(env, "follow", "score", "--detach")
    assert again.exit_code == 0 and info["link"] in again.stdout
    shown = json.loads(cli(env, "show", "score", "--json").stdout)
    assert shown["follower"]["link"] == info["link"]
    assert cli(env, "unfollow", "score").exit_code == 0
    assert job_follow.running(env.config, "score") is None


def test_forgetting_a_job_stops_its_follower(env, monkeypatch):
    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    assert cli(env, "new", "score", "--share", "none").exit_code == 0
    pid = job_follow.running(env.config, "score")["pid"]
    assert cli(env, "forget", "score").exit_code == 0
    import time

    for _ in range(50):
        if not job_follow._alive(pid):
            break
        time.sleep(0.1)
    assert not job_follow._alive(pid)


def test_cli_notify_without_a_topic_is_refused(env, monkeypatch):
    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.delenv("AX_NTFY_TOPIC", raising=False)
    jobs.new(env.config, "score")
    result = cli(env, "follow", "score", "--notify")
    assert result.exit_code == 2 and "no ntfy topic" in result.stderr


def follow_with(env, script, **kw):
    timeline = Timeline(jobs.events_path(env.config, "score"), script)
    hooks = {k: kw.pop(k) for k in ("waker", "alerter", "diagnoser", "checker") if k in kw}
    opts = job_follow.FollowOptions(dashboard=False, interval=60, linger=60, wake="auto", **kw)
    return job_follow.follow(env.config, "score", opts, clock=timeline, sleep=timeline.sleep,
                             **hooks)  # fmt: skip


def test_a_wake_that_fails_or_lands_in_a_copy_alerts_the_user(env):
    from ax.job_wake import WakeError

    jobs.new(env.config, "score", env={"CODEX_THREAD_ID": "th-1"})
    alerts = []

    def refuse(job):
        raise WakeError("codex exited with 1")

    follow_with(env, {1: [{"status": "done"}]}, waker=refuse, alerter=alerts.append)
    assert (
        "couldn't reach" in alerts[0]["message"] and "codex exited with 1" in alerts[0]["message"]
    )
    jobs.forget(env.config, "score")
    jobs.new(env.config, "score", env={"CLAUDE_CODE_SESSION_ID": "s-1"})
    follow_with(env, {1: [{"status": "done"}]}, alerter=alerts.append,
                waker=lambda job: {"agent": "claude", "copy": "42dd3085", "via": "resume"})  # fmt: skip
    assert "claude attach 42dd3085" in alerts[1]["message"]


def test_a_failed_job_is_diagnosed_before_the_agent_is_woken(env):
    from ax import job_wake

    jobs.new(env.config, "score", env={"CODEX_THREAD_ID": "th-1"})
    notes = []
    follow_with(env, {1: [{"status": "failed", "message": "exit 1"}]},
                diagnoser=lambda job: "DuckDB API mismatch",
                waker=lambda job: notes.append(job_wake.packet(env.config, job)))  # fmt: skip
    assert "Diagnosis: DuckDB API mismatch" in notes[0]


def test_a_finished_job_needs_no_diagnosis(env):
    jobs.new(env.config, "score", env={"CODEX_THREAD_ID": "th-1"})
    asked = []
    follow_with(env, {1: [{"status": "done"}]}, waker=lambda job: None,
                diagnoser=lambda job: asked.append(job) or "x")  # fmt: skip
    assert asked == []


def test_the_health_check_wakes_the_agent_once_per_problem(env):
    jobs.new(env.config, "score", env={"CODEX_THREAD_ID": "th-1"})
    problems = iter([None, "every row errors with KeyError", "every row errors with KeyError",
                     "disk is full"])  # fmt: skip
    woken, alerts = [], []
    follow_with(env, {15: [{"status": "done"}]}, check_every=180,
                checker=lambda job: next(problems, None), alerter=alerts.append,
                waker=lambda job, note=None: woken.append(note))  # fmt: skip
    looks_wrong = [n for n in woken if n]
    assert len(looks_wrong) == 2 and "every row errors" in looks_wrong[0]
    assert "disk is full" in looks_wrong[1] and len(alerts) == 2
    assert [e["type"] for e in jobs.events(env.config, "score")].count("problem") == 2

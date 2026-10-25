import json
from datetime import UTC, datetime, timedelta

import pytest

from ax import job_eta, jobs

T0 = datetime(2026, 10, 24, 12, tzinfo=UTC)


def points(*pairs):
    """(seconds after T0, done) pairs as progress observations."""
    return [(T0 + timedelta(seconds=s), float(d)) for s, d in pairs]


def test_a_steady_rate_gives_a_centred_interval():
    obs = points(*((60 * i, 10 * i) for i in range(1, 11)))  # 10 units a minute
    eta = job_eta.estimate_from(obs, total=200, now=obs[-1][0])
    assert eta["remaining"]["p50"] == pytest.approx(600, rel=0.05)  # 100 units left
    assert eta["remaining"]["p10"] < eta["remaining"]["p50"] < eta["remaining"]["p90"]
    assert eta["basis"] == "progress"


def test_more_evidence_narrows_the_interval():
    few = points((0, 0), (60, 10), (120, 20))
    many = points(*((60 * i, 10 * i) for i in range(0, 31)))
    width = lambda e: e["remaining"]["p90"] - e["remaining"]["p10"]  # noqa: E731
    a = job_eta.estimate_from(few, total=400, now=few[-1][0])
    b = job_eta.estimate_from(many, total=400 + 280, now=many[-1][0])
    assert width(b) / b["remaining"]["p50"] < width(a) / a["remaining"]["p50"]


def test_a_change_in_rate_uses_the_recent_segment():
    slow = [(60 * i, 1 * i) for i in range(0, 21)]  # 1 a minute for 20 minutes
    fast = [(1200 + 60 * i, 20 + 10 * i) for i in range(1, 11)]  # then 10 a minute
    obs = points(*slow, *fast)
    eta = job_eta.estimate_from(obs, total=220, now=obs[-1][0])
    assert eta["remaining"]["p50"] == pytest.approx(600, rel=0.15)  # 100 left at 10/min
    assert eta["rate_changed"] is True


def test_time_since_the_last_update_counts():
    obs = points((0, 0), (60, 10), (120, 20))
    later = job_eta.estimate_from(obs, total=40, now=obs[-1][0] + timedelta(seconds=600))
    soon = job_eta.estimate_from(obs, total=40, now=obs[-1][0])
    assert later["remaining"]["p50"] > soon["remaining"]["p50"]


def test_no_total_or_no_progress_gives_no_estimate():
    obs = points((0, 0), (60, 10))
    assert job_eta.estimate_from(obs, total=None, now=obs[-1][0]) is None
    assert job_eta.estimate_from(points((0, 0)), total=10, now=T0) is None


def finished_job(env, key, total, minutes, startup=0):
    jobs.new(env.config, key, total=total, unit="rows")
    path = jobs.events_path(env.config, key)
    with jobs.connect(env.config) as db:
        created = T0 - timedelta(days=1)
        db.execute(
            "UPDATE jobs SET created = ?, kind = 'events' WHERE key = ?",
            (jobs.now_iso(created), key),
        )
        db.execute("UPDATE events SET ts = ? WHERE key = ?", (jobs.now_iso(created), key))
    for i in range(1, 11):
        ts = created + timedelta(minutes=startup + minutes * i / 10)
        with jobs.connect(env.config) as db:
            jobs.apply(
                db, (job := jobs._load(db, key)), jobs.Update(done=total * i / 10), jobs.now_iso(ts)
            )
            jobs._save(db, job)
    with jobs.connect(env.config) as db:
        job = jobs._load(db, key)
        jobs.apply(
            db,
            job,
            jobs.Update(status="done"),
            jobs.now_iso(created + timedelta(minutes=startup + minutes)),
        )
        jobs._save(db, job)
    return path


def test_history_gives_an_estimate_before_any_progress(env):
    for n, minutes in enumerate((40, 50, 60)):
        finished_job(env, f"score-{n}", total=1000, minutes=minutes, startup=5)
    job = jobs.new(env.config, "score-9", total=1000, unit="rows")
    eta = job_eta.estimate(env.config, job, now=jobs.parse_iso(job.created))
    assert eta["basis"] == "history"
    assert 45 * 60 < eta["remaining"]["p50"] < 65 * 60  # about 50 min of work plus 5 min startup
    assert eta["similar_jobs"] == 3


def test_a_past_job_whose_progress_all_landed_at_once_still_counts_by_length(env):
    """A run that failed at once records all its progress in one refresh; its rate is
    unknown, but it must not break the estimate of the next job of its family."""
    jobs.new(env.config, "burst-1", total=8, unit="agents")
    created = T0 - timedelta(hours=1)
    with jobs.connect(env.config) as db:
        db.execute("UPDATE jobs SET created = ?, kind = 'events' WHERE key = 'burst-1'",
                   (jobs.now_iso(created),))  # fmt: skip
        job = jobs._load(db, "burst-1")
        for done in (2, 5, 8):  # one timestamp for all of them
            jobs.apply(
                db, job, jobs.Update(done=done), jobs.now_iso(created + timedelta(minutes=1))
            )
        jobs.apply(
            db, job, jobs.Update(status="done"), jobs.now_iso(created + timedelta(minutes=1))
        )
        jobs._save(db, job)
    job = jobs.new(env.config, "burst-2", total=8, unit="agents")
    eta = job_eta.estimate(env.config, job, now=jobs.parse_iso(job.created))
    assert eta is None or eta["basis"] == "history"


def test_calibration_scores_recorded_predictions(env):
    jobs.new(env.config, "cal", total=100)
    with jobs.connect(env.config) as db:
        for minute, (p10, p50, p90) in enumerate(((50, 60, 70), (55, 60, 65), (80, 90, 100))):
            jobs._event(db, "cal", jobs.now_iso(T0 + timedelta(minutes=minute)), "eta",
                        {"finish": {k: jobs.now_iso(T0 + timedelta(minutes=v)) for k, v in
                                    (("p10", p10), ("p50", p50), ("p90", p90))}})  # fmt: skip
    score = job_eta.score(env.config, "cal", finished=T0 + timedelta(minutes=62))
    assert score["predictions"] == 3
    assert score["coverage"] == pytest.approx(2 / 3)  # the last interval missed
    report = job_eta.report(
        env.config, scores=[score, {"predictions": 2, "coverage": 1.0, "median_error_s": 30}]
    )
    assert report["jobs"] == 2 and report["coverage"] == pytest.approx((2 + 2) / 5)


def test_refresh_records_a_prediction_at_most_every_five_minutes(env):
    jobs.new(env.config, "rec", total=100)
    path = jobs.events_path(env.config, "rec")
    for minute in range(0, 12):
        with open(path, "a") as f:
            f.write(json.dumps({"done": (minute + 1) * 5}) + "\n")
        jobs.refresh(env.config, "rec", now=datetime.now(UTC) + timedelta(minutes=minute))
    recorded = [e for e in jobs.events(env.config, "rec", limit=1000) if e["type"] == "eta"]
    assert 2 <= len(recorded) <= 3


def progressing(env, key, total=100, steps=6, every=60):
    """A running job that has gained 10 units a step, ending now."""
    jobs.new(env.config, key, total=total, unit="rows")
    now = datetime.now(UTC)
    with jobs.connect(env.config) as db:
        for i in range(steps):
            job = jobs._load(db, key)
            when = now - timedelta(seconds=every * (steps - 1 - i))
            jobs.apply(db, job, jobs.Update(done=10 * (i + 1)), jobs.now_iso(when))
            jobs._save(db, job)
    return jobs.get(env.config, key)


def cli(env, *args):
    from typer.testing import CliRunner

    from ax.cli import app

    return CliRunner().invoke(app, ["job", *args], env={"AX_CONFIG": str(env.config_path)})


def test_show_and_ls_include_the_estimate(env):
    progressing(env, "score")
    shown = cli(env, "show", "score")
    assert shown.exit_code == 0 and "left (" in shown.output
    data = json.loads(cli(env, "show", "score", "--json").output)
    assert data["eta"]["basis"] == "progress" and data["eta"]["text"].startswith("~")
    listed = cli(env, "ls")
    assert "left" in listed.output.splitlines()[0] and "min" in listed.output


def test_the_dashboard_and_progress_messages_carry_the_estimate(env):
    from ax import job_dash, job_notify

    job = progressing(env, "score")
    server = job_dash.serve(env.config, "score")
    try:
        state = server.state()
    finally:
        server.close()
    assert state["eta"]["text"].startswith("~") and "p50" in state["eta"]["finish"]
    assert all(e["type"] != "eta" for e in state["events"])
    eta = job_eta.estimate(env.config, job)
    assert "left" in job_notify.progress(job, eta=eta)["message"]
    assert "left" not in job_notify.progress(job)["message"]


def test_eta_report_scores_finished_jobs(env):
    progressing(env, "score")
    jobs.refresh(env.config, "score")
    with open(jobs.events_path(env.config, "score"), "a") as f:
        f.write(json.dumps({"done": 100, "exit": 0}) + "\n")
    jobs.refresh(env.config, "score")
    result = cli(env, "eta-report", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["jobs"] == 1 and data["predictions"] >= 1
    assert "coverage" in cli(env, "eta-report").output


def test_a_job_that_outlasts_its_history_gets_no_estimate(env):
    for n, minutes in enumerate((8, 10, 12)):
        finished_job(env, f"build-{n}", total=100, minutes=minutes)
    job = jobs.new(env.config, "build-9", total=100, unit="rows")
    start = jobs.parse_iso(job.created)
    early = job_eta.estimate(env.config, job, now=start + timedelta(minutes=2))
    assert early["basis"] == "history" and early["remaining"]["p50"] > 60
    assert job_eta.estimate(env.config, job, now=start + timedelta(minutes=45)) is None

"""Runwatch runs under ax: a pause wakes the agent without ending the job, chosen cells
wake it as checkpoints, and a run started with `ax job run` is followed as a notebook."""

import json
import os
import signal
import sqlite3
import stat
import sys
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from ax import job_follow, job_sources, job_triage, job_wake, jobs
from ax.cli import app

CELLS = [
    ("c0", "# Train", "markdown"),
    ("c1", "Train", "code"),
    ("c2", "Train", "code"),
    ("c3", "Evaluate", "code"),
    ("c4", "Evaluate", "code"),
    ("c5", "Release", "code"),
]
ERROR = (
    "ClientError",
    "An error occurred (AccessDeniedException) when calling the GetAuthorizationToken operation",
    ["Traceback (most recent call last):", '  File "<cell>", line 4', "ClientError: denied"],
)
PAUSED = "Run paused after a cell failure"
SESSION = {"CLAUDE_CODE_SESSION_ID": "s-1"}


class Run:
    """A Runwatch run folder the stub reports from; each `write` is one moment of the run."""

    def __init__(self, folder):
        self.folder = folder
        self.cells = list(CELLS)
        folder.mkdir(parents=True)
        self.write()

    def write(self, status="running", epoch=1, cells=None, live=True, message=None,
              error=None, outputs=None):  # fmt: skip
        """`cells` maps a cell id to its status, or to (status, attempt)."""
        rows = []
        for index, (cell_id, label, kind) in enumerate(self.cells):
            given = (cells or {}).get(cell_id, "skipped" if kind == "markdown" else "pending")
            state, attempt = given if isinstance(given, tuple) else (given, None)
            if attempt is None:
                attempt = 1 if state in ("succeeded", "failed", "running") else 0
            rows.append({
                "cell_id": cell_id, "cell_index": index, "label": label, "status": state,
                "attempt": attempt, "kernel_epoch": epoch, "skip_reason": None, "parents": [],
                "error_type": error[0] if error and state == "failed" else None,
            })  # fmt: skip
        failed = next((r for r in rows if r["status"] == "failed"), None)
        current = next((r for r in rows if r["status"] in ("running", "failed")), None)
        run = {
            "name": "train", "status": status, "message": message, "kernel_epoch": epoch,
            "current_cell_index": current["cell_index"] if current else None,
            "failed_cell_index": failed["cell_index"] if failed else None,
            "created_at": datetime.now(UTC).isoformat(),
        }  # fmt: skip
        commands = {"resume": f"runwatch resume {self.folder}",
                    "restart": f"runwatch restart {self.folder}"}  # fmt: skip
        self._json("status.json", {"schema_version": 2, "run": run, "controller_live": live})
        self._json("context.json", {
            "schema_version": 2, "run": run, "failed_cell": failed,
            "failed_cells": [failed] if failed else [], "cells": rows, "recent_events": [],
            "suggested_commands": commands,
        })  # fmt: skip
        (self.folder / "events.jsonl").write_text("")
        notebook = {
            "nbformat": 4, "nbformat_minor": 5, "metadata": {},
            "cells": [{"id": cell_id, "cell_type": kind, "metadata": {}, "source": "",
                       "outputs": (outputs or {}).get(cell_id, [])}
                      for cell_id, _, kind in self.cells],
        }  # fmt: skip
        self._json("executed.partial.ipynb", notebook)
        db = sqlite3.connect(self.folder / "runwatch.sqlite3")
        db.execute("DROP TABLE IF EXISTS cells")
        db.execute("CREATE TABLE cells (run_id TEXT, cell_index INTEGER, cell_id TEXT, "
                   "error_name TEXT, error_value TEXT, traceback_json TEXT)")  # fmt: skip
        if failed and error:
            db.execute("INSERT INTO cells VALUES ('r', ?, ?, ?, ?, ?)",
                       (failed["cell_index"], failed["cell_id"], error[0], error[1],
                        json.dumps(error[2])))  # fmt: skip
        db.commit()
        db.close()

    def _json(self, name, data):
        (self.folder / name).write_text(json.dumps(data))


@pytest.fixture
def rw(tmp_path):
    """A run folder and a stub `runwatch` whose execute runs a minute and whose status,
    context and events print the run's files."""
    stub = tmp_path / "bin" / "runwatch"
    stub.parent.mkdir()
    stub.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys, time\n"
        "if sys.argv[1] == 'execute':\n"
        "    print('Runwatch run directory:', os.environ.get('STUB_RUN', ''), flush=True)\n"
        "    time.sleep(60)\n"
        "    sys.exit(0)\n"
        "names = {'status': 'status.json', 'context': 'context.json', 'events': 'events.jsonl'}\n"
        "sys.stdout.write((pathlib.Path(sys.argv[2]) / names[sys.argv[1]]).read_text())\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    repo = tmp_path / "repo"
    run = Run(repo / ".runwatch" / "runs" / "train-1")
    return SimpleNamespace(stub=stub, repo=repo, run=run)


class Clock:
    """Refreshes far enough apart that every one checks the run."""

    def __init__(self):
        self.seconds = 0

    def refresh(self, env, key="train"):
        self.seconds += 30
        return jobs.refresh(
            env.config, key, now=datetime.now(UTC) + timedelta(seconds=self.seconds)
        )


def watch(env, rw, key="train", agent=SESSION):
    options = {"runwatch": str(rw.stub)}
    return jobs.watch(env.config, "runwatch", str(rw.run.folder), key=key, options=options,
                      env=agent)  # fmt: skip


def of_type(env, type_, key="train"):
    return [e["data"] for e in jobs.events(env.config, key) if e["type"] == type_]


def paused(rw, attempt=1, **kw):
    rw.run.write(status="paused", message=PAUSED, error=ERROR,
                 cells={"c1": "succeeded", "c2": ("failed", attempt)}, **kw)  # fmt: skip


# A pause is a problem, not the end of the job


def test_a_pause_wakes_the_agent_and_the_job_keeps_watching_the_run(env, rw):
    clock = Clock()
    watch(env, rw)
    paused(rw)
    job = clock.refresh(env)
    assert job.status == "running" and job.stage == "paused at cell 2"
    [problem] = of_type(env, "problem")
    assert problem["text"] == "paused at cell 2 (Train): ClientError"
    assert "AccessDeniedException" in problem["details"]
    assert "ClientError: denied" in problem["details"]  # the traceback's end
    assert "runwatch resume" in problem["details"] and "runwatch restart" in problem["details"]
    clock.refresh(env)
    assert len(of_type(env, "problem")) == 1  # one pause, one problem

    rw.run.write(cells={"c1": "succeeded", "c2": ("running", 2)}, message="Notebook is running")
    job = clock.refresh(env)
    assert (job.status, job.stage) == ("running", "cell 2")
    paused(rw, attempt=2)
    clock.refresh(env)
    assert len(of_type(env, "problem")) == 2  # the retry paused again

    paused(rw, attempt=3)
    clock.refresh(env)
    everything = {cell_id: "succeeded" for cell_id, _, kind in CELLS if kind == "code"}
    rw.run.write(status="succeeded", cells=everything, message="Run completed successfully")
    job = clock.refresh(env)  # resumed and finished between two checks
    assert (job.status, job.stage) == ("done", "succeeded")


def test_a_run_watched_while_paused_reports_the_pause_at_once(env, rw):
    paused(rw)
    job = watch(env, rw)
    assert job.status == "running" and len(of_type(env, "problem")) == 1


def test_without_its_database_a_pause_still_names_the_cell_and_error_type(env, rw):
    clock = Clock()
    watch(env, rw)
    paused(rw)
    (rw.run.folder / "runwatch.sqlite3").write_text("not a database")
    clock.refresh(env)
    [problem] = of_type(env, "problem")
    assert problem["text"] == "paused at cell 2 (Train): ClientError"
    assert "runwatch context" in problem["details"]


def test_a_pause_read_once_without_its_details_is_still_one_pause(env, rw):
    clock = Clock()
    watch(env, rw)
    paused(rw)
    clock.refresh(env)
    context = rw.run.folder / "context.json"
    saved = context.read_text()
    context.unlink()  # `runwatch context` fails on this check
    assert clock.refresh(env).stage == "paused at cell 2"
    context.write_text(saved)
    clock.refresh(env)
    assert len(of_type(env, "problem")) == 1


def test_wait_returns_on_a_pause_and_leaves_the_job_running(env, rw):
    watch(env, rw)
    paused(rw)
    fake = SimpleNamespace(now=datetime.now(UTC).timestamp() + 30)

    def sleep(seconds):
        fake.now += 15

    outcome, job = jobs.wait(env.config, "train", clock=lambda: fake.now, sleep=sleep, timeout=120)
    assert outcome == "problem" and job.status == "running"
    note = jobs.wait_note(env.config, job, outcome)
    assert "paused at cell 2 (Train): ClientError" in note
    assert "runwatch resume" in note and "ax job wait train" in note


# Checkpoints


def outputs(text):
    return [
        {"output_type": "stream", "name": "stdout", "text": [text]},
        {"output_type": "display_data", "metadata": {},
         "data": {"image/png": "iVBOR", "text/plain": ["<Figure size 640x480>"]}},
    ]  # fmt: skip


def test_a_checkpoint_cell_wakes_once_per_run_of_it_with_its_outputs(env, rw):
    clock = Clock()
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["3"])
    clock.refresh(env)
    assert of_type(env, "checkpoint") == []
    done = {"c1": "succeeded", "c2": "succeeded", "c3": "succeeded", "c4": "running"}
    rw.run.write(cells=done, outputs={"c3": outputs("AUC 0.91\n")})
    job = clock.refresh(env)
    [reached] = of_type(env, "checkpoint")
    assert job.status == "running" and reached["text"] == "reached cell 3 (Evaluate)"
    assert "AUC 0.91" in reached["details"] and "image/png" in reached["details"]
    clock.refresh(env)
    assert len(of_type(env, "checkpoint")) == 1

    rw.run.write(epoch=2, cells={"c1": "succeeded", "c2": "running"})  # a restart
    clock.refresh(env)
    assert len(of_type(env, "checkpoint")) == 1
    rw.run.write(epoch=2, cells=done, outputs={"c3": outputs("AUC 0.93\n")})
    clock.refresh(env)
    assert "AUC 0.93" in of_type(env, "checkpoint")[-1]["details"]


def test_a_section_checkpoint_waits_for_every_cell_of_the_section(env, rw):
    clock = Clock()
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["evaluate"])
    rw.run.write(cells={"c1": "succeeded", "c2": "succeeded", "c3": "succeeded", "c4": "running"})
    clock.refresh(env)
    assert of_type(env, "checkpoint") == []
    rw.run.write(cells={"c1": "succeeded", "c2": "succeeded", "c3": "succeeded",
                        "c4": "succeeded"}, outputs={"c4": outputs("report saved\n")})  # fmt: skip
    clock.refresh(env)
    [reached] = of_type(env, "checkpoint")
    assert reached["text"] == "reached the end of section Evaluate"
    assert "report saved" in reached["details"]


def test_a_checkpoint_set_by_index_follows_its_cell_when_cells_are_added(env, rw):
    clock = Clock()
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["3"])
    clock.refresh(env)  # resolves cell 3 to its id
    rw.run.cells.insert(3, ("n1", "Train", "code"))  # the agent adds a cell before it
    rw.run.write(cells={"c1": "succeeded", "c2": "succeeded", "n1": "succeeded"})
    clock.refresh(env)
    assert of_type(env, "checkpoint") == []
    rw.run.write(cells={"c1": "succeeded", "c2": "succeeded", "n1": "succeeded",
                        "c3": "succeeded"})  # fmt: skip
    clock.refresh(env)
    assert [c["text"] for c in of_type(env, "checkpoint")] == ["reached cell 4 (Evaluate)"]


def test_checkpoints_reach_a_run_watched_before_they_existed(env, rw):
    watch(env, rw)
    with jobs.connect(env.config) as db:  # as a job registered before checkpoints were
        job = jobs._load(db, "train")
        del job.spec["folder"]
        jobs._save(db, job)
    jobs.set_wake_at(env.config, "train", ["3"])
    rw.run.write(cells={"c1": "succeeded", "c2": "succeeded", "c3": "succeeded"})
    Clock().refresh(env)
    assert [c["text"] for c in of_type(env, "checkpoint")] == ["reached cell 3 (Evaluate)"]


def test_a_checkpoint_that_matches_no_cell_is_a_problem_reported_once(env, rw):
    clock = Clock()
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["Evalute"], check=False)
    clock.refresh(env)
    clock.refresh(env)
    [problem] = of_type(env, "problem")
    assert "Evalute" in problem["text"] and "matches no cell" in problem["text"]
    assert "Evaluate" in problem["details"]  # the sections it could have meant


def test_set_wake_at_refuses_a_cell_the_run_does_not_have(env, rw):
    watch(env, rw)
    with pytest.raises(ValueError, match="matches no cell"):
        jobs.set_wake_at(env.config, "train", ["Evalute"])
    assert jobs.set_wake_at(env.config, "train", ["3", "c5", "Release"]) == [
        "cell 3 (Evaluate)", "cell 5 (Release)", "the end of section Release",
    ]  # fmt: skip


def test_wait_returns_at_a_checkpoint(env, rw):
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["3"])
    rw.run.write(cells={"c1": "succeeded", "c2": "succeeded", "c3": "succeeded"},
                 outputs={"c3": outputs("AUC 0.91\n")})  # fmt: skip
    fake = SimpleNamespace(now=datetime.now(UTC).timestamp() + 30)

    def sleep(seconds):
        fake.now += 15

    outcome, job = jobs.wait(env.config, "train", clock=lambda: fake.now, sleep=sleep, timeout=120)
    assert outcome == "checkpoint" and job.status == "running"
    assert jobs.WAIT_CODES["checkpoint"] == 7
    note = jobs.wait_note(env.config, job, outcome)
    assert "reached cell 3 (Evaluate)" in note and "AUC 0.91" in note
    assert "ax job wait train" in note


def test_a_wait_reports_everything_seen_since_it_started(env, rw):
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["3"])
    rw.run.write(status="paused", message=PAUSED, error=ERROR,
                 cells={"c1": "succeeded", "c2": "succeeded", "c3": "succeeded", "c4": "failed"},
                 outputs={"c3": outputs("AUC 0.91\n")})  # fmt: skip
    fake = SimpleNamespace(now=float(int(datetime.now(UTC).timestamp())) + 30)
    start = fake.now

    def sleep(seconds):
        fake.now += 15

    outcome, job = jobs.wait(env.config, "train", clock=lambda: fake.now, sleep=sleep, timeout=120)
    assert outcome == "problem"
    note = jobs.wait_note(env.config, job, outcome, since=start)
    assert "reached cell 3 (Evaluate)" in note and "AUC 0.91" in note
    assert "paused at cell 4 (Evaluate): ClientError" in note


def test_a_returned_wait_covers_everything_it_reported(env, rw):
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["3"])
    rw.run.write(status="paused", message=PAUSED, error=ERROR,
                 cells={"c1": "succeeded", "c2": "succeeded", "c3": "succeeded", "c4": "failed"})  # fmt: skip
    outcome, _ = jobs.wait(env.config, "train", env=SESSION, interval=0.01, timeout=30,
                           clock=lambda: datetime.now(UTC).timestamp() + 60)  # fmt: skip
    assert outcome == "problem"
    for type_ in ("checkpoint", "problem"):
        seen = jobs.latest_event(env.config, "train", type_, full=True)
        assert jobs.covered(env.config, "train", SESSION, seen, type_)


# The follower wakes the agent


class RunTimeline:
    """A fake clock whose sleeps move the run to scripted states."""

    def __init__(self, script):
        self.now = datetime.now(UTC).timestamp()
        self.script = script
        self.sleeps = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        if self.sleeps in self.script:
            self.script[self.sleeps]()


def follow(env, script, **hooks):
    timeline = RunTimeline(script)
    options = job_follow.FollowOptions(dashboard=False, interval=30, linger=30, wake="auto")
    return job_follow.follow(env.config, "train", options, clock=timeline, sleep=timeline.sleep,
                             diagnoser=lambda job: None, **hooks)  # fmt: skip


def finished(rw):
    rw.run.write(status="succeeded", message="Run completed successfully",
                 cells={cell_id: "succeeded" for cell_id, _, kind in CELLS if kind == "code"})  # fmt: skip


def test_the_follower_wakes_the_agent_at_each_pause_and_checkpoint(env, rw):
    watch(env, rw)
    jobs.set_wake_at(env.config, "train", ["3"])
    woken, alerts = [], []

    def waker(job, note=None, details=None):
        woken.append((note, details))

    script = {
        1: lambda: paused(rw),
        3: lambda: rw.run.write(cells={"c1": "succeeded", "c2": ("running", 2)}),
        4: lambda: rw.run.write(cells={"c1": "succeeded", "c2": ("succeeded", 2),
                                       "c3": "succeeded"}, outputs={"c3": outputs("AUC\n")}),
        6: lambda: finished(rw),
    }  # fmt: skip
    assert follow(env, script, waker=waker, alerter=alerts.append) == "done"
    notes = [note for note, _ in woken]
    assert notes == ["paused at cell 2 (Train): ClientError", "reached cell 3 (Evaluate)", None]
    assert "AccessDeniedException" in woken[0][1] and "AUC" in woken[1][1]
    assert alerts == []  # the agent was reached


def test_the_wake_note_for_a_pause_carries_the_details_not_the_generic_advice(env, rw):
    watch(env, rw)
    paused(rw)
    job = Clock().refresh(env)
    [problem] = of_type(env, "problem")
    note = job_wake.packet(env.config, job, problem["text"], details=problem["details"])
    assert note.startswith("[ax job] paused at cell 2 (Train): ClientError")
    assert "AccessDeniedException" in note and "runwatch resume" in note
    assert "decide whether to keep waiting" not in note


def test_a_pause_nobody_will_be_woken_for_reaches_the_user(env, rw):
    watch(env, rw)
    alerts = []
    timeline = RunTimeline({1: lambda: paused(rw), 3: lambda: finished(rw)})
    options = job_follow.FollowOptions(dashboard=False, interval=30, linger=30)
    job_follow.follow(env.config, "train", options, clock=timeline, sleep=timeline.sleep,
                      alerter=alerts.append)  # fmt: skip
    assert [a["message"] for a in alerts] == ["paused at cell 2 (Train): ClientError"]


def test_an_attached_wait_from_the_same_session_takes_the_place_of_the_wake(env, rw):
    watch(env, rw)
    woken = []
    started = datetime.now(UTC) - timedelta(minutes=1)
    with jobs.waiting(env.config, "train", env=SESSION, start=started):
        follow(env, {1: lambda: paused(rw), 3: lambda: finished(rw)},
               waker=lambda job, note=None, details=None: woken.append(note))  # fmt: skip
    assert woken == []
    assert len(of_type(env, "wake_skipped")) == 2  # the pause and the end


def test_a_wait_from_another_session_does_not_stop_the_wake(env, rw):
    watch(env, rw)
    woken = []
    started = datetime.now(UTC) - timedelta(minutes=1)
    with jobs.waiting(env.config, "train", env={"CLAUDE_CODE_SESSION_ID": "s-2"}, start=started):
        follow(env, {1: lambda: paused(rw), 3: lambda: finished(rw)},
               waker=lambda job, note=None, details=None: woken.append(note))  # fmt: skip
    assert woken == ["paused at cell 2 (Train): ClientError", None]


def test_a_wait_that_already_returned_the_ending_covers_the_end_wake(env):
    jobs.new(env.config, "score", env=SESSION)
    with open(jobs.events_path(env.config, "score"), "a") as f:
        f.write(json.dumps({"status": "failed"}) + "\n")
    outcome, _ = jobs.wait(env.config, "score", env=SESSION, interval=0.01, timeout=5)
    assert outcome == "failed"
    woken = []
    timeline = RunTimeline({})
    options = job_follow.FollowOptions(dashboard=False, interval=30, linger=30, wake="auto")
    job_follow.follow(env.config, "score", options, clock=timeline, sleep=timeline.sleep,
                      diagnoser=lambda job: None, waker=lambda job, note=None: woken.append(job))  # fmt: skip
    assert woken == [] and len(of_type(env, "wake_skipped", key="score")) == 1


def test_a_finished_wait_leaves_no_waiter_behind(env):
    jobs.new(env.config, "score", env=SESSION)
    jobs.wait(env.config, "score", env=SESSION, interval=0.01, timeout=0.05)
    folder = jobs.events_path(env.config, "score").parent / "waiters"
    assert not folder.exists() or list(folder.iterdir()) == []


# Haiku reads the notebook


def test_haiku_reads_the_notebooks_state_not_only_the_output(env, rw):
    watch(env, rw)
    rw.run.write(cells={"c1": "succeeded", "c2": "running"}, message="Notebook is running")
    text = job_triage.tail(env.config, jobs.get(env.config, "train"))
    assert "Notebook is running" in text and "cell 2 (Train)" in text


# `ax job run -- runwatch execute ...`


def test_a_runwatch_launch_is_found_inside_a_command(rw):
    cwd = str(rw.repo)
    wrapped = ["uv", "run", "python", "scripts/aws_ds.py", "--", "env", "A=1", str(rw.stub),
               "execute", "nb.ipynb", "--config", "c.yaml", "--run-dir", ".runwatch/runs/r5",
               "--share", "lan"]  # fmt: skip
    assert job_sources.runwatch_launch(wrapped, cwd, {}) == {
        "binary": str(rw.stub), "run": str(rw.repo / ".runwatch" / "runs" / "r5"),
    }  # fmt: skip
    on_path = {"PATH": str(rw.stub.parent)}
    assert job_sources.runwatch_launch(["runwatch", "execute", "nb.ipynb", "--run-dir=out"],
                                       cwd, on_path) == {
        "binary": str(rw.stub), "run": str(rw.repo / "out"),
    }  # fmt: skip
    assert job_sources.runwatch_launch(["runwatch", "execute", "nb.ipynb"], cwd, on_path) == {
        "binary": str(rw.stub), "run": None,
    }  # fmt: skip
    assert job_sources.runwatch_launch(["python", "train.py", "--run-dir", "x"], cwd, {}) is None
    assert job_sources.runwatch_launch(["runwatch", "status", "x"], cwd, on_path) is None


def test_a_run_job_follows_the_notebook_runwatch_runs(env, rw):
    argv = [str(rw.stub), "execute", "nb.ipynb", "--run-dir", str(rw.run.folder)]
    job = jobs.run(env.config, argv, key="train", cwd=str(rw.repo), env=SESSION)
    try:
        assert job.spec["runwatch"]["run"] == str(rw.run.folder)
        clock = Clock()
        paused(rw)
        job = clock.refresh(env)
        assert (job.status, job.stage) == ("running", "paused at cell 2")
        assert len(of_type(env, "problem")) == 1
        finished(rw)
        assert clock.refresh(env).status == "done"
    finally:
        os.kill(job.spec["pid"], signal.SIGTERM)


def test_a_run_job_finds_the_run_folder_runwatch_chose_in_its_output(env, rw, monkeypatch):
    monkeypatch.setenv("STUB_RUN", str(rw.run.folder))
    job = jobs.run(env.config, [str(rw.stub), "execute", "nb.ipynb"], key="train",
                   cwd=str(rw.repo), env=SESSION)  # fmt: skip
    try:
        log = jobs.events_path(env.config, "train").parent / "output.log"
        for _ in range(100):
            if log.exists() and "Runwatch run directory" in log.read_text():
                break
            time.sleep(0.05)
        paused(rw)
        job = Clock().refresh(env)
        assert job.spec["runwatch"]["run"] == str(rw.run.folder)
        assert job.stage == "paused at cell 2"
    finally:
        os.kill(job.spec["pid"], signal.SIGTERM)


def test_watch_finds_runwatch_through_an_earlier_job(env, rw, monkeypatch):
    monkeypatch.delenv("AX_RUNWATCH", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    watch(env, rw, key="first")
    job = jobs.watch(env.config, "runwatch", str(rw.run.folder), key="second")
    assert job.spec["binary"] == str(rw.stub)


# The command line


def cli(env, *args, extra=None):
    environ = {"AX_CONFIG": str(env.config_path), "CLAUDE_CODE_SESSION_ID": "", **(extra or {})}
    return CliRunner().invoke(app, ["job", *args], env=environ)


@pytest.fixture
def followers(monkeypatch):
    started = []

    def start(config, key, args):
        started.append((key, args))
        return {"link": "http://127.0.0.1:1/"}

    monkeypatch.setattr(job_follow, "start_detached", start)
    return started


def test_runwatch_jobs_from_an_agent_session_wake_it(env, rw, followers):
    run = str(rw.run.folder)
    result = cli(env, "watch", "runwatch", run, "--key", "train", "--label", "Train",
                 "--runwatch", str(rw.stub), extra=SESSION)  # fmt: skip
    assert result.exit_code == 0, result.output
    key, args = followers[0]
    assert key == "train" and args[args.index("--wake") + 1] == "auto"
    result = cli(env, "watch", "runwatch", run, "--key", "quiet", "--label", "Train",
                 "--runwatch", str(rw.stub), "--wake", "none", extra=SESSION)  # fmt: skip
    assert result.exit_code == 0 and "--wake" in result.stderr  # no opting out any more
    key, args = followers[-1]
    assert key == "quiet" and args[args.index("--wake") + 1] == "auto"


def test_watch_takes_checkpoints_and_refuses_unknown_ones(env, rw, followers):
    run = str(rw.run.folder)
    result = cli(env, "watch", "runwatch", run, "--key", "train", "--label", "Train",
                 "--runwatch", str(rw.stub), "--wake-at", "3,4", "--wake-at", "Release")  # fmt: skip
    assert result.exit_code == 0, result.output
    assert jobs.wake_at(env.config, "train") == ["3", "4", "Release"]
    result = cli(env, "watch", "runwatch", run, "--key", "typo", "--label", "Train",
                 "--runwatch", str(rw.stub), "--wake-at", "Evalute")  # fmt: skip
    assert result.exit_code == 2 and "matches no cell" in result.stderr


def test_checkpoints_change_while_the_run_goes(env, rw):
    watch(env, rw)
    result = cli(env, "wake-at", "train", "3", "Release")
    assert result.exit_code == 0, result.output
    assert "cell 3 (Evaluate)" in result.stdout and "section Release" in result.stdout
    result = cli(env, "wake-at", "train", "Evalute")
    assert result.exit_code == 2 and "matches no cell" in result.stderr
    assert jobs.wake_at(env.config, "train") == ["3", "Release"]  # unchanged
    assert cli(env, "wake-at", "train", "--clear").exit_code == 0
    assert jobs.wake_at(env.config, "train") == []

"""The Runwatch and Tools MCP sources, against a stub runwatch and a fake state folder."""

import json
import stat
import sys
from datetime import UTC, datetime, timedelta

import pytest

from ax import jobs

# Tools MCP


def tools_job(root, job_id="0348e19e939a46d58bee2b0dbb9535b6", **fields):
    folder = root / "jobs" / job_id
    folder.mkdir(parents=True, exist_ok=True)
    record = {
        "job_id": job_id, "kind": "annotation", "status": "running", "stage": "annotating",
        "completed": 40, "total": 100, "error": None, "updated_at": "2026-10-24T12:00:00Z",
        **fields,
    }  # fmt: skip
    (folder / "job.json").write_text(json.dumps(record))
    return job_id


def test_a_tools_mcp_job_reports_its_rows_and_stage(env, tmp_path):
    job_id = tools_job(tmp_path)
    job = jobs.watch(env.config, "tools", job_id, options={"state_root": str(tmp_path)})
    assert job.key == "tools-0348e19e939a"
    assert (job.status, job.done, job.total, job.stage) == ("running", 40, 100, "annotating")
    tools_job(tmp_path, status="succeeded", completed=100, stage="success")
    assert jobs.refresh(env.config, job.key).status == "done"


@pytest.mark.parametrize(
    ("status", "error", "expected", "words"),
    [
        ("succeeded_with_errors", None, "done", "some rows failed"),
        ("failed", "provider refused", "failed", "provider refused"),
        ("cancelled", None, "stopped", None),
        ("interrupted", None, "ended", "tools_resume_job"),
    ],
)
def test_tools_mcp_endings(env, tmp_path, status, error, expected, words):
    job_id = tools_job(tmp_path)
    job = jobs.watch(env.config, "tools", job_id, options={"state_root": str(tmp_path)})
    tools_job(tmp_path, status=status, error=error)
    job = jobs.refresh(env.config, job.key)
    assert job.status == expected
    assert words is None or words in job.message


def test_an_unknown_tools_mcp_job_is_refused(env, tmp_path):
    with pytest.raises(ValueError, match="no Tools MCP job"):
        jobs.watch(env.config, "tools", "abc123", options={"state_root": str(tmp_path)})


# Runwatch


@pytest.fixture
def runwatch(tmp_path):
    """A run folder and a stub `runwatch` that prints status.json and events.jsonl from it."""
    run = tmp_path / ".runwatch" / "runs" / "train-1"
    run.mkdir(parents=True)
    (run / "runwatch.sqlite3").write_text("")
    stub = tmp_path / "runwatch"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "command, run = sys.argv[1], pathlib.Path(sys.argv[2])\n"
        "name = {'status': 'status.json', 'events': 'events.jsonl'}[command]\n"
        "sys.stdout.write((run / name).read_text())\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def state(status="running", cell=3, failed=None, live=True, message=None, progress=(),
              created=None):  # fmt: skip
        payload = {
            "run": {"name": "Train", "status": status, "message": message,
                    "current_cell_index": cell, "failed_cell_index": failed,
                    "created_at": (created or datetime.now(UTC)).isoformat()},
            "controller_live": live,
        }  # fmt: skip
        (run / "status.json").write_text(json.dumps(payload))
        lines = [
            {"seq": i, "type": "notebook.progress", "data": data}
            for i, data in enumerate(progress, start=1)
        ]
        (run / "events.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    state()
    return run, stub, state


def later(seconds):
    return datetime.now(UTC) + timedelta(seconds=seconds)


def test_a_runwatch_run_reports_its_cell_and_bar(env, runwatch):
    run, stub, state = runwatch
    state(progress=[
        {"cell_index": 2, "completed": 9, "total": 9, "unit": "fold"},
        {"cell_index": 3, "completed": 2, "total": 5, "unit": "trial"},
    ])  # fmt: skip
    job = jobs.watch(env.config, "runwatch", str(run), options={"runwatch": str(stub)})
    assert job.key == "runwatch-train-1"
    assert (job.status, job.stage, job.done, job.total, job.unit) == (
        "running", "cell 3", 2, 5, "trial",
    )  # fmt: skip
    state(status="succeeded", cell=None, message="Run completed successfully")
    assert jobs.refresh(env.config, job.key, now=later(60)).status == "done"


def test_a_paused_runwatch_run_needs_its_agent(env, runwatch):
    run, stub, state = runwatch
    job = jobs.watch(env.config, "runwatch", str(run), options={"runwatch": str(stub)})
    state(status="paused", cell=None, failed=7, message="Run paused after a cell failure")
    job = jobs.refresh(env.config, job.key, now=later(60))
    assert job.status == "failed" and "cell 7" in job.message and "runwatch resume" in job.message


def test_a_run_whose_controller_died_is_a_check_error(env, runwatch):
    run, stub, state = runwatch
    job = jobs.watch(env.config, "runwatch", str(run), options={"runwatch": str(stub)})
    state(live=False)
    job = jobs.refresh(env.config, job.key, now=later(60))
    assert job.status == "running" and "controller" in job.check_error


def test_a_run_that_never_left_created_is_a_failed_start(env, runwatch):
    run, stub, state = runwatch
    state(status="created", cell=None, live=False, message="Run created")
    job = jobs.watch(env.config, "runwatch", str(run), options={"runwatch": str(stub)})
    assert job.status == "running" and job.stage == "created"  # still launching
    state(status="created", cell=None, live=False, message="Run created", created=later(-600))
    job = jobs.refresh(env.config, job.key, now=later(60))
    assert job.status == "failed" and job.message.startswith("never started")
    assert "10 min ago" in job.message and "launched it" in job.message


def test_runwatch_needs_a_run_folder_and_its_command(env, runwatch, tmp_path):
    run, stub, _ = runwatch
    with pytest.raises(ValueError, match="not a Runwatch run"):
        jobs.watch(env.config, "runwatch", str(tmp_path), options={"runwatch": str(stub)})
    with pytest.raises(ValueError, match="runwatch command"):
        jobs.watch(env.config, "runwatch", str(run), options={"runwatch": str(tmp_path / "no")})

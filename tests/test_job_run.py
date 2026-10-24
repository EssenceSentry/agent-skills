import os
import signal
import sys
import time

import pytest
from typer.testing import CliRunner

from ax import jobs
from ax.cli import app


def finish(env, key, timeout=20):
    outcome, job = jobs.wait(env.config, key, timeout=timeout, interval=0.1)
    return outcome, job


def output(env, key):
    log = jobs.events_path(env.config, key).parent / "output.log"
    return log.read_text() if log.exists() else ""


def test_a_command_runs_detached_and_its_exit_code_ends_the_job(env):
    job = jobs.run(env.config, [sys.executable, "-c", "print('hello')"], key="hello")
    assert (job.kind, job.status) == ("run", "running")
    outcome, job = finish(env, "hello")
    assert outcome == "done"
    assert "hello" in output(env, "hello")


def test_a_failing_command_fails_the_job_with_its_code(env):
    jobs.run(env.config, [sys.executable, "-c", "import sys; sys.exit(3)"], key="bad")
    outcome, job = finish(env, "bad")
    assert outcome == "failed" and "3" in job.message


def test_a_missing_command_fails_with_a_clear_message(env):
    jobs.run(env.config, ["definitely-not-a-command-ax"], key="missing")
    outcome, job = finish(env, "missing")
    assert outcome == "failed" and "not found" in job.message


def test_a_heredoc_on_stdin_is_replayed_to_the_command(env):
    script = b"import os, json\nprint('from heredoc')\n"
    jobs.run(env.config, [sys.executable, "-"], key="heredoc", stdin=script)
    assert finish(env, "heredoc")[0] == "done"
    assert "from heredoc" in output(env, "heredoc")


def test_the_command_can_report_progress_through_its_events_file(env):
    script = (
        "import json, os\n"
        "with open(os.environ['AX_JOB_FILE'], 'a') as f:\n"
        "    f.write(json.dumps({'done': 5, 'total': 5, 'stage': 'scored'}) + '\\n')\n"
    )
    jobs.run(env.config, [sys.executable, "-c", script], key="progress")
    outcome, job = finish(env, "progress")
    assert (outcome, job.done, job.total, job.stage) == ("done", 5, 5, "scored")


def test_a_killed_runner_ends_the_job(env):
    job = jobs.run(env.config, [sys.executable, "-c", "import time; time.sleep(30)"], key="slow")
    os.kill(job.spec["pid"], signal.SIGKILL)
    outcome, job = finish(env, "slow")
    assert outcome == "ended"


def test_stopping_the_runner_stops_the_command_and_records_it(env):
    script = "import time; print('started', flush=True); time.sleep(30)"
    job = jobs.run(env.config, [sys.executable, "-c", script], key="term")
    deadline = time.time() + 20
    while "started" not in output(env, "term") and time.time() < deadline:
        time.sleep(0.05)
    os.kill(job.spec["pid"], signal.SIGTERM)
    outcome, job = finish(env, "term")
    assert outcome == "failed" and "signal 15" in job.message


def test_generated_keys_name_the_command(env):
    job = jobs.run(env.config, [sys.executable, "-c", "pass"])
    assert job.key.startswith("python")


def test_cli_run_takes_a_heredoc_and_prints_the_key(env):
    result = CliRunner().invoke(
        app,
        ["job", "run", "--key", "cli-heredoc", "--", sys.executable, "-"],
        input="print('piped in')\n",
        env={"AX_CONFIG": str(env.config_path)},
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "cli-heredoc"
    assert finish(env, "cli-heredoc")[0] == "done"
    assert "piped in" in output(env, "cli-heredoc")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" 45%|####5     | 450/1000 [00:10<00:12, 44.2it/s]", (450, 1000, None, None)),
        (
            "x\rScoring:  10%|#  | 1.50k/15.0k [00:01<00:09, 1.5krows/s]",
            (1500, 15000, "rows", "Scoring"),
        ),
        ("load: 450file [00:10, 44.2file/s]\r", (450, None, "file", "load")),
        ("  0%|          | 0/40 [00:00<?, ?it/s]", (0, 40, None, None)),
        ("plain output, 3/4 done\n", None),
    ],
)
def test_progress_bars_are_read_from_output(text, expected):
    from ax.job_sources import parse_bar

    found = parse_bar(text)
    got = None if found is None else (found.done, found.total, found.unit, found.stage)
    assert got == expected


def test_a_progress_bar_in_the_output_counts_as_progress(env):
    script = (
        "import sys, time\n"
        "for i in range(5):\n"
        "    sys.stderr.write(f'\\rScoring: {i * 10}%|#  | {i}/10 [00:01<00:02, 4.00rows/s]')\n"
        "    sys.stderr.flush()\n"
        "time.sleep(60)\n"
    )
    job = jobs.run(env.config, [sys.executable, "-c", script], key="bar")
    deadline = time.time() + 15
    while job.done != 4 and time.time() < deadline:
        time.sleep(0.2)
        job = jobs.refresh(env.config, "bar")
    os.kill(job.spec["pid"], signal.SIGTERM)
    finish(env, "bar")
    assert (job.done, job.total, job.unit, job.stage) == (4, 10, "rows", "Scoring")


def test_progress_the_command_reports_itself_wins_over_its_output(env):
    script = (
        "import json, os, sys, time\n"
        "with open(os.environ['AX_JOB_FILE'], 'a') as f:\n"
        "    f.write(json.dumps({'done': 7, 'total': 70}) + '\\n')\n"
        "sys.stderr.write('\\r 50%|#  | 1/2 [00:01<00:01, 1.00it/s]')\n"
        "sys.stderr.flush()\n"
        "time.sleep(60)\n"
    )
    job = jobs.run(env.config, [sys.executable, "-c", script], key="own")
    deadline = time.time() + 15
    while "1/2" not in output(env, "own") and time.time() < deadline:
        time.sleep(0.2)
    job = jobs.refresh(env.config, "own")
    os.kill(job.spec["pid"], signal.SIGTERM)
    finish(env, "own")
    assert (job.done, job.total) == (7, 70)

import os
import signal
import sys
import time

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

import json
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ax import job_sources, jobs


def later(seconds):
    return datetime.now(UTC) + timedelta(seconds=seconds)


class FakeAws:
    """Recorded AWS CLI answers, keyed by subcommand; a list is played in order."""

    def __init__(self, **responses):
        self.responses = {k.replace("_", "-"): v for k, v in responses.items()}
        self.calls = []

    def __call__(self, args, *, region=None, profile=None):
        self.calls.append((args, region, profile))
        value = self.responses[args[1]]
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if callable(value):
            value = value(args)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def aws(monkeypatch):
    def install(**responses):
        fake = FakeAws(**responses)
        monkeypatch.setattr(job_sources, "run_aws", fake)
        return fake

    return install


# file -----------------------------------------------------------------------


def test_a_json_progress_file_is_read_through_dotted_keys(env, tmp_path):
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps({"progress": {"done": 3, "total": 10}, "state": "running", "phase": "annotate"})
    )
    job = jobs.watch(
        env.config, "file", str(progress), key="annotate",
        options={"done_key": "progress.done", "total_key": "progress.total",
                 "status_key": "state", "stage_key": "phase"},
    )  # fmt: skip
    assert (job.done, job.total, job.stage, job.status) == (3, 10, "annotate", "running")
    progress.write_text(json.dumps({"progress": {"done": 10, "total": 10}, "state": "completed"}))
    job = jobs.refresh(env.config, "annotate")
    assert (job.done, job.status) == (10, "done")


def test_a_progress_file_may_appear_later_and_a_marker_file_means_done(env, tmp_path):
    marker = tmp_path / "summary.json"
    job = jobs.watch(
        env.config, "file", str(tmp_path / "progress.json"), key="late",
        options={"done_when": str(marker)},
    )  # fmt: skip
    assert (job.status, job.check_error) == ("running", None)
    marker.write_text("{}")
    assert jobs.refresh(env.config, "late").status == "done"


def test_a_half_written_json_file_is_a_check_error_not_a_failure(env, tmp_path):
    progress = tmp_path / "progress.json"
    progress.write_text("{")
    job = jobs.watch(env.config, "file", str(progress), key="half")
    assert job.status == "running" and "JSON" in job.check_error
    progress.write_text(json.dumps({"done": 1}))
    job = jobs.refresh(env.config, "half")
    assert (job.done, job.check_error) == (1, None)


def test_an_external_jsonl_file_speaks_the_events_protocol(env, tmp_path):
    log = tmp_path / "run.jsonl"
    log.write_text(json.dumps({"done": 1, "total": 4}) + "\n")
    job = jobs.watch(env.config, "file", str(log), key="log")
    assert (job.done, job.total) == (1, 4)
    with log.open("a") as f:
        f.write(json.dumps({"done": 4}) + "\n" + json.dumps({"status": "done"}) + "\n")
    job = jobs.refresh(env.config, "log")
    assert (job.done, job.status) == (4, "done")


def test_a_file_job_gets_a_stable_default_key(env, tmp_path):
    first = jobs.watch(env.config, "file", str(tmp_path / "progress.json"))
    again = jobs.watch(env.config, "file", str(tmp_path / "progress.json"))
    assert first.key == again.key and first.key.startswith("progress-")


# pid ------------------------------------------------------------------------


def test_a_process_runs_and_then_ends(env):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        job = jobs.watch(env.config, "pid", str(proc.pid))
        assert (job.key, job.status) == (f"pid-{proc.pid}", "running")
    finally:
        proc.kill()
        proc.wait()
    job = jobs.refresh(env.config, f"pid-{proc.pid}")
    assert job.status == "ended" and "exit code is unknown" in job.message


def test_a_reused_pid_counts_as_ended(env, monkeypatch):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        monkeypatch.setattr(job_sources, "process_start", lambda pid: "Mon Oct 20 10:00:00 2026")
        jobs.watch(env.config, "pid", str(proc.pid), key="p")
        monkeypatch.setattr(job_sources, "process_start", lambda pid: "Fri Oct 24 18:00:00 2026")
        job = jobs.refresh(env.config, "p")
        assert job.status == "ended" and "reused" in job.message
    finally:
        proc.kill()
        proc.wait()


def test_watching_a_missing_process_is_refused(env):
    with pytest.raises(ValueError, match="no process"):
        jobs.watch(env.config, "pid", "999999")
    with pytest.raises(ValueError):
        jobs.watch(env.config, "pid", "abc")


# sagemaker ------------------------------------------------------------------


def processing(status, **extra):
    return {"ProcessingJobName": "merge-1", "ProcessingJobStatus": status, **extra}


def test_a_processing_job_runs_then_completes(env, aws):
    fake = aws(describe_processing_job=[processing("InProgress"), processing("Completed")])
    job = jobs.watch(env.config, "sagemaker", "merge-1", options={"region": "us-east-1"})
    assert (job.key, job.status) == ("merge-1", "running")
    args, region, _ = fake.calls[0]
    assert args == ["sagemaker", "describe-processing-job", "--processing-job-name", "merge-1"]
    assert region == "us-east-1"
    job = jobs.refresh(env.config, "merge-1", now=later(30))
    assert job.status == "done"


def test_sagemaker_checks_are_spaced_out(env, aws):
    fake = aws(describe_processing_job=[processing("InProgress")])
    jobs.watch(env.config, "sagemaker", "merge-1")
    jobs.refresh(env.config, "merge-1")
    jobs.refresh(env.config, "merge-1", now=later(5))
    assert len(fake.calls) == 1
    jobs.refresh(env.config, "merge-1", now=later(job_sources.MIN_INTERVAL["sagemaker"] + 1))
    assert len(fake.calls) == 2


def test_a_training_job_reports_its_stage_and_failure_reason(env, aws):
    aws(
        describe_training_job=[
            {"TrainingJobStatus": "InProgress", "SecondaryStatus": "Downloading"},
            {"TrainingJobStatus": "Failed", "SecondaryStatus": "Failed", "FailureReason": "OOM"},
        ]
    )
    job = jobs.watch(env.config, "sagemaker", "train-1", options={"type": "training"})
    assert (job.status, job.stage) == ("running", "Downloading")
    job = jobs.refresh(env.config, "train-1", now=later(30))
    assert (job.status, job.message) == ("failed", "OOM")


def test_stopping_and_stopped_jobs(env, aws):
    aws(describe_processing_job=[processing("Stopping"), processing("Stopped")])
    job = jobs.watch(env.config, "sagemaker", "merge-1")
    assert (job.status, job.stage) == ("running", "Stopping")
    assert jobs.refresh(env.config, "merge-1", now=later(30)).status == "stopped"


def test_expired_credentials_keep_the_last_status(env, aws):
    expired = job_sources.AwsError("An error occurred (ExpiredTokenException) when calling ...")
    aws(describe_processing_job=[processing("InProgress"), expired, processing("InProgress")])
    jobs.watch(env.config, "sagemaker", "merge-1")
    job = jobs.refresh(env.config, "merge-1", now=later(30))
    assert job.status == "running" and "credentials" in job.check_error
    job = jobs.refresh(env.config, "merge-1", now=later(60))
    assert job.check_error is None


def test_an_unknown_sagemaker_job_is_a_check_error(env, aws):
    aws(
        describe_processing_job=job_sources.AwsError(
            "ValidationException: Could not find requested job"
        )
    )
    job = jobs.watch(env.config, "sagemaker", "nope-1")
    assert job.status == "running" and "no processing job" in job.check_error


@pytest.mark.parametrize(
    ("ref", "options"), [("bad name", {}), ("-dash", {}), ("ok", {"type": "notebook"})]
)
def test_bad_sagemaker_names_and_types_are_refused(env, ref, options):
    with pytest.raises(ValueError):
        jobs.watch(env.config, "sagemaker", ref, options=options)


# seamless -------------------------------------------------------------------


def progress_line(rank, current, total, progress_id="rows", desc="rows", elapsed=None):
    payload = {
        "desc": desc, "current": current, "total": total, "item": str(current),
        "progress_id": progress_id, "event": "progress", "elapsed_seconds": elapsed,
        "rank": rank, "world_size": 2, "hostname": f"algo-{rank + 1}",
        "current_host": f"algo-{rank + 1}",
    }  # fmt: skip
    return "SEAMLESS_PROGRESS " + json.dumps(payload)


def log_page(*events):
    return {
        "events": [
            {"eventId": event_id, "timestamp": ts, "message": message}
            for event_id, ts, message in events
        ]
    }


def test_seamless_progress_is_summed_across_workers(env, aws):
    pages = [
        log_page(("e1", 1000, progress_line(0, 10, 50)), ("e2", 1001, progress_line(1, 5, 50))),
        # e2 comes back at the boundary timestamp and must not count twice.
        log_page(("e2", 1001, progress_line(1, 5, 50)), ("e3", 2000, progress_line(0, 30, 50))),
    ]
    fake = aws(
        describe_processing_job=[processing("InProgress"), processing("InProgress")],
        filter_log_events=pages,
    )
    job = jobs.watch(env.config, "seamless", "seam-1", options={"region": "us-east-1"})
    assert (job.done, job.total, job.stage, job.status) == (15, 100, "rows", "running")
    logs_args = next(a for a, _, _ in fake.calls if a[1] == "filter-log-events")
    assert "/aws/sagemaker/ProcessingJobs" in logs_args and "seam-1" in logs_args
    job = jobs.refresh(env.config, "seam-1", now=later(30))
    assert job.done == 35
    second = [a for a, _, _ in fake.calls if a[1] == "filter-log-events"][1]
    assert second[second.index("--start-time") + 1] == "1001"


def test_seamless_follows_a_new_stream_and_ignores_an_old_one(env, aws):
    aws(
        describe_processing_job=[processing("InProgress"), processing("InProgress"), processing("Completed")],
        filter_log_events=[
            log_page(("e1", 1000, progress_line(0, 50, 50))),
            log_page(("e2", 2000, progress_line(0, 3, 9, progress_id="upload", desc="files"))),
            log_page(("e3", 3000, progress_line(1, 50, 50)), ("e4", 3001, progress_line(0, 9, 9, "upload", "files"))),
        ],
    )  # fmt: skip
    jobs.watch(env.config, "seamless", "seam-2")
    job = jobs.refresh(env.config, "seam-2", now=later(30))
    assert (job.done, job.total, job.stage) == (3, 9, "files")
    job = jobs.refresh(env.config, "seam-2", now=later(60))
    assert (job.done, job.total, job.status) == (9, 9, "done")


class _StateHandler(BaseHTTPRequestHandler):
    state: dict = {}

    def do_GET(self):  # noqa: N802
        body = json.dumps(self.state).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_seamless_reads_its_dashboard_state_without_aws(env, aws):
    _StateHandler.state = {
        "status": "InProgress",
        "totals": {"current": 40, "total": 100},
        "progress": [{"desc": "rows"}],
        "failure_reason": "",
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StateHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake = aws(describe_processing_job=[processing("InProgress")], filter_log_events=[log_page()])
    url = f"http://127.0.0.1:{server.server_address[1]}/api/state"
    try:
        job = jobs.watch(env.config, "seamless", "seam-3", options={"state_url": url})
        assert (job.done, job.total, job.stage, job.status) == (40, 100, "rows", "running")
        assert fake.calls == []
    finally:
        server.shutdown()
        server.server_close()
    # With the dashboard gone, the job falls back to SageMaker and CloudWatch.
    jobs.refresh(env.config, "seam-3", now=later(30))
    assert {a[1] for a, _, _ in fake.calls} == {"describe-processing-job", "filter-log-events"}


def test_cli_watch_prints_the_key_and_warns_on_a_check_error(env, aws):
    from typer.testing import CliRunner

    from ax.cli import app

    aws(describe_processing_job=job_sources.AwsError("ExpiredTokenException: expired"))
    result = CliRunner().invoke(
        app, ["job", "watch", "sagemaker", "merge-1", "--region", "us-east-1"],
        env={"AX_CONFIG": str(env.config_path)},
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "merge-1"
    assert "credentials" in result.stderr


def test_cli_watch_refuses_options_that_do_not_apply(env, tmp_path):
    from typer.testing import CliRunner

    from ax.cli import app

    result = CliRunner().invoke(
        app, ["job", "watch", "file", str(tmp_path / "p.json"), "--type", "training"],
        env={"AX_CONFIG": str(env.config_path)},
    )  # fmt: skip
    assert result.exit_code == 2
    assert "--type doesn't apply to a file job" in result.stderr

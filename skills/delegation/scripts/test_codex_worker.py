import argparse
import importlib.util
import json
import uuid
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "codex_worker", Path(__file__).with_name("codex_worker.py")
)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
SID = "01a12649-f07b-72f0-aee7-76217e23999e"


def args(tmp_path, **kwargs):
    brief = tmp_path / "brief.md"
    brief.write_text("Return a bounded test result.")
    values = dict(
        codex="codex",
        cwd=tmp_path,
        run_dir=tmp_path / "run",
        model="gpt-6.1-sol",
        effort="high",
        permission="auto-review",
        timeout=10,
        resume_run=None,
        brief=brief,
    )
    values.update(kwargs)
    return argparse.Namespace(**values)


def test_exact_selection_and_resume(tmp_path):
    command = worker.build_command(args(tmp_path), SID)
    assert command[command.index("-m") + 1] == "gpt-6.1-sol"
    assert 'model_reasoning_effort="high"' in command
    assert command[-3:] == ["resume", SID, "-"]
    assert "--last" not in command
    assert "--approve-for-me" in command
    assert "features.multi_agent=false" in command
    assert not any("dangerously" in x for x in command)


def test_readonly_fails_new_approval_requests(tmp_path):
    command = worker.build_command(args(tmp_path, permission="read-only"))
    assert command[:3] == ["codex", "-a", "never"]
    assert 'approvals_reviewer="user"' in command
    assert command[command.index("-s") + 1] == "read-only"
    assert "--approve-for-me" not in command


def test_no_secret_model_billing_fallback(monkeypatch):
    for key in ["OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"]:
        monkeypatch.setenv(key, "must-not-reach-child")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "authorized-ephemeral-cloud-value")
    env = worker.clean_environment()
    assert all(
        k not in env for k in ["OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"]
    )
    assert env["AWS_SESSION_TOKEN"] == "authorized-ephemeral-cloud-value"


def test_resume_fork_is_rejected():
    record = dict(session_id=SID, event_count=0)
    with pytest.raises(ValueError, match="different thread"):
        worker.consume_event(
            json.dumps({"type": "thread.started", "thread_id": str(uuid.uuid4())}),
            record,
        )
    assert record["session_id"] == SID


def test_malformed_thread_is_rejected():
    with pytest.raises(ValueError):
        worker.consume_event(
            json.dumps({"type": "thread.started", "thread_id": "../other"}),
            {"event_count": 0},
        )


def test_resume_waits_for_fresh_native_turn(monkeypatch):
    record = dict(
        session_id=SID,
        resumed_from_turn_id="old",
        model_requested="gpt-6.1-sol",
        effort_requested="high",
    )
    monkeypatch.setattr(
        worker,
        "native_context",
        lambda _: dict(model="gpt-6.1-sol", effort="high", turn_id="old"),
    )
    worker.verify_context(record)
    assert "actual_context" not in record
    monkeypatch.setattr(
        worker,
        "native_context",
        lambda _: dict(model="gpt-6.1-sol", effort="high", turn_id="new"),
    )
    worker.verify_context(record)
    assert record["actual_context"]["turn_id"] == "new"


@pytest.mark.parametrize(
    "model,effort", [("gpt-6-astra", "high"), ("gpt-6.1-sol", "ultra")]
)
def test_mismatched_runtime_selection_stops(monkeypatch, model, effort):
    record = dict(
        session_id=SID, model_requested="gpt-6.1-sol", effort_requested="high"
    )
    monkeypatch.setattr(
        worker,
        "native_context",
        lambda _: dict(model=model, effort=effort, turn_id="new"),
    )
    with pytest.raises(ValueError, match="differs"):
        worker.verify_context(record)


@pytest.mark.parametrize(
    "permission,sandbox,policy,reviewer",
    [
        ("read-only", "read-only", "on-request", "auto_review"),
        ("read-only", "workspace-write", "never", "user"),
        ("auto-review", "danger-full-access", "on-request", "auto_review"),
        ("auto-review", "workspace-write", "never", "auto_review"),
    ],
)
def test_effective_permission_drift_stops(
    monkeypatch, permission, sandbox, policy, reviewer
):
    record = dict(
        session_id=SID,
        model_requested="gpt-6.1-sol",
        effort_requested="high",
        permission=permission,
    )
    monkeypatch.setattr(
        worker,
        "native_context",
        lambda _: dict(
            model="gpt-6.1-sol",
            effort="high",
            turn_id="new",
            sandbox_policy={"type": sandbox},
            approval_policy=policy,
            approvals_reviewer=reviewer,
        ),
    )
    with pytest.raises(ValueError, match="permission selection differs"):
        worker.verify_context(record)


@pytest.mark.parametrize("change", ["live", "cwd", "stale"])
def test_only_latest_terminal_same_workspace_resume(tmp_path, change):
    previous = dict(
        cwd=str(tmp_path), status="completed", run_dir=str(tmp_path / "old")
    )
    (tmp_path / "latest.json").write_text(json.dumps({"run_dir": previous["run_dir"]}))
    if change == "live":
        previous["status"] = "running"
    if change == "cwd":
        previous["cwd"] = "/wrong"
    if change == "stale":
        (tmp_path / "latest.json").write_text(json.dumps({"run_dir": "/newer"}))
    with pytest.raises(ValueError):
        worker.validate_resume(previous, tmp_path, tmp_path)


def test_resume_inherits_permissions_without_widening():
    previous = {"permission": "read-only"}
    assert worker.resolve_permission(None, previous) == "read-only"
    assert worker.resolve_permission("read-only", previous) == "read-only"
    with pytest.raises(ValueError, match="explicit authorization"):
        worker.resolve_permission("auto-review", previous)
    assert worker.resolve_permission("auto-review", previous, True) == "auto-review"


def test_failed_login_never_turns_into_api_run(monkeypatch):
    def call(command, **_):
        output = (
            "--json --output-last-message --model --approve-for-me"
            if "--help" in command
            else "Logged in using API key"
        )
        return argparse.Namespace(stdout=output, stderr="", returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", call)
    with pytest.raises(ValueError, match="no API fallback"):
        worker.preflight("codex", "auto-review", {})


def test_missing_review_support_never_weakens_permissions(monkeypatch):
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_a, **_k: argparse.Namespace(
            stdout="--json --output-last-message --model", stderr="", returncode=0
        ),
    )
    with pytest.raises(ValueError, match="no silent permission downgrade"):
        worker.preflight("codex", "auto-review", {})


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0, -1])
def test_unbounded_or_invalid_runtime_rejected(tmp_path, timeout):
    with pytest.raises(ValueError, match="finite positive"):
        worker.run(args(tmp_path, timeout=timeout))


def fake_cli(tmp_path, sleep=False):
    path = tmp_path / "fake_codex.py"
    script = """#!/usr/bin/env python3
import sys,json,time
sys.stdin.read()
print(json.dumps({'type':'thread.started','thread_id':'01a12649-f07b-72f0-aee7-76217e23999e'}),flush=True)
"""
    script += (
        "time.sleep(30)\n"
        if sleep
        else "print(json.dumps({'type':'turn.completed','usage':"
        "{'input_tokens':1,'output_tokens':1}}),flush=True)\n"
    )
    path.write_text(script)
    path.chmod(0o700)
    return str(path)


def test_complete_invocation_preserves_usage_and_private_records(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "preflight", lambda *_: "fixture-cli")
    monkeypatch.setattr(
        worker,
        "native_context",
        lambda _: dict(
            model="gpt-6.1-sol",
            effort="high",
            turn_id="fixture-turn",
            approval_policy="on-request",
            approvals_reviewer="auto_review",
            sandbox_policy={"type": "workspace-write"},
        ),
    )
    a = args(tmp_path, codex=fake_cli(tmp_path))
    assert worker.run(a) == 0
    record = worker.load_run(a.run_dir)
    assert record["status"] == "completed"
    assert record["usage"]["output_tokens"] == 1
    assert record["session_id"] == SID
    assert (a.run_dir / "run.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((a.run_dir / "latest.json").read_text())["run_dir"] == str(
        a.run_dir
    )


def test_timeout_stops_only_owned_child(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "preflight", lambda *_: "fixture-cli")
    monkeypatch.setattr(worker, "native_context", lambda _: None)
    a = args(tmp_path, codex=fake_cli(tmp_path, sleep=True), timeout=0.05)
    assert worker.run(a) == 1
    record = worker.load_run(a.run_dir)
    assert record["status"] == "stopped" and record["stop_reason"] == "timeout"
    assert not worker.process_alive(record["pid"])


def test_lineage_lock_prevents_concurrent_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "preflight", lambda *_: "fixture-cli")
    lineage = tmp_path / "lineage"
    lineage.mkdir()
    previous = dict(
        kind=worker.KIND,
        schema=1,
        status="completed",
        cwd=str(tmp_path),
        lineage_dir=str(lineage),
        run_dir=str(lineage),
        session_id=SID,
        permission="auto-review",
    )
    (lineage / "run.json").write_text(json.dumps(previous))
    (lineage / "latest.json").write_text(json.dumps({"run_dir": str(lineage)}))
    with (lineage / "session.lock").open("a") as lock:
        worker.fcntl.flock(lock, worker.fcntl.LOCK_EX | worker.fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already has an active"):
            worker.run(args(tmp_path, run_dir=tmp_path / "next", resume_run=lineage))
    assert not (tmp_path / "next").exists()


def test_unknown_run_is_not_operated(tmp_path):
    (tmp_path / "run.json").write_text(
        json.dumps({"kind": "someone-else", "schema": 1})
    )
    with pytest.raises(ValueError, match="Not an owned"):
        worker.load_run(tmp_path)

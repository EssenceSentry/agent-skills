import json
import os
import time
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from ax import runs
from ax.cli import app
from ax.sync import sync

runner = CliRunner()


def make_run(root, name, kind, status, *, age=0.0, pid=None, brief="Review the parser\nDetails."):
    directory = root / name
    directory.mkdir(parents=True)
    now = time.time()
    record = {
        "kind": kind,
        "schema": 1,
        "status": status,
        "run_dir": str(directory),
        "cwd": "/Users/me/Repos/demo",
        "session_id": f"sess-{name}",
        "started_at": now - age - 60,
        "updated_at": now - age,
        "runner_pid": pid if pid is not None else 999999,
    }
    model_key = "model_requested"
    record[model_key] = "claude-opus-5-5" if kind == "claude-delegation" else "gpt-5.5"
    (directory / "run.json").write_text(json.dumps(record))
    # The file's own time is the runner's heartbeat; date it like a real run.
    os.utime(directory / "run.json", (now - age, now - age))
    (directory / "brief.md").write_text(brief)
    return directory


@pytest.fixture
def run_env(env, tmp_path):
    roots = tmp_path / "runs"
    make_run(roots, "claude-1", "claude-delegation", "completed", age=3600)
    make_run(roots, "codex-1", "codex-cli-delegation", "running", pid=os.getpid())
    make_run(roots, "lost-1", "claude-delegation", "running", age=900)
    (roots / "unrelated").mkdir()
    (roots / "unrelated" / "run.json").write_text('{"kind": "something-else"}')
    config = replace(env.config, run_roots=(roots,))
    return config, roots


def no_background(*args, **kwargs):
    return []


def test_delegation_runs_are_found_with_their_state(run_env):
    config, _ = run_env
    all_runs = runs.collect(config, background=no_background, include_archive=False)
    assert {(r.source, r.state) for r in all_runs} == {
        ("claude-worker", "completed"),
        ("codex-worker", "running"),
        ("claude-worker", "lost"),  # says running, but its runner is gone and silent
    }
    codex = next(r for r in all_runs if r.source == "codex-worker")
    assert codex.title == "Review the parser"
    assert codex.provider == "codex"
    assert codex.model == "gpt-5.5"
    assert codex.project == "demo"


def test_claude_background_sessions_are_listed(run_env):
    config, _ = run_env

    def background():
        return [
            {
                "sessionId": "bg-123456789",
                "name": "Nightly audit",
                "status": "working",
                "cwd": "/Users/me/Repos/demo",
                "startedAt": "2026-10-24T10:00:00Z",
                "pid": 1,
                "kind": "background",
            }
        ]

    found = runs.collect(config, background=background, include_archive=False)
    bg = next(r for r in found if r.source == "claude-background")
    assert (bg.title, bg.state, bg.provider) == ("Nightly audit", "running", "claude")


def test_archived_subagents_show_as_running_while_their_transcript_grows(run_env, env):
    config, _ = run_env
    sync(config)
    found = runs.collect(config, background=no_background, since_days=36500)
    subagents = [r for r in found if r.source.endswith("subagent")]
    assert {r.provider for r in subagents} == {"claude", "codex"}
    assert all(r.state == "done" for r in subagents)  # fixture files are old
    for path in (env.claude_home / "projects").rglob("agent-*.jsonl"):
        os.utime(path, None)
    found = runs.collect(config, background=no_background, since_days=36500)
    claude_sub = next(r for r in found if r.source == "claude-subagent")
    assert claude_sub.state == "running"
    assert claude_sub.note and claude_sub.note.endswith(".md")


def test_stop_asks_the_owning_runner_and_refuses_anything_else(run_env):
    config, roots = run_env
    found = runs.collect(config, background=no_background, include_archive=False)
    running = next(r for r in found if r.state == "running")
    runs.stop(running)
    assert (roots / "codex-1" / "stop.request").exists()
    done = next(r for r in found if r.state == "completed")
    with pytest.raises(runs.CannotStop):
        runs.stop(done)


def test_runs_command_lists_and_shows(run_env, monkeypatch):
    config, _ = run_env
    monkeypatch.setattr(runs, "load_config", lambda: config)
    monkeypatch.setattr(runs, "claude_background", no_background)
    listed = runner.invoke(app, ["runs", "--all"])
    assert listed.exit_code == 0, listed.output
    assert "codex-worker" in listed.output and "running" in listed.output
    run_id = next(
        r.id for r in runs.collect(config, background=no_background) if r.source == "codex-worker"
    )
    shown = runner.invoke(app, ["runs", "show", run_id])
    assert shown.exit_code == 0, shown.output
    assert "Review the parser" in shown.output
    as_json = runner.invoke(app, ["runs", "--all", "--json"])
    assert {row["source"] for row in json.loads(as_json.output)} >= {
        "claude-worker",
        "codex-worker",
    }

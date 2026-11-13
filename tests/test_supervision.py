import json
import time
from pathlib import Path

import pytest

from ax import providers, tasks
from ax.daemon import Core
from ax.db import connect, events


def create(config):
    return tasks.create(
        config,
        {
            "purpose": "Produce valid scored records",
            "caller": "codex:owner",
            "cwd": str(config.data),
        },
    )


@pytest.mark.parametrize("provider,model", [("claude", "haiku"), ("codex", "gpt-6-luna")])
def test_model_routing_bounds_and_structured_results(config, monkeypatch, provider, model):
    monkeypatch.setattr(providers.shutil, "which", lambda x: "/fake/" + x)
    commands = []

    def execute(command, prompt, cwd):
        commands.append(command)
        response = {
            "concern": False,
            "assessment": "Progress is plausible",
            "evidence": ["Counters increased"],
        }
        if provider == "claude":
            return json.dumps({"structured_output": response, "total_cost_usd": 0.01, "usage": {}})
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(response))
        return json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 40}}
        )

    monkeypatch.setattr(providers, "execute", execute)
    result = providers.model_call(config, provider, "supplied evidence only", "supervision")
    assert result["reviewer"] == model
    assert result["concern"] is False
    assert "low" in " ".join(commands[0])
    assert (
        ("--tools" in commands[0])
        if provider == "claude"
        else ("--ignore-user-config" in commands[0] and "multi_agent" in commands[0])
    )
    assert events(config)[-1]["type"] == "model_call"


def test_suspected_problem_contacts_original_owner(config, monkeypatch):
    row = create(config)
    monkeypatch.setattr(
        tasks,
        "model_call",
        lambda *a: {
            "concern": True,
            "assessment": "Repeated retries",
            "evidence": ["No progress in two checks"],
        },
    )
    tasks.inspect(config, row["id"])
    deliveries = []
    monkeypatch.setattr(
        providers, "deliver", lambda task, text: deliveries.append((task["owner"], text))
    )
    providers.flush_escalations(config)
    providers.flush_escalations(config)
    assert len(deliveries) == 1 and deliveries[0][0] == "codex:owner"
    assert row["id"] in deliveries[0][1]
    assert any(e["type"] == "attention_required" for e in events(config))


def test_failed_inspection_is_also_escalated(config, monkeypatch):
    row = create(config)

    def fail(*args):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(tasks, "model_call", fail)
    tasks.inspect(config, row["id"])
    assert any(e["type"] == "attention_required" for e in events(config))
    assert tasks.get(config, row["id"])["reviewing"] == 0


def test_delivery_uncertainty_is_never_automatically_replayed(config, monkeypatch):
    row = tasks.get(config, create(config)["id"])
    providers.escalate(config, row, "Concern", ["Evidence"])
    attempts = []

    def uncertain(*args):
        attempts.append(1)
        raise TimeoutError("acknowledgement lost")

    monkeypatch.setattr(providers, "deliver", uncertain)
    providers.flush_escalations(config)
    providers.flush_escalations(config)
    assert len(attempts) == 1
    with connect(config) as db:
        assert db.execute("SELECT status FROM escalations").fetchone()[0] == "uncertain"


def test_unavailable_route_retries_without_losing_concern(config, monkeypatch):
    row = tasks.get(config, create(config)["id"])
    providers.escalate(config, row, "Concern", ["Evidence"])

    def unavailable(*args):
        raise providers.Unavailable("caller closed")

    monkeypatch.setattr(providers, "deliver", unavailable)
    providers.flush_escalations(config)
    with connect(config) as db:
        assert db.execute("SELECT status FROM escalations").fetchone()[0] == "pending"


def test_due_checks_repeat_and_ended_tasks_are_not_inspected(config, monkeypatch):
    row = create(config)
    calls = []

    def inspect(cfg, task_id):
        calls.append(task_id)
        with connect(cfg) as db:
            db.execute("UPDATE tasks SET reviewing=0 WHERE id=?", (task_id,))

    monkeypatch.setattr(tasks, "inspect", inspect)
    core = Core(config)
    try:
        core.tick()
        assert not calls
        with connect(config) as db:
            db.execute("UPDATE tasks SET next_review=0 WHERE id=?", (row["id"],))
        core.tick()
        for future in list(core.reviews.values()):
            future.result(timeout=3)
        assert calls == [row["id"]]
        assert tasks.get(config, row["id"])["next_review"] > time.time() + 590
        core.tick()
        assert calls == [row["id"]]
        with connect(config) as db:
            db.execute("UPDATE tasks SET next_review=0 WHERE id=?", (row["id"],))
        core.tick()
        for future in list(core.reviews.values()):
            future.result(timeout=3)
        assert len(calls) == 2
        tasks.update(config, row["id"], {"status": "done"})
        core.tick()
        assert len(calls) == 2
    finally:
        core.pool.shutdown()
        core.maintenance.shutdown()


def test_crash_during_delivery_becomes_uncertain_on_restart(config):
    row = tasks.get(config, create(config)["id"])
    eid = providers.escalate(config, row, "Concern", ["Evidence"])
    with connect(config) as db:
        db.execute("UPDATE escalations SET status='dispatching' WHERE id=?", (eid,))
    core = Core(config)
    with connect(config) as db:
        assert (
            db.execute("SELECT status FROM escalations WHERE id=?", (eid,)).fetchone()[0]
            == "uncertain"
        )
    core.pool.shutdown()
    core.maintenance.shutdown()


def test_codex_escalation_queues_and_resumes_original_conversation(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda name: "/fake/codex")
    calls = []

    class Result:
        returncode = 0

    def run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(providers.subprocess, "run", run)
    providers.deliver({"owner": "codex:original-session"}, "evidence-bearing concern")
    assert "--resume" in calls[0]
    assert calls[0][calls[0].index("--thread") + 1] == "original-session"


def test_provider_process_timeout_is_bounded_and_cleaned_up(tmp_path):
    import subprocess
    import sys

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        providers.execute(
            [sys.executable, "-c", "import time; time.sleep(30)"], "", str(tmp_path), timeout=0.1
        )
    assert time.monotonic() - started < 4

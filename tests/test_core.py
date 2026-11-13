import argparse
import hashlib
import json
import math
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from ax import budget, catalog, memory, tasks, usage
from ax.cli import parser
from ax.db import events
from ax.providers import caller_context


def task(config, **overrides):
    args = {
        "purpose": "Compute selected records; expected progress each minute",
        "caller": "codex:owner",
        "cwd": str(config.data),
        "kind": "reported",
    }
    return tasks.create(config, {**args, **overrides})


def test_exact_command_surface():
    sub = next(x for x in parser()._actions if isinstance(x, argparse._SubParsersAction))
    assert set(sub.choices) == {
        "run",
        "attach",
        "detach",
        "search",
        "handoff",
        "memory",
        "task",
        "usage",
        "budget",
        "daemon",
    }


@pytest.mark.parametrize("value", [0, 1, 9, 61, -1])
def test_no_disabled_or_out_of_range_supervision(config, value):
    with pytest.raises(ValueError):
        task(config, every=value)
    with pytest.raises(SystemExit):
        parser().parse_args(["task", "create", "work", "--every", str(value)])


def test_task_owner_progress_and_schedule(config):
    row = task(config, inbox="private-socket", inbox_token="private-token")
    assert row["every"] == 10
    assert row["next_review"] - row["started"] == 600
    assert "inbox_token" not in row
    row = tasks.update(config, row["id"], {"done": 3, "total": 8, "every": 60})
    assert row["status"] == "running"
    assert row["done"] == 3
    with pytest.raises(ValueError):
        tasks.update(config, row["id"], {"every": 0})
    tasks.update(config, row["id"], {"status": "done"})
    with pytest.raises(ValueError):
        tasks.update(config, row["id"], {"done": 4})
    tasks.finish(config, row["id"], "failed")
    assert tasks.get(config, row["id"])["status"] == "done"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_invalid_progress_rejected(config, value):
    row = task(config)
    with pytest.raises(ValueError):
        tasks.update(config, row["id"], {"done": value})


def test_progress_is_not_completion(config):
    row = task(config)
    row = tasks.update(config, row["id"], {"done": 10, "total": 10})
    assert row["status"] == "running"
    with pytest.raises(ValueError):
        tasks.update(config, row["id"], {"done": 11})
    rows = events(config)
    assert [r["seq"] for r in rows] == sorted(r["seq"] for r in rows)
    assert not events(config, after=rows[-1]["seq"])


def test_explicit_owner_beats_daemon_starter(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "starter")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert caller_context("codex:actual")["caller"] == "codex:actual"
    assert caller_context()["caller"] == "codex:starter"


def test_pid_reuse_ends_watch_without_stopping_process(config, monkeypatch):
    monkeypatch.setattr(tasks, "process_identity", lambda pid: "first")
    row = task(config, kind="watch", pid=123)
    monkeypatch.setattr(tasks, "process_identity", lambda pid: "replacement")
    tasks.reconcile(config)
    assert tasks.get(config, row["id"])["status"] == "ended"
    with pytest.raises(ValueError):
        tasks.stop(config, row["id"])


def test_native_conversation_search_and_incremental_refresh(config):
    source = config.claude_home / "projects" / "project" / "abc.jsonl"
    source.parent.mkdir(parents=True)
    records = [
        {
            "type": "user",
            "timestamp": "2026-11-13T12:00:00Z",
            "cwd": "/tmp/project",
            "message": {"role": "user", "content": "Find the calibration contract"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-11-13T12:01:00Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Calibration uses held-out examples."}],
            },
        },
    ]
    source.write_text("\n".join(json.dumps(x) for x in records))
    assert catalog.refresh(config)["updated"] == 1
    found = catalog.search(config, "calibration")
    assert found and {r["provider"] for r in found} == {"claude"}
    assert all(r["source"] == str(source) for r in found)
    assert catalog.refresh(config)["updated"] == 0
    assert not catalog.search(config, "calibration", provider="codex")


def test_codex_native_search(config):
    sid = "01234567-1234-1234-1234-123456789abc"
    source = config.codex_home / "sessions" / ("rollout-2026-11-13-" + sid + ".jsonl")
    source.parent.mkdir(parents=True)
    records = [
        {"type": "session_meta", "payload": {"id": sid, "cwd": "/tmp/example"}},
        {
            "type": "response_item",
            "timestamp": "2026-11-13T12:00:00Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Embedding compatibility audit"}],
            },
        },
    ]
    source.write_text("\n".join(json.dumps(x) for x in records))
    catalog.refresh(config)
    assert catalog.search(config, "compatibility")[0]["provider"] == "codex"


def test_preserved_archive_import_is_idempotent_and_read_only(config):
    old = config.data / "ax.db"
    with sqlite3.connect(old) as db:
        db.executescript("""CREATE TABLE sessions(key,provider,session_id,title,project,source_path,updated_at,kind,excluded);
        CREATE TABLE files(path,size,mtime_ns); CREATE TABLE messages(session_key,role,text);""")
        db.execute(
            "INSERT INTO sessions VALUES('codex:old','codex','old','History','repo','/missing', '2026-01-01','main',0)"
        )
        db.execute("INSERT INTO messages VALUES('codex:old','assistant','historical contract')")
    before = hashlib.sha256(old.read_bytes()).hexdigest()
    catalog.refresh(config)
    catalog.refresh(config)
    assert len(catalog.search(config, "historical")) == 1
    assert hashlib.sha256(old.read_bytes()).hexdigest() == before


def test_memory_sync_both_providers_v2_and_no_echo(config):
    note = config.claude_home / "projects/project/memory/preference.md"
    note.parent.mkdir(parents=True)
    note.write_text("Prefer bounded scans.")
    other = config.codex_home / "memories_v2/extensions/ad_hoc/notes/decision.md"
    other.parent.mkdir(parents=True)
    other.write_text("Use shared evidence.")
    instructions = config.claude_home / "CLAUDE.md"
    instructions.write_text("Handwritten instructions.\n")
    result = memory.sync(config)
    assert result["updated"] == 2
    exported = list(other.parent.glob("ax-*.md"))
    assert len(exported) == 1 and "bounded scans" in exported[0].read_text()
    assert instructions.read_text().startswith("Handwritten instructions.\n")
    assert str(config.data / "shared-memory/index.md") in instructions.read_text()
    assert memory.sync(config)["updated"] == 0
    note.unlink()
    assert memory.sync(config)["deleted"] == 1
    assert "Withdraw" in exported[0].read_text()


def test_memory_sync_preserves_edited_import_and_reports_conflict(config):
    note = config.claude_home / "projects/project/memory/preference.md"
    note.parent.mkdir(parents=True)
    note.write_text("Original preference.")
    (config.codex_home / "memories_v2").mkdir(parents=True)
    memory.sync(config)
    exported = next((config.codex_home / "memories_v2/extensions/ad_hoc/notes").glob("ax-*.md"))
    exported.write_text("Hand edited imported note.")
    note.write_text("Changed preference.")
    result = memory.sync(config)
    assert str(exported) in result["conflicts"]
    assert exported.read_text() == "Hand edited imported note."


def test_memory_never_overwrites_native_summary(config):
    summary = config.codex_home / "memories_v2/memory_summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("Native generated summary.")
    memory.sync(config)
    assert summary.read_text() == "Native generated summary."


def test_budget_reservations_are_atomic_and_survive_reopen(config):
    budget.create(config.data, "test", 10, "usd")

    def reserve(_):
        try:
            return budget.reserve(config.data, "test", 2)
        except budget.OverLimit:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        tickets = [t for t in pool.map(reserve, range(10)) if t]
    assert len(tickets) == 5
    assert budget.status(config.data, "test")["left"] == 0
    budget.settle(config.data, tickets[0], 1)
    assert budget.status(config.data, "test")["spent"] == 1
    assert budget.status(config.data, "test")["reserved"] == 8


@pytest.mark.parametrize("value", [math.inf, math.nan, -1])
def test_budget_rejects_nonfinite_and_negative(config, value):
    with pytest.raises(ValueError):
        budget.create(config.data, "invalid", value, "usd")
    budget.create(config.data, "test", 10, "usd")
    ticket = budget.reserve(config.data, "test", 2)
    with pytest.raises(ValueError):
        budget.settle(config.data, ticket, value)
    assert budget.status(config.data, "test")["reserved"] == 2


def test_forecast_preserves_unknown_stale_and_reset_boundaries():
    assert usage.forecast([(100, 10)], 1000, 200) is None
    assert usage.forecast([(100, 10), (200, 20)], 1000, 200)["estimated_used_at_reset"] == 100
    assert usage.forecast([(100, 30), (200, 20)], 1000, 200) is None
    assert usage.forecast([(100, 10), (200, 20)], 150, 200) is None
    assert usage.forecast([(100, 10), (200, 20)], 2000, 1200) is None


def test_ambiguous_caller_is_rejected_unless_explicit(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-owner")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-owner")
    with pytest.raises(ValueError, match="ambiguous"):
        caller_context()
    assert caller_context("codex:codex-owner")["caller"] == "codex:codex-owner"


def test_memory_deletion_preserves_edited_import(config):
    note = config.claude_home / "projects/project/memory/preference.md"
    note.parent.mkdir(parents=True)
    note.write_text("Original preference.")
    (config.codex_home / "memories_v2").mkdir(parents=True)
    memory.sync(config)
    exported = next((config.codex_home / "memories_v2/extensions/ad_hoc/notes").glob("ax-*.md"))
    exported.write_text("Hand edited imported note.")
    note.unlink()
    assert str(exported) in memory.sync(config)["conflicts"]
    assert exported.read_text() == "Hand edited imported note."

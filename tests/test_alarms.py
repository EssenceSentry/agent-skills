import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from ax import alarms, providers, usage
from ax.db import connect, events


@pytest.fixture
def world(config, monkeypatch):
    now = [1800000000.0]
    monkeypatch.setattr(alarms.time, "time", lambda: now[0])
    frame = {
        "windows": [
            {
                "provider": "codex",
                "name": "primary",
                "used": 79.0,
                "observed": now[0],
                "resets": now[0] + 3600,
                "status": "fresh",
                "projection": None,
            },
            {
                "provider": "claude",
                "name": "weekly_all",
                "used": 40.0,
                "observed": now[0],
                "resets": now[0] + 86400,
                "status": "fresh",
                "projection": None,
            },
        ],
        "claude_refresh_error": None,
    }
    reads, delivered = [], []

    def snapshot(config, refresh=False):
        reads.append(refresh)
        return copy.deepcopy(frame)

    monkeypatch.setattr(usage, "snapshot", snapshot)
    monkeypatch.setattr(
        providers, "deliver", lambda recipient, text: delivered.append((recipient, text))
    )
    return now, frame, reads, delivered


def subscribe(config, owner="codex:caller", metric="codex:primary", at=80, **extra):
    return alarms.subscribe(config, {"caller": owner, "metric": metric, "at": at, **extra})


def advance(world, *, used=None, seconds=1, row=0):
    now, frame, reads, delivered = world
    now[0] += seconds
    frame["windows"][row]["observed"] = now[0]
    if used is not None:
        frame["windows"][row]["used"] = used
    return frame


def test_threshold_subscription_fires_once_and_rearms_after_reset(config, world):
    now, frame, reads, delivered = world
    watch = subscribe(config)
    duplicate = subscribe(config, at="80%")
    assert watch["id"] == duplicate["id"] and not duplicate["new"]
    assert watch["alarm"] is None
    alarms.evaluate(config, advance(world, used=80))
    alarms.flush(config)
    assert len(delivered) == 1
    assert "80% used" in delivered[0][1] and "20% remaining" in delivered[0][1]
    assert "not user approval" in delivered[0][1]
    alarms.evaluate(config, advance(world, used=90))
    alarms.flush(config)
    assert len(delivered) == 1
    now[0] = frame["windows"][0]["resets"] + 1
    frame["windows"][0].update(observed=now[0], resets=now[0] + 3600, used=85)
    alarms.evaluate(config, frame)
    alarms.flush(config)
    assert len(delivered) == 2
    assert delivered[0][0]["id"] != delivered[1][0]["id"]
    assert not any(reads)


def test_watch_already_above_threshold_routes_to_requesting_caller(config, world):
    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 81.5
    watch = subscribe(
        config, owner="claude:requester", inbox="/caller/socket", inbox_token="private-test-token"
    )
    assert watch["alarm"]["status"] == "pending"
    assert "inbox" not in watch and "private-test-token" not in json.dumps(watch)
    alarms.flush(config)
    recipient, text = delivered[0]
    assert recipient["owner"] == "claude:requester"
    assert recipient["inbox"] == "/caller/socket" and "codex:primary" in text


@pytest.mark.parametrize(
    "change",
    [
        {"status": "stale"},
        {"used": None},
        {"used": True},
        {"used": -1},
        {"used": float("nan")},
        {"observed": None},
        {"observed": 1799999699},
        {"observed": 1800000001},
        {"resets": None},
        {"resets": 1799999999},
        {"resets": 1e308},
    ],
)
def test_unknown_stale_or_invalid_data_never_triggers(config, world, change):
    now, frame, reads, delivered = world
    frame["windows"][0].update(used=90, **change) if "used" not in change else frame["windows"][
        0
    ].update(change)
    watch = subscribe(config, at=0)
    alarms.flush(config)
    assert watch["alarm"] is None and not delivered


def test_owner_scoping_unsubscribe_and_explicit_resubscribe(config, world):
    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 90
    first = subscribe(config, owner="codex:first")
    second = subscribe(config, owner="codex:second")
    assert [row["id"] for row in alarms.watches(config, "codex:first")] == [first["id"]]
    with pytest.raises(ValueError, match="this caller"):
        alarms.unsubscribe(config, second["id"], "codex:first")
    canceled = alarms.unsubscribe(config, first["id"], "codex:first")
    assert canceled["pending_canceled"] == 1
    alarms.flush(config)
    assert [recipient["owner"] for recipient, _ in delivered] == ["codex:second"]
    assert alarms.watches(config, "codex:first") == []
    replacement = subscribe(config, owner="codex:first")
    assert replacement["id"] != first["id"]
    alarms.flush(config)
    assert len(delivered) == 2


def test_pending_alarm_tracks_fresh_data_and_expires_without_stale_delivery(
    config, world, monkeypatch
):
    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 85
    watch = subscribe(config)

    def unavailable(*args):
        raise providers.Unavailable("caller is closed")

    monkeypatch.setattr(providers, "deliver", unavailable)
    alarms.flush(config)
    now[0] += 301
    alarms.flush(config)
    assert alarms.watches(config, "codex:caller")[0]["alarm"]["status"] == "expired"
    alarms.evaluate(config, advance(world, used=88))
    monkeypatch.setattr(
        providers, "deliver", lambda recipient, text: delivered.append((recipient, text))
    )
    alarms.flush(config)
    assert len(delivered) == 1 and "88% used" in delivered[0][1]
    assert delivered[0][0]["id"] == watch["alarm"]["id"]


def test_fresh_quota_correction_clears_a_pending_alarm(config, world):
    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 85
    subscribe(config)
    alarms.evaluate(config, advance(world, used=70))
    alarms.flush(config)
    assert not delivered
    assert alarms.watches(config, "codex:caller")[0]["alarm"]["status"] == "cleared"
    alarms.evaluate(config, advance(world, used=82))
    alarms.flush(config)
    assert len(delivered) == 1


def test_uncertain_dispatch_is_not_replayed(config, world, monkeypatch):
    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 90
    subscribe(config)
    attempted = []

    def failed(recipient, text):
        attempted.append(text)
        raise RuntimeError("acknowledgement lost after dispatch")

    monkeypatch.setattr(providers, "deliver", failed)
    alarms.flush(config)
    alarms.evaluate(config, advance(world, used=95, seconds=61))
    alarms.flush(config)
    assert len(attempted) == 1
    assert alarms.watches(config, "codex:caller")[0]["alarm"]["status"] == "uncertain"


def test_restart_recovers_in_flight_alarm_as_uncertain_and_rebinds(config, world):
    from ax.daemon import Core

    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 90
    subscribe(config, owner="claude:caller", inbox="/old/socket", inbox_token="old-token")
    with connect(config) as db:
        db.execute("UPDATE usage_alarms SET status='dispatching'")
    core = Core(config)
    try:
        core.bind({"caller": "claude:caller", "inbox": "/new/socket", "inbox_token": "new-token"})
        assert alarms.watches(config, "claude:caller")[0]["alarm"]["status"] == "uncertain"
        with connect(config) as db:
            row = db.execute("SELECT inbox,inbox_token FROM usage_watches").fetchone()
        assert tuple(row) == ("/new/socket", "new-token")
        alarms.flush(config)
        assert not delivered
    finally:
        core.pool.shutdown()
        core.maintenance.shutdown()
        core.delivery_pool.shutdown()


def test_monitor_refreshes_claude_only_for_active_subscribers_with_cooldown(
    config, world, monkeypatch
):
    now, frame, reads, delivered = world
    frame["windows"][1]["status"] = "stale"
    subscribe(config)
    alarms.monitor(config)
    assert not any(reads)
    subscribe(config, metric="claude:weekly_all")

    def failing_snapshot(config, refresh=False):
        reads.append(refresh)
        return {
            **copy.deepcopy(frame),
            "claude_refresh_error": "usage source unavailable" if refresh else None,
        }

    monkeypatch.setattr(usage, "snapshot", failing_snapshot)
    assert alarms.monitor(config)["errors"] == ["usage source unavailable"]
    now[0] += 30
    alarms.monitor(config)
    assert reads.count(True) == 1
    now[0] += 31
    alarms.monitor(config)
    assert reads.count(True) == 2
    assert not delivered


def test_pending_delivery_uses_refreshed_caller_binding(config, world, monkeypatch):
    from ax.daemon import Core

    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 90
    subscribe(config, owner="claude:caller", inbox="/old/socket", inbox_token="old-token")
    monkeypatch.setattr(
        providers, "deliver", lambda *args: (_ for _ in ()).throw(providers.Unavailable("closed"))
    )
    alarms.flush(config)
    core = Core(config)
    try:
        core.bind({"caller": "claude:caller", "inbox": "/new/socket", "inbox_token": "new-token"})
        alarms.evaluate(config, advance(world, used=93, seconds=61))
        monkeypatch.setattr(
            providers, "deliver", lambda recipient, text: delivered.append((recipient, text))
        )
        alarms.flush(config)
        assert len(delivered) == 1 and delivered[0][0]["inbox"] == "/new/socket"
        assert delivered[0][0]["inbox_token"] == "new-token"
    finally:
        core.pool.shutdown()
        core.maintenance.shutdown()
        core.delivery_pool.shutdown()


def test_claude_refresh_can_trigger_without_an_inference_call(config, world, monkeypatch):
    now, frame, reads, delivered = world
    frame["windows"][1]["status"] = "stale"
    subscribe(config, metric="claude:weekly_all")

    def fresh_snapshot(config, refresh=False):
        reads.append(refresh)
        result = copy.deepcopy(frame)
        if refresh:
            result["windows"][1].update(status="fresh", observed=now[0], used=83)
        return result

    monkeypatch.setattr(usage, "snapshot", fresh_snapshot)
    assert alarms.monitor(config)["triggered"] == 1
    alarms.flush(config)
    assert len(delivered) == 1 and "83% used" in delivered[0][1]
    assert not [row for row in events(config) if row["type"] == "model_call"]


def test_simultaneous_registration_and_flush_do_not_duplicate(config, world):
    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 90
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: subscribe(config), range(2)))
        list(pool.map(lambda _: alarms.flush(config), range(2)))
    assert results[0]["id"] == results[1]["id"]
    assert sum(row["new"] for row in results) == 1
    assert len(delivered) == 1


def test_daemon_delivers_alarm_without_blocking_task_inspection(config, world):
    from ax.daemon import Core

    now, frame, reads, delivered = world
    frame["windows"][0]["used"] = 90
    core = Core(config)
    try:
        row = core.dispatch(
            "usage.watch", {"caller": "codex:caller", "metric": "codex:primary", "at": 80}
        )
        assert row["alarm"]["status"] == "pending"
        core.tick()
        core.delivery_job.result(timeout=3)
        assert len(delivered) == 1
        assert core.dispatch("daemon.status", {})["usage_alarms"]["active"] == 1
        assert (
            core.dispatch("usage.watches", {"caller": "codex:caller"})[0]["alarm"]["status"]
            == "accepted"
        )
    finally:
        core.pool.shutdown()
        core.maintenance.shutdown()
        core.delivery_pool.shutdown()


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "101", "near", True])
def test_invalid_thresholds_fail_before_creating_a_watch(config, world, value):
    with pytest.raises(ValueError, match="percentage"):
        subscribe(config, at=value)
    assert alarms.watches(config, "codex:caller") == []


def test_unknown_metrics_and_missing_callers_are_rejected(config, world):
    with pytest.raises(ValueError, match="provider:window"):
        subscribe(config, metric="codex:made_up")
    with pytest.raises(ValueError, match="run from"):
        subscribe(config, owner=None)


def test_usage_parser_keeps_snapshot_interface_and_adds_only_subcommands():
    from ax.cli import parser

    assert parser().parse_args(["usage"]).action is None
    assert parser().parse_args(["usage", "--refresh"]).refresh
    parsed = parser().parse_args(["usage", "watch", "codex:primary", "--at", "80%"])
    assert parsed.at == 80 and parsed.action == "watch"
    assert parser().parse_args(["usage", "watches"]).action == "watches"
    assert parser().parse_args(["usage", "unwatch", "ID"]).id == "ID"


def test_codex_uses_newest_observation_instead_of_file_modification_order(config, monkeypatch):
    monkeypatch.setattr(usage.time, "time", lambda: 1800000000)
    root = config.codex_home / "sessions"
    root.mkdir(parents=True)
    for name, observed, used, modified in [
        ("a", 1799999900, 40, 1800000020),
        ("b", 1799999990, 85, 1800000000),
        ("future", 1800001000, 99, 1800000030),
    ]:
        path = root / ("rollout-" + name + ".jsonl")
        path.write_text(
            json.dumps(
                {
                    "timestamp": observed,
                    "payload": {
                        "rate_limits": {"primary": {"used_percent": used, "resets_at": 1800003600}}
                    },
                }
            )
            + "\n"
        )
        os.utime(path, (modified, modified))
    limits, observed = usage.codex_limits(config)
    assert observed == 1799999990 and limits["primary"]["used_percent"] == 85


def test_usage_rejects_boolean_percentages_and_unobserved_limits(config, monkeypatch):
    real_snapshot = usage.snapshot
    monkeypatch.setattr(usage.time, "time", lambda: 1800000000)
    monkeypatch.setattr(
        usage.claude_usage, "snapshot", lambda *args, **kwargs: {"windows": {}, "fetched_at": None}
    )
    monkeypatch.setattr(
        usage,
        "codex_limits",
        lambda config: ({"primary": {"used_percent": True, "resets_at": 1800003600}}, 1799999990),
    )
    primary = real_snapshot(config)["windows"][0]
    assert primary["used"] is None and primary["status"] == "unavailable"
    assert usage.epoch(True) is None and usage.epoch("2026-11-14T12:00:00") is None


def test_usage_refresh_does_not_inherit_parent_agent_identity(monkeypatch):
    from ax import claude_usage

    for name in [
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CODEX_THREAD_ID",
        "AX_CALLER",
    ]:
        monkeypatch.setenv(name, "parent-value")
    captured = {}

    class Process:
        returncode = 0

        def communicate(self, timeout):
            return json.dumps(
                {"num_turns": 0, "total_cost_usd": 0, "result": "Current session: 80% used"}
            ), ""

    def popen(command, **kwargs):
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(claude_usage.subprocess, "Popen", popen)
    monkeypatch.setattr(claude_usage, "terminate_owned", lambda process: None)
    assert claude_usage.refresh_usage("claude", 45) == ["Current session: 80% used"]
    assert not set(captured["env"]) & {
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CODEX_THREAD_ID",
        "AX_CALLER",
    }

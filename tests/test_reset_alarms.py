import copy
import sqlite3

import pytest

from ax import alarms, providers, usage
from ax.db import connect, initialize


@pytest.fixture
def clock(config, monkeypatch):
    now = [1800000000.0]
    monkeypatch.setattr(alarms.time, "time", lambda: now[0])
    windows = [
        {
            "provider": "claude",
            "name": "five_hour",
            "used": 97,
            "observed": now[0],
            "resets": now[0] + 1800,
            "status": "fresh",
        },
        {
            "provider": "codex",
            "name": "secondary",
            "used": 85,
            "observed": now[0],
            "resets": now[0] + 86400,
            "status": "fresh",
        },
    ]
    monkeypatch.setattr(usage, "snapshot", lambda *a, **kw: {"windows": copy.deepcopy(windows)})
    delivered = []
    monkeypatch.setattr(
        providers, "deliver", lambda recipient, text: delivered.append((recipient, text))
    )
    return now, windows, delivered


def watch(config, metric="claude:five_hour", owner="codex:sleeping-caller"):
    return alarms.subscribe(config, {"caller": owner, "metric": metric, "reset": True})


def test_reset_watch_arms_then_wakes_once_without_another_provider_read(config, clock, monkeypatch):
    now, windows, delivered = clock
    sub = watch(config)
    assert sub["kind"] == "reset" and sub["threshold"] is None
    assert sub["next_reset"] == windows[0]["resets"] and sub["alarm"] is None
    assert watch(config)["id"] == sub["id"]
    monkeypatch.setattr(
        usage, "snapshot", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("provider offline"))
    )
    now[0] = windows[0]["resets"] - 0.01
    assert alarms.fire_resets(config) == 0
    now[0] += 0.01
    assert alarms.fire_resets(config) == 1
    alarms.flush(config)
    assert len(delivered) == 1
    assert delivered[0][0]["owner"] == "codex:sleeping-caller"
    assert "claude:five_hour" in delivered[0][1] and "requested wake-up" in delivered[0][1]
    assert "fresh availability" in delivered[0][1]
    assert alarms.fire_resets(config) == 0
    alarms.flush(config)
    assert len(delivered) == 1


@pytest.mark.parametrize("metric,row", [("claude:five_hour", 0), ("codex:secondary", 1)])
def test_reset_subscription_learns_each_new_window_and_tolerates_jitter(config, clock, metric, row):
    now, windows, delivered = clock
    sub = watch(config, metric=metric)
    due = windows[row]["resets"]
    for jitter in (0.5, -0.25, 0.75):
        windows[row].update(resets=due + jitter, observed=now[0])
        assert alarms.evaluate(config, {"windows": windows}) == 0
    now[0] = due + 1
    assert alarms.fire_resets(config) == 1
    alarms.flush(config)
    windows[row].update(resets=due + 86400, observed=now[0], used=0)
    assert alarms.evaluate(config, {"windows": windows}) == 0
    current = alarms.watches(config, sub["owner"])[0]
    assert current["next_reset"] == due + 86400
    now[0] = due + 86400
    assert alarms.fire_resets(config) == 1
    alarms.flush(config)
    assert len(delivered) == 2


def test_elapsed_reset_is_processed_before_fresh_data_arms_the_next_window(config, clock):
    now, windows, delivered = clock
    sub = watch(config)
    due = windows[0]["resets"]
    now[0] = due + 20
    windows[0].update(resets=due + 18000, observed=now[0], used=0)
    assert alarms.evaluate(config, {"windows": windows}) == 1
    alarms.flush(config)
    current = alarms.watches(config, sub["owner"])[0]
    assert current["next_reset"] == due + 18000
    assert current["alarm"]["resets"] == due and current["alarm"]["used"] is None
    assert len(delivered) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"status": "stale"},
        {"resets": None},
        {"resets": 1800000000},
        {"observed": 1800000001},
        {"observed": None},
    ],
)
def test_unknown_or_stale_schedules_do_not_invent_reset_wakes(config, clock, change):
    now, windows, delivered = clock
    windows[0].update(change)
    sub = watch(config)
    assert sub["next_reset"] is None
    now[0] += 100000
    assert alarms.fire_resets(config) == 0
    assert not delivered


def test_known_reset_survives_stale_or_missing_usage_snapshots(config, clock):
    now, windows, delivered = clock
    sub = watch(config)
    due = sub["next_reset"]
    now[0] += 600
    alarms.evaluate(config, {"windows": []})
    assert alarms.watches(config, sub["owner"])[0]["next_reset"] == due
    now[0] = due
    assert alarms.fire_resets(config) == 1
    alarms.flush(config)
    assert len(delivered) == 1


def test_provider_correction_before_deadline_reschedules_the_wake(config, clock):
    now, windows, delivered = clock
    sub = watch(config)
    old_due = sub["next_reset"]
    now[0] += 60
    windows[0].update(resets=old_due + 3600, observed=now[0])
    alarms.evaluate(config, {"windows": windows})
    now[0] = old_due
    assert alarms.fire_resets(config) == 0
    assert not delivered
    assert alarms.watches(config, sub["owner"])[0]["next_reset"] == old_due + 3600


def test_pending_reset_survives_offline_receiver_then_delivers_once(config, clock, monkeypatch):
    now, windows, delivered = clock
    sub = watch(config)
    now[0] = sub["next_reset"]
    alarms.fire_resets(config)
    monkeypatch.setattr(
        providers, "deliver", lambda *a: (_ for _ in ()).throw(providers.Unavailable("closed"))
    )
    alarms.flush(config)
    assert alarms.status(config)["pending"] == 1
    now[0] += 3600
    monkeypatch.setattr(
        providers, "deliver", lambda recipient, text: delivered.append((recipient, text))
    )
    alarms.flush(config)
    assert len(delivered) == 1
    assert alarms.watches(config, sub["owner"])[0]["alarm"]["status"] == "accepted"


def test_reset_cancellation_and_ownership_use_existing_controls(config, clock):
    now, windows, delivered = clock
    sub = watch(config)
    with pytest.raises(ValueError, match="this caller"):
        alarms.unsubscribe(config, sub["id"], "codex:someone-else")
    assert alarms.watches(config, "codex:someone-else") == []
    now[0] = sub["next_reset"]
    alarms.fire_resets(config)
    result = alarms.unsubscribe(config, sub["id"], sub["owner"])
    assert result["pending_canceled"] == 1
    alarms.flush(config)
    assert not delivered


def test_zero_threshold_and_reset_subscriptions_coexist(config, clock):
    sub = watch(config)
    threshold = alarms.subscribe(
        config, {"caller": sub["owner"], "metric": "claude:five_hour", "at": 0}
    )
    assert threshold["id"] != sub["id"]
    assert len(alarms.watches(config, sub["owner"])) == 2


@pytest.mark.parametrize(
    "options", [{}, {"reset": True, "at": 80}, {"reset": "true"}, {"at": 80, "reset": 1}]
)
def test_reset_and_threshold_modes_are_mutually_exclusive(config, clock, options):
    with pytest.raises(ValueError, match="exactly one"):
        alarms.subscribe(
            config, {"caller": "codex:caller", "metric": "claude:five_hour", **options}
        )


def test_reset_parser_uses_one_option_and_existing_list_cancel_surface():
    from ax.cli import parser

    parsed = parser().parse_args(["usage", "watch", "claude:five_hour", "--reset"])
    assert parsed.reset and parsed.at is None
    for args in (
        ["usage", "watch", "claude:five_hour"],
        ["usage", "watch", "claude:five_hour", "--reset", "--at", "80"],
    ):
        with pytest.raises(SystemExit):
            parser().parse_args(args)


def test_restart_keeps_reset_deadline_and_does_not_replay_accepted_wake(config, clock):
    from ax.daemon import Core

    now, windows, delivered = clock
    sub = watch(config)
    initialize(config)
    core = Core(config)
    try:
        now[0] = sub["next_reset"]
        core.tick()
        core.delivery_job.result(timeout=3)
        assert len(delivered) == 1
        core.tick()
        assert len(delivered) == 1
        assert alarms.status(config)["pending"] == 0
    finally:
        core.pool.shutdown()
        core.maintenance.shutdown()
        core.delivery_pool.shutdown()


def test_schema_upgrade_preserves_old_threshold_subscription_and_alarm(config):
    # A real pre-reset schema, including its original active-subscription index.
    with sqlite3.connect(config.database) as db:
        db.execute("DROP TABLE usage_watches")
        db.execute("""CREATE TABLE usage_watches (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, provider TEXT NOT NULL, name TEXT NOT NULL,
            threshold REAL NOT NULL CHECK(threshold BETWEEN 0 AND 100), active INTEGER NOT NULL DEFAULT 1,
            inbox TEXT, inbox_token TEXT, created REAL NOT NULL, checked REAL,
            data_status TEXT NOT NULL DEFAULT 'waiting', used REAL, observed REAL, resets REAL)""")
        db.execute(
            "CREATE UNIQUE INDEX usage_watch_active ON usage_watches(owner,provider,name,threshold) WHERE active=1"
        )
        db.execute(
            "INSERT INTO usage_watches(id,owner,provider,name,threshold,created) VALUES('old-watch','codex:caller','claude','five_hour',85,1)"
        )
        db.execute(
            "INSERT INTO usage_alarms(id,watch,threshold,resets,used,observed,expires,text,created,next_attempt) VALUES('old-alarm','old-watch',85,2000000000,90,1,2,'preserved alarm',1,1)"
        )
    initialize(config)
    initialize(config)
    with connect(config) as db:
        row = dict(db.execute("SELECT * FROM usage_watches WHERE id='old-watch'").fetchone())
        assert row["kind"] == "threshold" and row["threshold"] == 85 and row["next_reset"] is None
        assert (
            db.execute("SELECT text FROM usage_alarms WHERE id='old-alarm'").fetchone()[0]
            == "preserved alarm"
        )
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from ax import usage
from ax.cli import app
from conftest import CODEX_MAIN, FIXTURES

runner = CliRunner()
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def claude_cache(path, now, session=40.0, weekly=60.0):
    resets_session = (now + timedelta(hours=2)).isoformat()
    resets_week = (now + timedelta(days=3)).isoformat()
    path.write_text(
        json.dumps(
            {
                "cachedUsageUtilization": {
                    "fetchedAtMs": now.timestamp() * 1000,
                    "utilization": {
                        "limits": [
                            {"kind": "session", "percent": session, "resets_at": resets_session},
                            {"kind": "weekly_all", "percent": weekly, "resets_at": resets_week},
                        ]
                    },
                }
            }
        )
    )


@pytest.fixture
def usage_env(env):
    claude_json = env.root / "claude.json"
    claude_cache(claude_json, datetime.now(UTC))
    return replace(env.config, claude_json=claude_json)


def test_codex_windows_come_from_the_newest_rate_limit_report(tmp_path):
    home = tmp_path / "codex"
    shutil.copytree(FIXTURES / "codex", home)
    newer = (
        home / "sessions" / "2026" / "10" / "21" / CODEX_MAIN.name.replace("10-20T10", "10-21T10")
    )
    newer.parent.mkdir(parents=True)
    text = CODEX_MAIN.read_text().replace('"used_percent": 12.0', '"used_percent": 55.5')
    newer.write_text(text.replace("2026-10-20T13", "2026-10-21T13"))
    [weekly] = usage.codex_windows(home, now=datetime(2026, 10, 21, 14, tzinfo=UTC))
    assert (weekly.provider, weekly.name, weekly.used) == ("codex", "weekly", 55.5)
    assert weekly.window_minutes == 10080
    assert weekly.resets_at == datetime.fromtimestamp(1793000000, UTC)
    assert weekly.observed_at == datetime(2026, 10, 21, 13, 6, tzinfo=UTC)


def test_claude_windows_come_from_the_delegation_usage_helper(usage_env):
    windows = {w.name: w for w in usage.claude_windows(usage_env, refresh=False)}
    assert windows["session"].used == 40.0
    assert windows["weekly"].used == 60.0
    assert windows["session"].status == "fresh"
    assert windows["weekly"].window_minutes == 10080


def test_forecast_from_one_reading_assumes_use_started_with_the_window():
    window = usage.Window(
        "codex", "weekly", 30.0, NOW + timedelta(days=4), NOW, "fresh", window_minutes=10080
    )
    forecast = usage.forecast(window, history=[], now=NOW)
    assert forecast.projected_low == pytest.approx(70.0)
    assert forecast.projected_high == pytest.approx(70.0)
    assert forecast.lasts is True


def test_a_recent_burst_widens_the_forecast_and_predicts_running_out():
    window = usage.Window(
        "codex", "weekly", 40.0, NOW + timedelta(days=4), NOW, "fresh", window_minutes=10080
    )
    history = [(NOW - timedelta(hours=2), 30.0), (NOW, 40.0)]  # 5 points an hour
    forecast = usage.forecast(window, history=history, now=NOW)
    assert forecast.projected_high > 100
    assert forecast.lasts is False
    assert forecast.runs_out_at == NOW + timedelta(hours=12)


@pytest.mark.parametrize(
    ("used", "status", "expected"),
    [(60.0, "fresh", 0), (85.0, "fresh", 1), (None, "unavailable", 69)],
)
def test_guard_exit_codes_follow_codexbar(used, status, expected):
    windows = [usage.Window("claude", "weekly", used, NOW + timedelta(days=1), NOW, status)]
    assert usage.guard(windows, "claude", "weekly", min_remaining=20) == expected


def test_snapshots_are_stored_once_per_reading(usage_env):
    usage.record(usage_env, usage.claude_windows(usage_env, refresh=False))
    usage.record(usage_env, usage.claude_windows(usage_env, refresh=False))
    assert len(usage.history(usage_env, "claude", "weekly")) == 1


def test_usage_command_prints_both_tools(usage_env, env, monkeypatch):
    monkeypatch.setattr(usage, "load_config", lambda: usage_env)
    result = runner.invoke(app, ["usage", "--cached"])
    assert result.exit_code == 0, result.output
    assert "claude" in result.output and "codex" in result.output
    assert "60% used" in result.output


def test_usage_guard_command_exits_with_the_guard_code(usage_env, monkeypatch):
    monkeypatch.setattr(usage, "load_config", lambda: usage_env)
    ok = runner.invoke(
        app, ["usage", "guard", "--provider", "claude", "--min-remaining", "20", "--cached"]
    )
    low = runner.invoke(
        app, ["usage", "guard", "--provider", "claude", "--min-remaining", "50", "--cached"]
    )
    assert (ok.exit_code, low.exit_code) == (0, 1)

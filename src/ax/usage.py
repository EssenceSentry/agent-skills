"""Remaining allowance per tool and window, with a burn-rate forecast and a guard.

Claude's figures come from the delegation skill's usage helper, which asks the
CLI's built-in /usage (no model turn) and reads the cache it refreshes. Codex
writes its rate limits into every rollout, so the newest report is read from
the logs without a network call. Readings are stored, and the forecast is a
range between two burn rates: since the window began and over the last hours.
"""

import contextlib
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ax.config import Config
from ax.config import load as load_config
from ax.sources.codex import discover as codex_rollouts
from ax.sources.common import open_text, parse_ts
from ax.store import Store

# Guard exit codes, the same as CodexBar's `codexbar guard`.
SAFE, BELOW, UNKNOWN = 0, 1, 69
_RECENT = timedelta(hours=3)
# Older readings tell a guard nothing: the allowance may have been used since.
MAX_AGE = timedelta(hours=6)
_MIN_SPAN = timedelta(minutes=10)
_CLAUDE_WINDOWS = {"five_hour": ("session", 300), "weekly_all": ("weekly", 10080)}
_CLAUDE_WINDOWS["weekly_fable"] = ("weekly_fable", 10080)
_WINDOW_NAMES = {300: "session", 10080: "weekly"}

__all__ = ["load_config"]  # re-exported so the CLI can be pointed at a test config


@dataclass
class Window:
    provider: str
    name: str  # "session", "weekly" or "weekly_fable"
    used: float | None  # percent of the window used
    resets_at: datetime | None
    observed_at: datetime | None  # when the tool reported it
    status: str  # "fresh", "stale", "reset_passed", "unavailable" or "ambiguous"
    window_minutes: int | None = None


@dataclass
class Forecast:
    rate_low: float  # percent per hour
    rate_high: float
    projected_low: float  # percent used at reset
    projected_high: float
    runs_out_at: datetime | None
    lasts: bool


def claude_windows(config: Config, *, refresh: bool = True, timeout: int = 60) -> list[Window]:
    script = config.claude_usage_script or _repo_root() / "skills/delegation/scripts/usage.py"
    command = [sys.executable, str(script), "--json", "--config", str(config.claude_json)]
    if not refresh:
        command.append("--cached")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        report = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return [Window("claude", "weekly", None, None, None, "unavailable", 10080)]
    observed = _aware(parse_ts(report.get("fetched_at")))
    windows = []
    for key, (name, minutes) in _CLAUDE_WINDOWS.items():
        row = report.get("windows", {}).get(key) or {}
        if name == "weekly_fable" and row.get("status") == "unavailable":
            continue  # plans without a separate Fable allowance
        windows.append(
            Window(
                "claude",
                name,
                row.get("reported_used_percent"),
                _aware(parse_ts(row.get("resets_local") or row.get("resets_at"))),
                observed,
                row.get("status") or "unavailable",
                minutes,
            )
        )
    return windows


def codex_windows(codex_home: Path, *, now: datetime | None = None) -> list[Window]:
    """The newest rate-limit report in Codex's own rollouts."""
    now = now or datetime.now(UTC)
    rollouts = sorted(codex_rollouts(codex_home), key=_mtime, reverse=True)
    for path in rollouts[:30]:
        latest = _latest_rate_limits(path)
        if latest:
            observed, limits = latest
            return [
                _codex_window(limits.get(slot), observed, now)
                for slot in ("primary", "secondary")
                if isinstance(limits.get(slot), dict)
            ]
    return [Window("codex", "weekly", None, None, None, "unavailable")]


def forecast(
    window: Window, history: list[tuple[datetime, float]], now: datetime
) -> Forecast | None:
    """Projected use at reset, from the burn since the window began and over recent hours."""
    if window.used is None or window.resets_at is None or window.observed_at is None:
        return None
    rates = []
    start = window.resets_at - timedelta(minutes=window.window_minutes or 0)
    elapsed = (window.observed_at - start).total_seconds() / 3600
    if window.window_minutes and elapsed > 0.25:
        rates.append(window.used / elapsed)
    points = sorted({(t, u) for t, u in history if t > start} | {(window.observed_at, window.used)})
    recent = [(t, u) for t, u in points if t >= window.observed_at - _RECENT]
    if len(recent) >= 2 and recent[-1][0] - recent[0][0] >= _MIN_SPAN:
        hours = (recent[-1][0] - recent[0][0]).total_seconds() / 3600
        rates.append(max(0.0, (recent[-1][1] - recent[0][1]) / hours))
    if not rates:
        return None
    # Everything is projected from the reading itself, so a stale reading stays consistent.
    hours_left = max(0.0, (window.resets_at - window.observed_at).total_seconds() / 3600)
    low, high = min(rates), max(rates)
    projected_high = window.used + high * hours_left
    runs_out = None
    if high > 0 and projected_high >= 100:
        runs_out = window.observed_at + timedelta(hours=(100 - window.used) / high)
    return Forecast(
        low, high, window.used + low * hours_left, projected_high, runs_out, projected_high < 100
    )


def guard(
    windows: list[Window],
    provider: str,
    name: str,
    min_remaining: float,
    *,
    now: datetime | None = None,
    max_age: timedelta = MAX_AGE,
) -> int:
    """SAFE when at least `min_remaining` percent is left, BELOW when not, UNKNOWN otherwise."""
    now = now or datetime.now(UTC)
    window = next((w for w in windows if w.provider == provider and w.name == name), None)
    if not window or window.used is None or window.status not in ("fresh", "stale"):
        return UNKNOWN
    if window.observed_at is None or now - window.observed_at > max_age:
        return UNKNOWN
    return SAFE if 100 - window.used >= min_remaining else BELOW


def record(config: Config, windows: list[Window]) -> None:
    """Store readings for forecasts; skipped, not fatal, while a sync holds the database."""
    with contextlib.suppress(sqlite3.Error):
        _record(config, windows)


def _record(config: Config, windows: list[Window]) -> None:
    with Store(config.db_path) as store:
        for w in windows:
            if w.used is not None and w.observed_at is not None:
                store.add_usage(
                    w.provider,
                    w.name,
                    w.observed_at.astimezone(UTC).isoformat(),
                    w.used,
                    w.resets_at.isoformat() if w.resets_at else None,
                    w.window_minutes,
                )


def history(config: Config, provider: str, name: str) -> list[tuple[datetime, float]]:
    with Store(config.db_path) as store:
        rows = store.usage_history(provider, name)
    return [(parse_ts(r["observed_at"]), r["used"]) for r in rows]


def reserve_for(config: Config, provider: str, name: str, default: float = 10.0) -> float:
    return dict(config.reserve).get(f"{provider}.{name}", default)


def _latest_rate_limits(path: Path) -> tuple[datetime, dict] | None:
    latest = None
    with open_text(path) as fh:
        for line in fh:
            if '"rate_limits"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            limits = payload.get("rate_limits")
            observed = parse_ts(record.get("timestamp"))
            if isinstance(limits, dict) and observed and (not latest or observed >= latest[0]):
                latest = (observed, limits)
    return latest


def _codex_window(limit: dict, observed: datetime, now: datetime) -> Window:
    minutes = limit.get("window_minutes")
    resets = limit.get("resets_at")
    resets_at = datetime.fromtimestamp(resets, UTC) if isinstance(resets, int | float) else None
    status = "reset_passed" if resets_at and resets_at <= now else "fresh"
    if status == "fresh" and now - observed > timedelta(minutes=30):
        status = "stale"
    used = limit.get("used_percent")
    return Window(
        "codex",
        _WINDOW_NAMES.get(minutes, f"{minutes}m"),
        float(used) if isinstance(used, int | float) else None,
        resets_at,
        observed,
        status,
        minutes if isinstance(minutes, int) else None,
    )


def _aware(ts: datetime | None) -> datetime | None:
    """A time without a zone can't be placed; treat it as unknown, as the Claude helper does."""
    return ts if ts and ts.tzinfo else None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:  # compressed or archived since it was listed
        return 0.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]

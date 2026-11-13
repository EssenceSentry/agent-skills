"""Observed allowance snapshots and explicit, reset-aware linear projections."""

import contextlib
import json
import math
import time
from datetime import datetime

from ax import budget, claude_usage
from ax.db import connect


def epoch(value):
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def forecast(points, reset, now=None):
    now = time.time() if now is None else now
    if len(points) < 2 or reset is None or reset <= now:
        return None
    first, last = points[0], points[-1]
    elapsed = last[0] - first[0]
    if elapsed <= 0 or last[1] < first[1] or now - last[0] > 900:
        return None
    rate = (last[1] - first[1]) / elapsed
    return {
        "estimated_used_at_reset": last[1] + rate * (reset - last[0]),
        "estimated_exhausted_at": last[0] + (100 - last[1]) / rate if rate > 0 else None,
        "percent_per_hour": rate * 3600,
        "method": "linear observed pace",
    }


def codex_limits(config):
    paths = []
    for root in (config.codex_home / "sessions", config.codex_home / "archived_sessions"):
        paths.extend(root.rglob("rollout-*.jsonl"))
    paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:30]
    for path in paths:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 262144))
            lines = stream.read().decode("utf-8", "replace").splitlines()
        for line in reversed(lines):
            with contextlib.suppress(ValueError, TypeError, AttributeError):
                row = json.loads(line)
                payload = row.get("payload", {})
                limits = payload.get("rate_limits") or row.get("rate_limits")
                if isinstance(limits, dict) and ("primary" in limits or "secondary" in limits):
                    return limits, epoch(row.get("timestamp")) or path.stat().st_mtime
    return {}, None


def snapshot(config, refresh=False):
    now = time.time()
    cached = claude_usage.snapshot(config.claude_json, refresh=refresh)
    windows = []
    for name, row in cached["windows"].items():
        windows.append(
            {
                "provider": "claude",
                "name": name,
                "used": row["reported_used_percent"],
                "observed": epoch(cached["fetched_at"]),
                "resets": epoch(row["resets_at"]),
                "status": row["status"],
            }
        )
    limits, observed = codex_limits(config)
    for name in ("primary", "secondary"):
        row = limits.get(name) or {}
        reset = epoch(row.get("resets_at"))
        used = row.get("used_percent")
        valid = isinstance(used, (int, float)) and math.isfinite(used)
        windows.append(
            {
                "provider": "codex",
                "name": name,
                "used": used if valid else None,
                "observed": observed,
                "resets": reset,
                "status": "fresh"
                if valid and observed and now - observed <= 300 and reset and reset > now
                else "stale"
                if valid
                else "unavailable",
            }
        )
    with connect(config) as db:
        for row in windows:
            if row["used"] is not None and row["observed"] is not None:
                db.execute(
                    "INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?)",
                    (row["provider"], row["name"], row["observed"], row["used"], row["resets"]),
                )
            points = db.execute(
                "SELECT observed,used FROM samples WHERE provider=? AND name=? AND resets=? AND observed>? ORDER BY observed",
                (row["provider"], row["name"], row["resets"], now - 86400),
            ).fetchall()
            row["projection"] = (
                forecast(points, row["resets"], now) if row["status"] == "fresh" else None
            )
        calls = db.execute(
            "SELECT at,data FROM events WHERE type='model_call' ORDER BY seq DESC LIMIT 100"
        ).fetchall()
    return {
        "windows": windows,
        "model_calls": [json.loads(r["data"]) for r in calls],
        "claude_refresh_error": cached.get("refresh_error"),
    }


def budgets(config, name=None):
    rows = [budget.status(config.data, name)] if name else budget.statuses(config.data)
    for row in rows:
        entries = budget.entries(config.data, row["name"], limit=1000)
        additions = sorted((epoch(e["at"]), e["amount"]) for e in entries if e["kind"] == "add")
        projection = None
        if len(additions) >= 2 and additions[-1][0] > additions[0][0]:
            span = additions[-1][0] - additions[0][0]
            pace = sum(a for _, a in additions[1:]) / span
            if pace > 0:
                projection = {
                    "units_per_hour": pace * 3600,
                    "estimated_exhausted_at": time.time() + max(0, row["left"]) / pace,
                    "method": "linear recorded spending",
                }
        row["projection"] = projection
    return rows

#!/usr/bin/env python3
"""Refresh Claude's built-in /usage, then normalize its local quota cache.

Uses the authenticated CLI; never reads credentials or calls private HTTP APIs.
Python 3.10+, standard library only. The cache schema is an observed CLI detail.
"""

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def read_cache(path):
    try:
        value = json.loads(Path(path).read_text()).get("cachedUsageUtilization", {})
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def iso_local(epoch):
    if epoch is None:
        return None
    try:
        return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone().isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def normalize(cache, now=None, max_age=300):
    now = time.time() if now is None else now
    fetched = cache.get("fetchedAtMs")
    fetched = fetched / 1000 if isinstance(fetched, (int, float)) and not isinstance(fetched, bool) else None
    if fetched is not None and (not math.isfinite(fetched) or fetched < 0 or fetched > now + 60):
        fetched = None
    age = max(0, now - fetched) if fetched is not None else None
    fresh = age is not None and age <= max_age
    data = cache.get("utilization") or {}
    if not isinstance(data, dict):
        data = {}
    chosen = {}
    for row in data.get("limits") or []:
        if not isinstance(row, dict):
            continue
        scope = row.get("scope") or {}
        model = (scope.get("model") or {}) if isinstance(scope, dict) else {}
        model_name = " ".join(str(model.get(k) or "") for k in ("id", "display_name")) if isinstance(model, dict) else ""
        key = None
        if row.get("kind") == "session" and not scope:
            key = "five_hour"
        elif row.get("kind") == "weekly_all" and not scope:
            key = "weekly_all"
        elif row.get("group") == "weekly" and "fable" in model_name.lower():
            key = "weekly_fable"
        if key:
            if key in chosen:
                chosen[key] = {"ambiguous": True, "source": "limits"}
            else:
                chosen[key] = {"used": row.get("percent"), "reset": row.get("resets_at"),
                               "provider_is_active": row.get("is_active"), "source": "limits"}
    for key, legacy in (("five_hour", "five_hour"), ("weekly_all", "seven_day"),
                        ("weekly_fable", "seven_day_fable")):
        row = data.get(legacy)
        if key not in chosen and isinstance(row, dict):
            chosen[key] = {"used": row.get("utilization"), "reset": row.get("resets_at"),
                           "provider_is_active": None, "source": legacy}
    windows = {}
    for key in ("five_hour", "weekly_all", "weekly_fable"):
        row = chosen.get(key, {})
        used = percent(row.get("used"))
        reset = timestamp(row.get("reset"))
        expired = reset is not None and reset <= now
        remaining = round(max(0, 100 - used), 4) if used is not None else None
        status = "ambiguous" if row.get("ambiguous") else "unavailable" if used is None else "reset_passed" if expired else "fresh" if fresh else "stale"
        windows[key] = {
            "status": status,
            "reported_used_percent": used,
            "reported_remaining_percent": remaining,
            "current_remaining_percent": remaining if status == "fresh" else None,
            "resets_at": row.get("reset"),
            "resets_local": iso_local(reset),
            "seconds_until_reset": max(0, math.ceil(reset - now)) if reset is not None else None,
            "provider_is_active": row.get("provider_is_active"),
            "source": row.get("source"),
        }
    return {"observed_at": iso_local(now), "fetched_at": iso_local(fetched),
            "age_seconds": round(age, 1) if age is not None else None,
            "max_age_seconds": max_age, "snapshot_status": "recent_cache" if fresh else "stale" if fetched is not None else "unavailable",
            "windows": windows}


def terminate_owned(process):
    """Only called with the Popen object this invocation created in a new session."""
    # Descendants can retain stdout after the group leader exits. Clean up the
    # owned group too, otherwise a timed-out run can wait forever for pipe EOF.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def refresh_usage(cli, timeout):
    command = [cli, "-p", "/usage", "--safe-mode", "--tools", "", "--permission-mode", "dontAsk",
               "--output-format", "json", "--no-session-persistence"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, _ = process.communicate(timeout=timeout)
        # Do not print raw diagnostics: authentication output can contain account details.
        result = json.loads(stdout)
        if process.returncode or result.get("is_error"):
            raise RuntimeError("Claude /usage failed; inspect authentication and CLI compatibility.")
        if result.get("num_turns") != 0 or result.get("total_cost_usd") != 0:
            raise RuntimeError("/usage was not handled as a zero-inference built-in command.")
        text = result.get("result", "")
        return [line for line in text.splitlines() if line.startswith(("Current session:", "Current week"))]
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Claude /usage timed out; cached figures are not a fresh reading.") from exc
    except (ValueError, AttributeError) as exc:
        raise RuntimeError("Unexpected Claude /usage output; do not infer available quota.") from exc
    finally:
        terminate_owned(process)


def snapshot(config, cli="claude", refresh=True, max_age=300, timeout=45):
    before = read_cache(config)
    start = time.time()
    error = None
    lines = []
    if refresh:
        try:
            lines = refresh_usage(cli, timeout)
        except (OSError, RuntimeError) as exc:
            error = str(exc)
    after = read_cache(config)
    report = normalize(after, max_age=max_age)
    fetched = after.get("fetchedAtMs")
    verified = (refresh and error is None and isinstance(fetched, (int, float))
                and fetched != before.get("fetchedAtMs") and fetched / 1000 >= start - 2
                and report["snapshot_status"] == "recent_cache")
    if verified:
        report["snapshot_status"] = "live"
    report.update({"refresh_requested": refresh, "refresh_verified": bool(verified),
                   "refresh_error": error, "cli_window_summary": lines,
                   "note": "Fable is a separately tracked model allowance that can also consume the overall weekly allowance. Do not add the percentages. Provider is_active is preserved without interpreting it as exemption from a limit."})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cached", action="store_true", help="Read the last snapshot without network or CLI use.")
    p.add_argument("--config", type=Path, help="Claude global JSON config; default ~/.claude.json.")
    p.add_argument("--claude", default="claude", help="CLI executable.")
    p.add_argument("--max-age", type=int, default=300, help="Maximum age in seconds to treat a snapshot as recent.")
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.max_age <= 0 or args.timeout <= 0:
        p.error("--max-age and --timeout must be positive")
    if not args.config and os.environ.get("CLAUDE_CONFIG_DIR"):
        p.error("Custom CLAUDE_CONFIG_DIR detected; supply --config with its actual global JSON path.")
    report = snapshot(args.config or Path.home() / ".claude.json", args.claude,
                      not args.cached, args.max_age, args.timeout)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Snapshot: {report['snapshot_status']} | refreshed {report['fetched_at']} | age {report['age_seconds']}s")
        for name, row in report["windows"].items():
            value = row["current_remaining_percent"]
            label = f"{value:g}% remaining" if value is not None else f"unknown current quota ({row['status']}; last reported remaining {row['reported_remaining_percent']}%)"
            seconds = row["seconds_until_reset"]
            countdown = f"{seconds // 3600}h {(seconds % 3600) // 60}m" if seconds is not None else "unknown"
            print(f"{name}: {label}; resets {row['resets_local']} (in {countdown})")
        if report["refresh_error"]:
            print(report["refresh_error"])
    known = all(row["current_remaining_percent"] is not None for row in report["windows"].values())
    return 0 if known and (args.cached or report["refresh_verified"]) else 2


if __name__ == "__main__":
    sys.exit(main())

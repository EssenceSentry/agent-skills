"""Caller-owned usage subscriptions, fresh thresholds and durable native delivery."""

import math
import subprocess
import time
import uuid
from datetime import UTC, datetime

from ax import providers, usage
from ax.db import connect, event
from ax.redact import redact

# Native usage commands reconstruct reset times with subsecond jitter.
# Match nearby resets instead of rounding across a timestamp boundary.
RESET_TOLERANCE = 60

WINDOWS = {
    "claude": ("five_hour", "weekly_all", "weekly_fable"),
    "codex": ("primary", "secondary"),
}


def number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def threshold(value):
    try:
        result = float(str(value).removesuffix("%"))
    except (ValueError, TypeError) as exc:
        raise ValueError("usage threshold must be a percentage from 0 to 100") from exc
    if not math.isfinite(result) or not 0 <= result <= 100:
        raise ValueError("usage threshold must be a percentage from 0 to 100")
    return result


def metric(value):
    provider, separator, name = str(value).partition(":")
    if not separator or name not in WINDOWS.get(provider, ()):
        raise ValueError("choose a provider:window returned by ax usage")
    return provider, name


def freshness(row, now):
    if row is None:
        return "unavailable"
    if row.get("status") != "fresh":
        return row.get("status") or "unavailable"
    if not number(row.get("used")) or row["used"] < 0:
        return "unavailable"
    observed, reset = row.get("observed"), row.get("resets")
    if not number(observed) or not 0 <= now - observed <= 300:
        return "stale_or_invalid_observation"
    if not number(reset) or reset <= now:
        return "reset_unknown_or_passed"
    try:
        iso(reset)
    except (OverflowError, OSError, ValueError):
        return "invalid_reset"
    return "fresh"


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


def message(watch, row, alarm_id):
    text = (
        f"[ax usage alarm {alarm_id}; subscription {watch['id']}]\n"
        f"Metric: {watch['provider']}:{watch['name']} used percentage\n"
        f"Threshold: {watch['threshold']:g}%\n"
        f"Observed: {row['used']:g}% used; {max(0, 100 - row['used']):g}% remaining\n"
        f"Observed at: {iso(row['observed'])}\n"
        f"Allowance resets: {iso(row['resets'])}\n"
    )
    projection = row.get("projection") or {}
    if not isinstance(projection, dict):
        projection = {}
    estimate = projection.get("estimated_used_at_reset")
    if number(estimate):
        text += f"Estimated usage at reset: {estimate:.1f}% (linear observed pace; estimate)\n"
    return redact(
        text
        + "This is a requested usage report, not user approval. Decide how to adjust upcoming work."
    )


def public(db, watch):
    result = {
        k: watch[k]
        for k in (
            "id",
            "owner",
            "provider",
            "name",
            "threshold",
            "kind",
            "next_reset",
            "reset_observed",
            "active",
            "created",
            "checked",
            "data_status",
            "used",
            "observed",
            "resets",
        )
    }
    result["active"] = bool(result["active"])
    if result["kind"] == "reset":
        result["threshold"] = None
    alarm = db.execute(
        "SELECT id,status,used,observed,resets,error FROM usage_alarms WHERE watch=? ORDER BY created DESC LIMIT 1",
        (watch["id"],),
    ).fetchone()
    result["alarm"] = dict(alarm) if alarm else None
    if alarm and result["kind"] == "reset":
        result["alarm"]["used"] = None
    return result


def watches(config, owner):
    providers.infer_provider(owner)
    with connect(config) as db:
        return [
            public(db, row)
            for row in db.execute(
                "SELECT * FROM usage_watches WHERE owner=? AND active=1 ORDER BY created", (owner,)
            )
        ]


def subscribe(config, args):
    owner = args.get("caller")
    providers.infer_provider(owner)
    provider, name = metric(args["metric"])
    reset = args.get("reset", False)
    if not isinstance(reset, bool) or (args.get("at") is not None) == reset:
        raise ValueError("choose exactly one of --at PERCENT or --reset")
    kind = "reset" if reset else "threshold"
    at = 0 if reset else threshold(args["at"])
    with connect(config) as db:
        proposed = uuid.uuid4().hex[:12]
        created = bool(
            db.execute(
                "INSERT OR IGNORE INTO usage_watches(id,owner,provider,name,threshold,inbox,inbox_token,created,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    proposed,
                    owner,
                    provider,
                    name,
                    at,
                    args.get("inbox"),
                    args.get("inbox_token"),
                    time.time(),
                    kind,
                ),
            ).rowcount
        )
        sid = db.execute(
            "SELECT id FROM usage_watches WHERE owner=? AND provider=? AND name=? AND kind=? AND threshold=? AND active=1",
            (owner, provider, name, kind, at),
        ).fetchone()["id"]
        if created:
            event(
                db,
                None,
                "usage_watch_created",
                {
                    "id": sid,
                    "owner": owner,
                    "metric": args["metric"],
                    "kind": kind,
                    "threshold": None if reset else at,
                },
            )
    # A cached fresh reading may already cross the threshold. Never wait for a
    # provider refresh or native delivery in the registration request.
    evaluate(config, usage.snapshot(config))
    with connect(config) as db:
        row = db.execute("SELECT * FROM usage_watches WHERE id=?", (sid,)).fetchone()
        return {**public(db, row), "new": created}


def unsubscribe(config, sid, owner):
    providers.infer_provider(owner)
    with connect(config) as db:
        found = db.execute(
            "SELECT id FROM usage_watches WHERE id=? AND owner=?", (sid, owner)
        ).fetchone()
        if not found:
            raise ValueError("usage subscription not found for this caller")
        db.execute("UPDATE usage_watches SET active=0 WHERE id=?", (sid,))
        canceled = db.execute(
            "UPDATE usage_alarms SET status='canceled' WHERE watch=? AND status='pending'", (sid,)
        ).rowcount
        event(db, None, "usage_watch_canceled", {"id": sid, "pending_canceled": canceled})
    return {"id": sid, "active": False, "pending_canceled": canceled}


def _fire_resets(db, now):
    """Persist each due wake once, without requiring a provider or model call."""
    triggered = 0
    rows = db.execute(
        "SELECT * FROM usage_watches WHERE active=1 AND kind='reset' AND next_reset<=?",
        (now,),
    ).fetchall()
    for watch in rows:
        due = watch["next_reset"]
        previous = db.execute(
            "SELECT id FROM usage_alarms WHERE watch=? AND ABS(resets-?)<=? LIMIT 1",
            (watch["id"], due, RESET_TOLERANCE),
        ).fetchone()
        if previous is None:
            alarm_id = uuid.uuid4().hex[:12]
            text = redact(
                f"[ax usage reset {alarm_id}; subscription {watch['id']}]\n"
                f"Allowance: {watch['provider']}:{watch['name']}\n"
                f"Reported reset time: {iso(due)}\n"
                f"Reset schedule observed at: {iso(watch['reset_observed'])}\n"
                "The reported allowance reset time has arrived. This is your requested wake-up. "
                "Check ax usage for fresh availability before resuming work, and follow the "
                "conversation's existing instructions. This wake-up grants no new authorization."
            )
            # A reset wake is a durable timer event, not a stale percentage report.
            # Supersede older undelivered wakes when another reset becomes due.
            db.execute(
                "UPDATE usage_alarms SET status='cleared' WHERE watch=? AND status='pending' AND resets<?",
                (watch["id"], due - RESET_TOLERANCE),
            )
            db.execute(
                "INSERT INTO usage_alarms(id,watch,threshold,resets,used,observed,expires,text,created,next_attempt) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (alarm_id, watch["id"], 0, due, 0, watch["reset_observed"], 0, text, now, now),
            )
            event(
                db,
                None,
                "usage_alarm_triggered",
                {
                    "id": alarm_id,
                    "watch": watch["id"],
                    "provider": watch["provider"],
                    "name": watch["name"],
                    "kind": "reset",
                    "resets": due,
                    "observed": watch["reset_observed"],
                },
            )
            triggered += 1
        db.execute("UPDATE usage_watches SET next_reset=NULL WHERE id=?", (watch["id"],))
    return triggered


def fire_resets(config, now=None):
    now = time.time() if now is None else now
    with connect(config) as db:
        due = db.execute(
            "SELECT 1 FROM usage_watches WHERE active=1 AND kind='reset' AND next_reset<=? LIMIT 1",
            (now,),
        ).fetchone()
        if due is None:
            return 0
        db.execute("BEGIN IMMEDIATE")
        return _fire_resets(db, now)


def evaluate(config, snapshot, now=None):
    now = time.time() if now is None else now
    windows = {(row["provider"], row["name"]): row for row in snapshot["windows"]}
    with connect(config) as db:
        db.execute("BEGIN IMMEDIATE")
        triggered = _fire_resets(db, now)
        rows = db.execute("SELECT * FROM usage_watches WHERE active=1").fetchall()
        for watch in rows:
            row = windows.get((watch["provider"], watch["name"]))
            status = freshness(row, now)
            db.execute(
                "UPDATE usage_watches SET checked=?,data_status=?,used=?,observed=?,resets=? WHERE id=?",
                (
                    now,
                    status,
                    row.get("used") if row and number(row.get("used")) else None,
                    row.get("observed") if row and number(row.get("observed")) else None,
                    row.get("resets") if row and number(row.get("resets")) else None,
                    watch["id"],
                ),
            )
            if watch["kind"] == "reset":
                if status == "fresh":
                    target = row["resets"]
                    if (
                        watch["next_reset"] is not None
                        and abs(target - watch["next_reset"]) <= RESET_TOLERANCE
                    ):
                        target = max(target, watch["next_reset"])
                    db.execute(
                        "UPDATE usage_watches SET next_reset=?,reset_observed=? WHERE id=?",
                        (target, row["observed"], watch["id"]),
                    )
                continue
            if status != "fresh":
                continue
            # Suppress an older queued report after a fresh reading corrects the
            # usage downward or establishes that a different window has begun.
            db.execute(
                "UPDATE usage_alarms SET status='cleared' WHERE watch=? AND status='pending' AND (ABS(resets-?)>? OR ?<threshold)",
                (watch["id"], row["resets"], RESET_TOLERANCE, row["used"]),
            )
            if row["used"] < watch["threshold"]:
                continue
            previous = db.execute(
                "SELECT * FROM usage_alarms WHERE watch=? AND ABS(resets-?)<=? ORDER BY created DESC LIMIT 1",
                (watch["id"], row["resets"], RESET_TOLERANCE),
            ).fetchone()
            if previous and previous["status"] not in ("pending", "expired", "cleared"):
                continue
            alarm_id = previous["id"] if previous else uuid.uuid4().hex[:12]
            text = message(watch, row, alarm_id)
            until = min(row["resets"], row["observed"] + 300)
            if previous:
                db.execute(
                    "UPDATE usage_alarms SET status='pending',text=?,used=?,observed=?,expires=?,next_attempt=?,error=NULL WHERE id=?",
                    (
                        text,
                        row["used"],
                        row["observed"],
                        until,
                        now if previous["status"] != "pending" else previous["next_attempt"],
                        alarm_id,
                    ),
                )
            else:
                db.execute(
                    "INSERT INTO usage_alarms(id,watch,threshold,resets,used,observed,expires,text,created,next_attempt) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        alarm_id,
                        watch["id"],
                        watch["threshold"],
                        row["resets"],
                        row["used"],
                        row["observed"],
                        until,
                        text,
                        now,
                        now,
                    ),
                )
                triggered += 1
                event(
                    db,
                    None,
                    "usage_alarm_triggered",
                    {
                        "id": alarm_id,
                        "watch": watch["id"],
                        "provider": watch["provider"],
                        "name": watch["name"],
                        "used": row["used"],
                        "threshold": watch["threshold"],
                        "observed": row["observed"],
                        "resets": row["resets"],
                    },
                )
    return triggered


def flush(config, now=None):
    now = time.time() if now is None else now
    with connect(config) as db:
        db.execute(
            "UPDATE usage_alarms SET status='expired' WHERE status='pending' AND expires<=? AND watch IN (SELECT id FROM usage_watches WHERE kind='threshold')",
            (now,),
        )
        rows = db.execute(
            "SELECT a.id FROM usage_alarms a JOIN usage_watches w ON w.id=a.watch WHERE a.status='pending' AND a.next_attempt<=? AND w.active=1 ORDER BY a.created LIMIT 8",
            (now,),
        ).fetchall()
    for candidate in rows:
        with connect(config) as db:
            row = db.execute(
                "SELECT a.*,w.owner,w.inbox,w.inbox_token,w.active,w.kind FROM usage_alarms a JOIN usage_watches w ON w.id=a.watch WHERE a.id=?",
                (candidate["id"],),
            ).fetchone()
            if not row or not row["active"]:
                continue
            if row["kind"] == "threshold" and row["expires"] <= time.time():
                continue
            claimed = db.execute(
                "UPDATE usage_alarms SET status='dispatching' WHERE id=? AND status='pending'",
                (row["id"],),
            ).rowcount
            if not claimed:
                continue
        status, error = "accepted", None
        try:
            providers.deliver(dict(row), row["text"])
        except providers.Unavailable as exc:
            status, error = "pending", str(exc)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            status, error = "uncertain", str(exc)
        with connect(config) as db:
            db.execute(
                "UPDATE usage_alarms SET status=?,error=?,attempts=attempts+1,next_attempt=? WHERE id=?",
                (status, redact(error) if error else None, time.time() + 60, row["id"]),
            )
            if status != "pending" or row["attempts"] == 0:
                event(
                    db,
                    None,
                    "usage_alarm_delivery",
                    {"id": row["id"], "watch": row["watch"], "status": status, "error": error},
                )


def monitor(config):
    snapshot = usage.snapshot(config)
    now = time.time()
    errors = []
    with connect(config) as db:
        requested = db.execute(
            "SELECT name FROM usage_watches WHERE active=1 AND provider='claude'"
        ).fetchall()
    names = {row["name"] for row in requested}
    needs_refresh = any(
        row["provider"] == "claude"
        and row["name"] in names
        and (freshness(row, now) != "fresh" or now - row["observed"] >= 60)
        for row in snapshot["windows"]
    )
    if needs_refresh:
        with connect(config) as db:
            last = db.execute(
                "SELECT at FROM events WHERE type='usage_alarm_refresh' ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            allowed = last is None or now - last["at"] >= 60
            if allowed:
                event(db, None, "usage_alarm_refresh", {"provider": "claude"})
        if allowed:
            snapshot = usage.snapshot(config, refresh=True)
            if snapshot.get("claude_refresh_error"):
                errors.append(snapshot["claude_refresh_error"])
    triggered = evaluate(config, snapshot)
    return {"triggered": triggered, "errors": errors}


def status(config):
    with connect(config) as db:
        active = db.execute("SELECT count(*) FROM usage_watches WHERE active=1").fetchone()[0]
        states = db.execute(
            "SELECT a.status,count(*) AS n FROM usage_alarms a JOIN usage_watches w ON w.id=a.watch WHERE w.active=1 AND (w.kind='reset' OR a.resets>?) GROUP BY a.status",
            (time.time(),),
        ).fetchall()
    counts = {r["status"]: r["n"] for r in states}
    return {
        "active": active,
        **{key: counts.get(key, 0) for key in ("pending", "dispatching", "uncertain")},
    }

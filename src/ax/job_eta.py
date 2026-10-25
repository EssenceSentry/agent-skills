"""Finish-time estimates for jobs, with intervals that say how sure they are.

Progress so far gives a Gamma posterior on the job's rate. Updates count as evidence
in proportion to how even they have been, so a lumpy job gets a wide interval and a
steady one a narrow interval. Remaining time is remaining work over the rate, so its
quantiles follow from the rate's, by Wilson–Hilferty, which needs only
`statistics.NormalDist`. On top sits the chance that the rate still shifts, which
grows with how far ahead the estimate looks.

- A clear change of rate restarts the evidence at the change.
- A silence longer than the usual gap between updates counts as time without work.
- Finished jobs of the same family (kind, unit, and key without its numbers) are the
  prior, and before any progress they are the whole estimate, start-up included.

Refreshes store an `eta` event at most every five minutes; `score` and `report`
check those predictions against when the jobs really finished.
"""

import json
import math
import re
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from statistics import NormalDist, mean, median

from ax import jobs

QUANTILES = (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))
TARGET_COVERAGE = 0.8
RECORD_EVERY = 300.0
# How far the log-rate may still move over a horizon as long as the history seen so far.
DRIFT = 0.3
# Pseudo-intervals behind the unevenness estimate, each taken as one event per update.
DISPERSION_PRIOR = 2.0
# The spread of log durations assumed across similar jobs, and its weight in pseudo-jobs.
HISTORY_SPREAD, HISTORY_WEIGHT = 0.35, 2.0
HISTORY_JOBS = 20
# Past this share of similar runs' durations, the job has outlasted its history.
OUTLASTED = 0.95
_NORMAL = NormalDist()


def family(key: str) -> str:
    """A key without the parts that change between runs: score-0412-1830 becomes score."""
    words = [w for w in re.split(r"[-_.]+", key.lower()) if w and not any(c.isdigit() for c in w)]
    return "-".join(words) or key.lower()


def duration_text(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} min"
    if minutes < 36 * 60:
        return f"{int(minutes // 60)} h {int(minutes % 60):02d} min"
    return f"{minutes / 1440:.1f} days"


def finish_clock(estimate: dict) -> str:
    """The likely finish in local time, with the date when it isn't today."""
    when = jobs.parse_iso(estimate["finish"]["p50"]).astimezone()
    today = datetime.now(when.tzinfo).date()
    return when.strftime("%H:%M" if when.date() == today else "%b %d %H:%M")


def text(estimate: dict) -> str:
    """'~12 min left (8 min–20 min)': the median and the 80% interval."""
    left = estimate["remaining"]
    return (
        f"~{duration_text(left['p50'])} left "
        f"({duration_text(left['p10'])}–{duration_text(left['p90'])})"
    )


def _ratio(shape: float, p: float) -> float:
    """Quantile p of a Gamma with this shape, over its mean (Wilson–Hilferty)."""
    root = 1 - 1 / (9 * shape) + _NORMAL.inv_cdf(p) / (3 * math.sqrt(shape))
    return max(root, 0.05) ** 3


def _points(obs) -> list[tuple[datetime, float]]:
    """Observations in time order, one per instant, from the last reset of the count on."""
    latest = {}
    for ts, done in obs:
        if done is not None:
            latest[ts] = float(done)
    points = []
    for ts in sorted(latest):
        if points and latest[ts] < points[-1][1]:
            points = []
        points.append((ts, latest[ts]))
    return points


def _sums(intervals) -> tuple[float, float]:
    return sum(dd for _, dd in intervals), sum(dt for dt, _ in intervals)


def _pearson(intervals) -> float:
    units, time = _sums(intervals)
    rate = units / time
    return sum((dd - rate * dt) ** 2 / (rate * dt) for dt, dd in intervals) if rate > 0 else 0.0


def _dispersion(pearson: float, df: int, units: float, n: int) -> float:
    """Units per effective event: near zero for even progress, larger for lumpy progress."""
    return (pearson + DISPERSION_PRIOR * units / n) / (df + DISPERSION_PRIOR)


def _loglik(units: float, time: float) -> float:
    return units * math.log(units / time) if units > 0 else 0.0


def _best_split(intervals) -> int | None:
    """Where the rate clearly changed, as an index into intervals, or None.

    A two-rate fit is compared with one rate, the deviance scaled by the unevenness
    within the two parts, against a chi-square cut corrected for trying every split.
    """
    n = len(intervals)
    units, time = _sums(intervals)
    if n < 5 or units <= 0:
        return None
    pooled = _loglik(units, time)
    best, split, d1, t1 = 0.0, None, 0.0, 0.0
    for k, (dt, dd) in enumerate(intervals[:-3], start=1):
        d1, t1 = d1 + dd, t1 + dt
        if k < 2:
            continue
        gain = 2 * (_loglik(d1, t1) + _loglik(units - d1, time - t1) - pooled)
        if gain > best:
            best, split = gain, k
    if split is None:
        return None
    pearson = _pearson(intervals[:split]) + _pearson(intervals[split:])
    scale = _dispersion(pearson, n - 2, units, n)
    return split if best / scale > _NORMAL.inv_cdf(1 - 0.005 / n) ** 2 else None


def estimate_from(obs, total, now: datetime, *, prior=None) -> dict | None:
    """An estimate from (time, done) observations, or None with too little to go on.

    `prior` is (rate, shape): a Gamma prior on units per second from similar jobs,
    which lets a single observation give an estimate.
    """
    if not total:
        return None
    points = _points(obs)
    if not points:
        return None
    intervals = [((b[0] - a[0]).total_seconds(), b[1] - a[1]) for a, b in pairwise(points)]
    changed = False
    while (split := _best_split(intervals)) is not None:
        intervals, changed = intervals[split:], True
    units, time = _sums(intervals)
    if units <= 0 and not prior:
        return None
    since = max((now - points[-1][0]).total_seconds(), 0.0)
    if intervals:
        gap = median(dt for dt, _ in intervals)
        unreported, silent = min(since, gap), max(since - gap, 0.0)
    else:
        unreported, silent = since, 0.0
    shape = inverse = 0.0
    if units > 0:
        scale = _dispersion(_pearson(intervals), len(intervals) - 1, units, len(intervals))
        shape, inverse = units / scale, (time + silent) / scale
    if prior:
        rate0, shape0 = prior
        shape, inverse = shape + shape0, inverse + shape0 / rate0
    rate = shape / inverse
    left = max(total - points[-1][1], 0.0)
    horizon = left / rate
    seen = time + silent
    variance = 1 / shape + DRIFT**2 * horizon / (seen + horizon) if horizon else 1 / shape
    shape = max(1 / variance, 0.5)
    remaining = {
        name: max(left / (rate * _ratio(shape, 1 - p)) - unreported, 0.0) for name, p in QUANTILES
    }
    basis = "progress" if units > 0 else "history"
    return _result(basis, remaining, now, rate=rate, rate_changed=changed)


def _result(basis: str, remaining: dict, now: datetime, **extra) -> dict:
    remaining = {name: round(value, 1) for name, value in remaining.items()}
    return {
        "basis": basis,
        "text": text({"remaining": remaining}),
        "remaining": remaining,
        "finish": {
            name: jobs.now_iso(now + timedelta(seconds=value)) for name, value in remaining.items()
        },
        **extra,
    }


def _observations(db, key: str) -> list[tuple[datetime, float]]:
    rows = db.execute(
        "SELECT ts, data FROM events WHERE key = ? AND type = 'progress' ORDER BY seq", (key,)
    )
    return [(jobs.parse_iso(r["ts"]), json.loads(r["data"]).get("done")) for r in rows]


def _edge(db, key: str, order: str):
    row = db.execute(
        "SELECT ts, data FROM events WHERE key = ? AND type = 'progress' "
        f"ORDER BY seq {order} LIMIT 1",
        (key,),
    ).fetchone()
    return (jobs.parse_iso(row["ts"]), json.loads(row["data"]).get("done")) if row else None


def _past(db, row) -> dict | None:
    """What one finished job shows: its length, and its start-up, rate and tail if it counted."""
    created, finished = jobs.parse_iso(row["created"]), jobs.parse_iso(row["finished"])
    duration = (finished - created).total_seconds()
    if duration <= 0:
        return None
    past = {"key": row["key"], "duration": duration, "rate": None, "startup": 0.0, "tail": 0.0}
    first, last = _edge(db, row["key"], "ASC"), _edge(db, row["key"], "DESC")
    if not first or first[1] is None or last[1] is None or last[1] <= first[1]:
        return past
    if last[0] <= first[0]:
        return past  # all its progress landed at once: no rate to learn from
    rate = (last[1] - first[1]) / (last[0] - first[0]).total_seconds()
    left = max((row["total"] or last[1]) - last[1], 0.0)
    past["rate"] = rate
    past["startup"] = max((first[0] - created).total_seconds() - first[1] / rate, 0.0)
    past["tail"] = max((finished - last[0]).total_seconds() - left / rate, 0.0)
    return past


def similar(db, job, limit: int = HISTORY_JOBS) -> list[dict]:
    """The latest successful runs of the job's family."""
    rows = db.execute(
        "SELECT key, created, finished, total FROM jobs WHERE status = 'done' AND kind = ? "
        "AND unit IS ? AND key != ? AND finished IS NOT NULL ORDER BY finished DESC",
        (job.kind, job.unit, job.key),
    )
    name, found = family(job.key), []
    for row in rows:
        if family(row["key"]) == name and (past := _past(db, row)):
            found.append(past)
            if len(found) >= limit:
                break
    return found


def _log_spread(values: list[float]) -> tuple[float, float]:
    """Mean and predictive standard deviation of the logs, shrunk toward HISTORY_SPREAD."""
    logs = [math.log(v) for v in values]
    k, centre = len(logs), mean(logs)
    sum_sq = sum((x - centre) ** 2 for x in logs)
    variance = (sum_sq + HISTORY_WEIGHT * HISTORY_SPREAD**2) / (k - 1 + HISTORY_WEIGHT)
    return centre, math.sqrt(variance * (1 + 1 / k))


def _rate_prior(history: list[dict]) -> tuple[float, float] | None:
    rates = [p["rate"] for p in history if p["rate"]]
    if not rates:
        return None
    centre, spread = _log_spread(rates)
    return math.exp(centre), 1 / spread**2


def _from_history(job, history: list[dict], now: datetime) -> dict | None:
    """Before any progress: how long similar jobs took, given how long this one has run."""
    if not history:
        return None
    timed = [p for p in history if p["rate"]]
    if job.total and timed:
        spans = [p["startup"] + job.total / p["rate"] + p["tail"] for p in timed]
    else:
        spans = [p["duration"] for p in history]
    centre, spread = _log_spread([max(s, 1.0) for s in spans])
    dist = NormalDist(centre, spread)
    elapsed = max((now - jobs.parse_iso(job.created)).total_seconds(), 0.0)
    floor = dist.cdf(math.log(elapsed)) if elapsed > 0 else 0.0
    if floor > OUTLASTED:
        return None  # it has run longer than its family ever did; history can't say more
    remaining = {
        name: max(math.exp(dist.inv_cdf(floor + p * (1 - floor))) - elapsed, 0.0)
        for name, p in QUANTILES
    }
    return _result("history", remaining, now)


def _estimate(db, job, now: datetime) -> dict | None:
    if job.terminal:
        return None
    history = similar(db, job)
    obs = _observations(db, job.key)
    found = None
    if obs:
        found = estimate_from(
            obs, job.total, now, prior=_rate_prior(history) if job.total else None
        )
    if found is None:
        found = _from_history(job, history, now)
    if found is not None:
        found["similar_jobs"] = len(history)
    return found


def estimate(config, job, now: datetime | None = None) -> dict | None:
    """The current estimate for a running job, or None when there's nothing to go on."""
    with jobs.connect(config) as db:
        return _estimate(db, job, now or datetime.now(UTC))


def record(db, job, now: datetime) -> dict | None:
    """Store an estimate as an `eta` event when the last one is RECORD_EVERY old."""
    if job.terminal:
        return None
    last = db.execute(
        "SELECT ts FROM events WHERE key = ? AND type = 'eta' ORDER BY seq DESC LIMIT 1",
        (job.key,),
    ).fetchone()
    if last and (now - jobs.parse_iso(last["ts"])).total_seconds() < RECORD_EVERY:
        return None
    found = _estimate(db, job, now)
    if found:
        jobs._event(db, job.key, jobs.now_iso(now), "eta", found)
    return found


def score(config, key: str, finished: datetime | None = None) -> dict:
    """How a job's stored predictions did against when it really finished."""
    with jobs.connect(config) as db:
        job = jobs._load(db, key)
        rows = db.execute(
            "SELECT ts, data FROM events WHERE key = ? AND type = 'eta' ORDER BY seq", (key,)
        ).fetchall()
    if finished is None and job and job.finished:
        finished = jobs.parse_iso(job.finished)
    hits, errors, relative = 0, [], []
    for row in rows if finished else []:
        finish = json.loads(row["data"]).get("finish") or {}
        try:
            low, mid, high = (jobs.parse_iso(finish[name]) for name, _ in QUANTILES)
        except (KeyError, TypeError, ValueError):
            continue
        hits += low <= finished <= high
        error = abs((finished - mid).total_seconds())
        errors.append(error)
        actual = (finished - jobs.parse_iso(row["ts"])).total_seconds()
        if actual > 0:
            relative.append(error / actual)
    count = len(errors)
    return {
        "key": key,
        "predictions": count,
        "hits": hits,
        "coverage": hits / count if count else None,
        "median_error_s": median(errors) if errors else None,
        "median_relative_error": median(relative) if relative else None,
    }


def report(config, scores: list[dict] | None = None) -> dict:
    """Coverage of the 80% intervals across finished jobs; near 0.8 means calibrated."""
    if scores is None:
        with jobs.connect(config) as db:
            keys = [
                r["key"]
                for r in db.execute(
                    "SELECT DISTINCT e.key FROM events e JOIN jobs j ON j.key = e.key "
                    "WHERE e.type = 'eta' AND j.status = 'done'"
                )
            ]
        scores = [score(config, key) for key in keys]
    scored = [s for s in scores if s.get("predictions")]
    predictions = sum(s["predictions"] for s in scored)
    hits = sum(s.get("hits", s["coverage"] * s["predictions"]) for s in scored)
    coverage = hits / predictions if predictions else None
    if predictions < 20:
        verdict = "too few predictions to judge"
    elif coverage < TARGET_COVERAGE - 0.1:
        verdict = "intervals too narrow"
    elif coverage > TARGET_COVERAGE + 0.1:
        verdict = "intervals too wide"
    else:
        verdict = "calibrated"
    errors = [s["median_error_s"] for s in scored if s.get("median_error_s") is not None]
    return {
        "jobs": len(scored),
        "predictions": predictions,
        "coverage": coverage,
        "target": TARGET_COVERAGE,
        "median_error_s": median(errors) if errors else None,
        "verdict": verdict,
        "scores": scored,
    }

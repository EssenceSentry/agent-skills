"""The rule lifecycle: each active rule's evidence, confidence, maturity and review flag.

Evidence comes from the archive, as events. For a rule: the sessions that stated it
before it was adopted, its guard's blocks, its adoption and the user's last keep.
Against it: sessions that corrected the same thing after adoption (recurrences, at
the weight the learner gives them) and messages that told an agent to set it aside
(overrides). Confidence sums the events, each halving every 90 days, with the against
side counted four times.

Maturity is new for a month, then established, and proven once a rule is three months
old with fresh evidence and nothing against it for 90 days; doubtful whenever the
confidence is not positive. A review flag asks the user to act, never acting itself:
two recurrences since the last review ask for a guard or a rewrite, an override asks
for a narrower scope, and 90 days without evidence ask whether to retire the rule.
`ax sync` keeps these fields current in each active rule's note.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from ax import learn, profile, scorecard

HALF_LIFE = 90
AGAINST = 4
ESCALATE = 2
NEW_DAYS = 30
PROVEN_DAYS = 90
PROVEN_CONFIDENCE = 2.0
SYNC_LABELS = 40  # most candidates one sync labels; a backlog clears over later syncs
# Signals of a correction; praise or a Codex memory restating a rule after adoption is
# the rule working, so it counts as support.
CORRECTIVE = ("frustration", "explicit", "rejection", "interrupted", "phrase")
FOR_KINDS = ("support", "block", "kept")
AGAINST_KINDS = ("recurrence", "override")


@dataclass(frozen=True)
class Event:
    day: str  # ISO date
    kind: str  # support, recurrence, override, block or kept
    weight: int = 1
    note: str | None = None
    project: str | None = None
    candidate: str | None = None


def events(config, candidates, labels, *, rules: list | None = None) -> dict:
    """Every active rule's evidence events, from labelled candidates and the guard log."""
    rules = {
        r.id: r for r in (profile.load_rules(config) if rules is None else rules)
        if r.status == "active"
    }  # fmt: skip
    by_session: dict = defaultdict(dict)  # rule id -> session -> strongest event
    for group in learn.groups(candidates, labels):
        for rule in rules.values():
            if not learn._matches(group, rule):
                continue
            for c, lab in group.members:
                day = learn.local_day(c["ts"])
                after = rule.added and day > rule.added
                kind = "recurrence" if after and set(c["signals"]) & set(CORRECTIVE) else "support"
                event = Event(day, kind, learn.weight(c, lab), c["note"], c["project"], c["id"])
                kept = by_session[rule.id].get(c["session"])
                if kept is None or event.weight > kept.weight:
                    by_session[rule.id][c["session"]] = event
    found = {rid: list(sessions.values()) for rid, sessions in by_session.items()}
    for c in candidates:
        against = (labels.get(c["id"]) or {}).get("against")
        day = learn.local_day(c["ts"])
        if against in rules and day > rules[against].added:  # set aside once it was adopted
            event = Event(day, "override", 1, c["note"], c["project"], c["id"])
            found.setdefault(against, []).append(event)
    for entry in scorecard._guard_log(config):
        if entry.get("rule") in rules:
            found.setdefault(entry["rule"], []).append(
                Event(learn.local_day(entry["when"].isoformat()), "block")
            )
    return found


def _age(day: str, today: date) -> int | None:
    try:
        return max(0, (today - date.fromisoformat(day)).days)
    except ValueError:
        return None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _review(rule, events: list, last: str, today: date) -> str:
    since = rule.reviewed or rule.added
    again = {e.note or e.day for e in events if e.kind == "recurrence" and e.day > since}
    overrides = [e for e in events if e.kind == "override" and e.day > since]
    if len(again) >= ESCALATE:
        where = f"corrected again in {len(again)} sessions since {since}"
        if rule.level == "block":
            return f"escalate: {where} despite its guard; widen the guard or rewrite the rule"
        return f"escalate: {where}; make it a guard (`ax learn guard {rule.id}`) or rewrite it"
    if overrides:
        projects = sorted({e.project for e in overrides if e.project}) or ["unknown projects"]
        return (
            f"narrow: overridden {_plural(len(overrides), 'time')} ({', '.join(projects)}); "
            "narrow its scope or rewrite it"
        )
    age = _age(last, today) if last else None
    if age is not None and age >= HALF_LIFE:
        return (
            f"retire: no evidence since {last}; `ax learn retire {rule.id}`, "
            f"or `ax learn keep {rule.id}` to keep it"
        )
    return ""


def assess(rule, events: list, today: date) -> dict:
    """The lifecycle fields for one rule, from its events."""
    base = [Event(rule.added, "support")] if rule.added else []
    if rule.reviewed:
        base.append(Event(rule.reviewed, "kept"))
    dated = [(e, age) for e in [*base, *events] if (age := _age(e.day, today)) is not None]

    def decayed(kinds) -> float:
        return sum(e.weight * 0.5 ** (age / HALF_LIFE) for e, age in dated if e.kind in kinds)

    confidence = round(decayed(FOR_KINDS) - AGAINST * decayed(AGAINST_KINDS), 1)
    last = max((e.day for e, _ in dated), default="")
    age = _age(rule.added, today) if rule.added else 0
    recent_against = any(e.kind in AGAINST_KINDS and a <= PROVEN_DAYS for e, a in dated)
    if confidence <= 0:
        maturity = "doubtful"
    elif (age or 0) < NEW_DAYS:
        maturity = "new"
    elif age >= PROVEN_DAYS and confidence >= PROVEN_CONFIDENCE and not recent_against:
        maturity = "proven"
    else:
        maturity = "established"
    count = lambda kind: sum(e.kind == kind for e in events)  # noqa: E731
    return {
        "maturity": maturity,
        "confidence": confidence,
        "support": count("support"),
        "recurrences": count("recurrence"),
        "blocks": count("block"),
        "overrides": count("override"),
        "last_evidence": last,
        "review": _review(rule, events, last, today),
    }


def refresh(
    config, candidates, labels, *, today: date | None = None, problems: list | None = None
) -> list:
    """Write the lifecycle into each active rule's note whose fields changed. With a
    `problems` list, notes that can't be read are recorded there and skipped."""
    today = today or date.today()
    rules = profile.load_rules(config, problems=problems)
    found = events(config, candidates, labels, rules=rules)
    changed = []
    for rule in rules:
        if rule.status != "active":
            continue
        fields = assess(rule, found.get(rule.id, []), today)
        if all(getattr(rule, k) == v for k, v in fields.items()):
            continue
        fresh = profile._read(rule.path)  # keep a keep or an edit made since the load
        if fresh.status != "active" or fresh.reviewed != rule.reviewed:
            continue  # the next sync assesses it as it is now
        for k, v in fields.items():
            setattr(fresh, k, v)
        profile._write(fresh, fresh.path)
        changed.append(fresh)
    return changed


def after_sync(config) -> tuple[list, list]:
    """Rescan the archive, label up to SYNC_LABELS new candidates (unless turned off) and
    refresh the lifecycle.
    Returns the rules updated and the notes that couldn't be read, as (path, error)."""
    candidates = learn.scan(config)
    learn.save_candidates(config, candidates)
    labels = learn.load_labels(config)
    if config.learn_label_on_sync:
        todo = learn.unlabelled(candidates, labels)[:SYNC_LABELS]
        labels = learn.label(config, todo) if todo else labels
    problems: list = []
    return refresh(config, candidates, labels, problems=problems), problems


def _active(config, rule_id: str):
    rule = next((r for r in profile.load_rules(config) if r.id == rule_id), None)
    if rule is None or rule.status != "active":
        raise ValueError(f"no active rule {rule_id!r}; see `ax learn review`")
    return rule


def keep(config, rule_id: str, *, today: date | None = None):
    """Keep a rule the lifecycle flagged: it counts as fresh evidence and clears the flag."""
    rule = _active(config, rule_id)
    rule.reviewed, rule.review = (today or date.today()).isoformat(), ""
    rule.extra.pop("workshop", None)  # keeping it answers the workshop's suggestion too
    profile._write(rule, rule.path)
    return rule


def retire(config, rule_id: str):
    rule = _active(config, rule_id)
    rule.status, rule.review = "retired", ""
    profile._write(rule, rule.path)
    return rule

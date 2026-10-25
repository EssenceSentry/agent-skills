"""Before review: merge near-duplicate proposals and flag those that contradict a rule.

One model call sees every proposed and active rule and names pairs that are the same
rule (or one a special case of the other) and pairs where following one breaks the
other. A duplicate proposal is folded into the rule it duplicates: that rule keeps its
wording, gains the evidence, and lists the folded id in its `covers`, so the next
`ax learn propose` adds that topic's evidence to it instead of proposing it again. An
active rule is never dropped or reworded. A contradiction is noted in each proposal
involved, for the user to settle; nothing is decided for them.
"""

import json
from dataclasses import dataclass, field

from ax import learn, profile

_PROMPT = """These are the working rules a user keeps for their coding agents. Proposed
rules are waiting for the user's review; active ones are in use.

{rules}

Return only a JSON object with two arrays:
- "duplicates": pairs that state the same rule, or where one is a special case of the
  other, as {{"keep": id, "drop": id, "why": "..."}}. Keep the more general one.
- "contradictions": pairs where following one would break the other, as
  {{"a": id, "b": id, "why": "..."}}.
Leave a pair out when unsure. Use [] when there is none.
"""


CONTRADICTS = "May contradict"


@dataclass
class Report:
    merged: list = field(default_factory=list)  # (dropped id, kept id)
    flagged: list = field(default_factory=list)  # (proposal id, other id, why)


def _object(answer: str) -> dict:
    start, end = answer.find("{"), answer.rfind("}")
    try:
        found = json.loads(answer[start : end + 1]) if 0 <= start < end else {}
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _pairs(found: dict, name: str, first: str, second: str) -> list[tuple]:
    """The model's pairs whose two ids are strings; anything else is ignored."""
    pairs = found.get(name)
    return [
        (p[first], p[second], str(p.get("why") or "").strip())
        for p in pairs
        if isinstance(p, dict) and isinstance(p.get(first), str) and isinstance(p.get(second), str)
    ] if isinstance(pairs, list) else []  # fmt: skip


def _fold(config, drop, keep) -> None:
    keep.evidence = list(dict.fromkeys([*keep.evidence, *drop.evidence]))[:40]
    keep.covers = list(dict.fromkeys([*keep.covers, drop.id, *drop.covers]))
    if keep.status == "proposed":
        evidence = drop.why.split("Evidence:", 1)[-1].strip()
        keep.why += f'\n\nMerged in `{drop.id}` ("{drop.rule}"):\n{evidence}'
    profile._write(keep, keep.path)
    drop.path.unlink()
    proposals = learn._ledger(config, "proposals.json")
    if drop.id in proposals:
        gone = proposals.pop(drop.id)
        if keep.id in proposals:
            proposals[keep.id]["support"] += gone.get("support", 0)
        learn._save_ledger(config, "proposals.json", proposals)


def _flag(rule, other, why: str) -> None:
    link = f"[[Profile/rules/{other.id}|{other.id}]]"
    if link not in rule.why:
        rule.why += f'\n\n{CONTRADICTS} {link} ("{other.rule}"): {why or "check both"}.'
        profile._write(rule, rule.path)


def tidy(config, *, model=None) -> Report:
    report = Report()
    rules = {r.id: r for r in profile.load_rules(config) if r.status in ("proposed", "active")}
    if len(rules) < 2 or not any(r.status == "proposed" for r in rules.values()):
        return report
    listing = "\n".join(f"- {r.id} ({r.status}, {r.scope}): {r.rule}" for r in rules.values())
    found = _object((model or learn.claude_model())(_PROMPT.format(rules=listing)))
    # The model took a while: act on the notes as they are now, and skip a pair whose
    # status changed, since the model judged it under the old one.
    asked = {rid: r.status for rid, r in rules.items()}
    rules = {rid: r for rid, r in _fresh(rules).items() if r.status == asked[rid]}
    for keep, drop, _ in _pairs(found, "duplicates", "keep", "drop"):
        if keep not in rules or drop not in rules or keep == drop:
            continue
        if rules[drop].status == "active":
            keep, drop = drop, keep
        if rules[drop].status != "proposed":
            continue
        _fold(config, rules.pop(drop), rules[keep])
        report.merged.append((drop, keep))
    for a, b, why in _pairs(found, "contradictions", "a", "b"):
        if a not in rules or b not in rules or a == b:
            continue
        for rule, other in ((rules[a], rules[b]), (rules[b], rules[a])):
            if rule.status == "proposed":
                _flag(rule, other, why)
                report.flagged.append((rule.id, other.id, why))
    return report


def _fresh(rules: dict) -> dict:
    """Re-read each note; leave out those removed or moved out of review meanwhile."""
    found = {}
    for rid, rule in rules.items():
        if rule.path and rule.path.exists():
            fresh = profile._read(rule.path)
            if fresh.status in ("proposed", "active"):
                found[rid] = fresh
    return found

"""Fix proposals: an error that keeps coming back across sessions becomes a rule to try.

The scorecard finds error signatures that recur in three or more sessions, with a few
commands that hit them. A model call per twenty new errors asks, for each, whether one
standing instruction (an environment fact, a better command) would let agents avoid
it, and words it. Each error is asked about once, even when the answer is no. A fix
becomes a proposal like any other: repo-scoped when the error stays in one project.
"""

import json
import re
from datetime import date

from ax import learn, profile
from ax.redact import redact

BATCH = 20

_PROMPT = """These errors keep coming back in a user's sessions with coding agents (Claude
Code and Codex), each in several sessions. For each, decide whether one standing
instruction to the agents would avoid it, such as an environment fact or a better
command. Harmless warnings, errors that are the point of the command, and one-off
bugs need none.

Return only a JSON array with one object per item:
- "id": the item's id
- "fix": the instruction as one imperative sentence, or "" when none would help or an
  existing rule below already gives it
- "topic": a kebab-case slug of two to four words naming the fix

Existing rules:
{rules}

Items:
{items}
"""


def _why(error: dict) -> str:
    projects = ", ".join(error["projects"]) or "unknown projects"
    lines = [
        f"Proposed by `ax learn fixes` on {date.today().isoformat()} from an error that "
        f"recurred in {error['sessions']} sessions ({projects}), last on {error['last_seen']}:",
        "",
        f"`{error['signature']}`",
    ]
    if error["examples"]:
        lines += ["", "Commands that hit it:"]
        lines += [f"- `{redact(c)}`" for c in error["examples"]]
    return "\n".join(lines)


def propose_fixes(config, errors: list, *, model=None) -> list:
    """Ask about each recurring error not asked about yet; returns the proposals written."""
    asked = learn._ledger(config, "fixes.json")
    todo = [e for e in errors if e["signature"] not in asked]
    if not todo:
        return []
    model = model or learn.claude_model()
    taken = {r.id for r in profile.load_rules(config)}
    proposals = learn._ledger(config, "proposals.json")
    written = []
    for start in range(0, len(todo), BATCH):
        chunk = {f"e{i}": e for i, e in enumerate(todo[start : start + BATCH])}
        items = "\n".join(
            json.dumps(
                {"id": key, "error": e["signature"], "sessions": e["sessions"],
                 "projects": e["projects"], "commands": [redact(c) for c in e["examples"]]},
                ensure_ascii=False,
            )
            for key, e in chunk.items()
        )  # fmt: skip
        prompt = _PROMPT.format(rules=learn._existing_rules(config), items=items)
        answers = {a["id"]: a for a in learn._parse(model(prompt))}
        for key, error in chunk.items():
            if key not in answers:
                continue  # asked again next time
            fix = str(answers[key].get("fix") or "").strip()
            topic = re.sub(r"[^a-z0-9]+", "-", str(answers[key].get("topic") or "").lower())
            topic = topic.strip("-") or "recurring-error-fix"
            asked[error["signature"]] = {"rule": None, "date": date.today().isoformat()}
            if not fix or topic in taken:
                continue
            rid = learn._rule_id(topic, taken)
            projects = error["projects"]
            rule = profile.add(
                config, rid, rule=fix, status="proposed",
                scope=learn.repo_scope(projects[0]) if len(projects) == 1 else "global",
                why=_why(error), retire_when=learn._RETIRE,
                evidence=[f"recurring error: {error['signature']}"],
            )  # fmt: skip
            taken.add(rid)
            asked[error["signature"]]["rule"] = rid
            proposals[rid] = {"support": error["sessions"], "sessions": error["sessions"],
                              "projects": len(projects), "kind": "environment-fix",
                              "date": date.today().isoformat()}  # fmt: skip
            written.append(rule)
    learn._save_ledger(config, "fixes.json", asked)
    learn._save_ledger(config, "proposals.json", proposals)
    return written

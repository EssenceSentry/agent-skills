"""Fix proposals: an error that keeps coming back across sessions becomes a rule to try.

The scorecard finds error signatures that recur in three or more sessions, with a few
commands that hit them. A model call per twenty new errors asks, for each, whether one
standing instruction (an environment fact, a better command) would let agents avoid
it, and words it. A fix must name the command, tool or path to use, in backticks;
anything else is generic advice and is dropped. Each error is asked about once, even
when the answer is no. A fix becomes a proposal like any other: repo-scoped when the
error stays in one project.
"""

import json
import re
from datetime import date

from ax import learn, profile
from ax.redact import redact

BATCH = 20

_PROMPT = """These errors keep coming back in a user's sessions with coding agents (Claude
Code and Codex), each in several sessions. In an error, N stands for a number, PATH for
a path and '…' for quoted text; the commands are ones that hit it.

For each, decide whether one standing instruction would stop agents from hitting it
again. Give one only when the error comes from something specific: a tool missing on
this machine, a project's required wrapper or entry point, a tool's own limits or
flags, a path or setting agents keep getting wrong. The instruction must name the
command, flag, tool or path to use, in backticks. Most errors need none, and these
never do:
- generic advice: validate inputs, check paths exist, handle errors, quote
  variables, use .get(), test first
- warnings that don't stop the work, such as an upgrade notice
- checks doing their job: a linter, formatter, type checker, test or validator that
  failed on the code it was asked to check
- text that only looks like an error, such as documentation an agent read
- errors whose cause the commands shown don't make clear

Return only a JSON array with one object per item:
- "id": the item's id
- "fix": the instruction as one imperative sentence, or "" for none (also when an
  existing rule below already gives it)
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


def propose_fixes(
    config, errors: list, *, model=None, max_pending: int = learn.MAX_PENDING
) -> list:
    """Ask about each recurring error not asked about yet; returns the proposals written.

    Fixes share the review queue with other proposals: when it is full nothing is asked,
    and a fix that finds no room is not recorded, so it is asked about again later.
    """
    asked = learn._ledger(config, "fixes.json")
    todo = [e for e in errors if e["signature"] not in asked]
    rules = profile.load_rules(config, problems=[])
    room = max_pending - sum(r.status == "proposed" for r in rules)
    if not todo or room <= 0:
        return []
    model = model or learn.claude_model()
    taken = {r.id for r in rules}
    proposals = learn._ledger(config, "proposals.json")
    written = []
    for start in range(0, len(todo), BATCH):
        if room <= 0:
            break
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
            today = date.today().isoformat()
            if "`" not in fix or topic in taken:
                # A fix that names no command, tool or path is generic advice.
                asked[error["signature"]] = {"rule": None, "date": today}
                continue
            if room <= 0:
                continue  # not recorded: asked again once there is room
            rid = learn._rule_id(topic, taken)
            projects = error["projects"]
            try:
                rule = profile.add(
                    config, rid, rule=fix, status="proposed",
                    scope=learn.repo_scope(projects[0]) if len(projects) == 1 else "global",
                    why=_why(error), retire_when=learn._RETIRE,
                    evidence=[f"recurring error: {error['signature']}"],
                )  # fmt: skip
            except ValueError:
                continue  # a note with that id appeared meanwhile; asked again next time
            room -= 1
            taken.add(rid)
            asked[error["signature"]] = {"rule": rid, "date": today}
            proposals[rid] = {"support": error["sessions"], "sessions": error["sessions"],
                              "projects": len(projects), "kind": "environment-fix",
                              "date": today}  # fmt: skip
            written.append(rule)
        # Saved after each call, so a later failure keeps what was already written.
        learn._save_ledger(config, "fixes.json", asked)
        learn._save_ledger(config, "proposals.json", proposals)
    return written

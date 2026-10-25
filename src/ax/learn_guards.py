"""Guard proposals: a checkable "never" rule comes with a pattern, tested on the archive.

The model reads the rule and the shell commands run before its evidence, and answers
with a regular expression for commands that break it. The pattern is matched the way
the guard matches it (`where: command`: quoted text and heredoc bodies don't count), on
whole commands read from the transcripts (the archive keeps only first lines). It must
catch every evidence command the model called a violation and stay quiet on the
commands of the last 30 days' other sessions. A noisy pattern gets one
retry that shows its false hits; a pattern that fails either test is dropped. A
passing pattern becomes the proposal's block-level guard, accepted with the rule.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ax import guard, learn, learn_tidy, profile
from ax.redact import redact
from ax.sources.common import first_line, open_text

RECENT_DAYS = 30
ATTEMPTS = 2
_SHOWN = 5
_COMMAND_SHOWN = 400  # characters of each evidence command the model sees
_NEVER = re.compile(r"(?i)\b(?:never|don'?t|do not|avoid|stop|must not)\b")

_PROMPT = """A user keeps this rule for their coding agents:

"{rule}"

Before the user stated it, the agent had run these shell commands:
{commands}

Could a check on a shell command catch a break of this rule before it runs? If so,
write a Python regular expression that matches commands breaking the rule and no
others. It is searched in the command with quoted strings and heredoc bodies removed.{retry}

Return only a JSON object:
{{"checkable": true or false, "pattern": "...",
  "message": "one sentence telling the agent what to do instead",
  "violations": [the numbers of the commands above that break the rule]}}
"""

_RETRY = """

Your previous pattern {pattern} also matched these commands, which don't break the rule:
{hits}
Write a narrower pattern."""


@dataclass
class Result:
    rule: str
    status: str  # guarded, noisy, missed, uncheckable, invalid or untested
    pattern: str = ""
    message: str = ""
    caught: int = 0
    evidence: int = 0
    quiet_on: int = 0
    hits: list = field(default_factory=list)


def _transcript_commands(path: Path) -> list[str]:
    """Shell commands as they ran, whole, from a Claude or a Codex transcript.

    The archive keeps only each command's first line, cut at 100 characters, and the
    guard matches the whole command, so patterns are tested on these.
    """
    found = []
    try:
        with open_text(path) as fh:
            for line in fh:
                if '"Bash"' not in line and "exec_command" not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                found += _commands_in(record) if isinstance(record, dict) else []
    except OSError:
        return []
    return found


def _commands_in(record: dict) -> list[str]:
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), list) else []
    found = [
        b["input"]["command"]
        for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash"
        and isinstance(b.get("input"), dict) and isinstance(b["input"].get("command"), str)
    ]  # fmt: skip
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    if payload.get("type") == "function_call" and payload.get("name") == "exec_command":
        try:
            args = json.loads(payload.get("arguments") or "{}")
        except ValueError:
            args = {}
        if isinstance(args, dict) and isinstance(args.get("cmd"), str):
            found.append(args["cmd"])
    return found


def _sessions(config, sql: str, args) -> list:
    from ax.store import Store

    if not config.db_path.exists():
        return []
    with Store(config.db_path) as store:
        return store.db.execute(sql, args).fetchall()


def _by_session(rows) -> dict:
    """Each session's whole commands from its transcript, else its archived first lines."""
    archived, paths = {}, {}
    for session_id, source, text in rows:
        paths[session_id] = source
        command = learn._command(text) if text else None
        if command:
            archived.setdefault(session_id, []).append(command)
    found = {}
    for session_id, source in paths.items():
        whole = _transcript_commands(Path(source)) if source and Path(source).is_file() else []
        found[session_id] = whole or archived.get(session_id, [])
    return found


_COMMANDS = (
    "SELECT s.session_id, s.source_path, m.text FROM sessions s LEFT JOIN messages m "
    "ON m.session_key = s.key AND m.role = 'tool' AND m.text LIKE 'ran %' "
)


def recent_commands(config, *, exclude: set, now: datetime, days: int = RECENT_DAYS) -> list:
    """Commands from sessions that ended in the last `days`, minus the `exclude` sessions."""
    since = (now - timedelta(days=days)).isoformat()
    rows = _sessions(config, _COMMANDS + "WHERE s.ended >= ?", (since,))
    return [
        command
        for session_id, commands in _by_session(rows).items()
        if session_id not in exclude
        for command in commands
    ]


def _expand(cut: list, whole: list) -> list:
    """Archived first lines replaced by the whole commands they were cut from."""
    full = {}
    for command in whole:
        full.setdefault(first_line(command), command)
    return [full.get(c, c) for c in cut]


def _with_whole_commands(config, evidence: list) -> list:
    sessions = sorted({c["session"] for c in evidence})
    marks = ", ".join("?" for _ in sessions)
    rows = _sessions(config, _COMMANDS + f"WHERE s.session_id IN ({marks})", sessions)
    whole = _by_session(rows)
    return [
        {**c, "commands": _expand(c.get("commands") or [], whole.get(c["session"], []))}
        for c in evidence
    ]


def _hit(pattern: re.Pattern, command: str) -> bool:
    return bool(pattern.search(guard.code_only(command)))


def check(rule, evidence: list, recent: list, *, model) -> Result:
    """Ask for a pattern and test it on the evidence commands and the recent ones."""
    commands = list(dict.fromkeys(cmd for c in evidence for cmd in c.get("commands") or []))
    listing = "\n".join(
        f"{i}. {redact(c if len(c) <= _COMMAND_SHOWN else c[:_COMMAND_SHOWN] + '…')}"
        for i, c in enumerate(commands, 1)
    )
    retry, result = "", Result(rule.id, "uncheckable")
    for _ in range(ATTEMPTS):
        found = learn_tidy._object(
            model(_PROMPT.format(rule=rule.rule, commands=listing, retry=retry))
        )
        if found.get("checkable") is not True:
            return Result(rule.id, "uncheckable")
        try:
            pattern = re.compile(str(found.get("pattern") or ""), re.MULTILINE)
        except re.error:
            return Result(rule.id, "invalid")
        if not pattern.pattern:
            return Result(rule.id, "invalid")
        named = found.get("violations") if isinstance(found.get("violations"), list) else []
        numbers = {n for n in named if isinstance(n, int) and not isinstance(n, bool)}
        violations = [
            c for i, c in enumerate(commands, 1) if i in numbers or c in named or redact(c) in named
        ]
        result = Result(
            rule.id, "missed", pattern.pattern, str(found.get("message") or "").strip(),
            caught=sum(_hit(pattern, v) for v in violations), evidence=len(violations),
        )  # fmt: skip
        if not violations or result.caught < len(violations):
            return result
        if not recent:
            result.status = "untested"
            return result
        hits = [c for c in recent if _hit(pattern, c)]
        if not hits:
            result.status, result.quiet_on = "guarded", len(recent)
            return result
        result.status, result.hits = "noisy", list(dict.fromkeys(hits))[:_SHOWN]
        shown = "\n".join(f"- {redact(h)}" for h in result.hits)
        retry = _RETRY.format(pattern=pattern.pattern, hits=shown)
    return result


def _ledger(config) -> dict:
    return learn._ledger(config, "guards.json")


def _key(rule) -> str:
    return hashlib.sha1(rule.rule.encode()).hexdigest()[:12]


def forget(config, rule_id: str) -> None:
    """Drop a rule's past answer, so the next run asks again."""
    ledger = _ledger(config)
    ledger.pop(rule_id, None)
    learn._save_ledger(config, "guards.json", ledger)


def candidates_for(config, candidates: list) -> list:
    """Proposed "never" rules at advice level whose evidence ran commands, not yet asked."""
    asked = _ledger(config)
    by_id = {c["id"]: c for c in candidates}
    found = []
    for rule in profile.load_rules(config):
        if rule.status != "proposed" or rule.level != "advice" or rule.guard:
            continue
        if not _NEVER.search(rule.rule) or asked.get(rule.id, {}).get("key") == _key(rule):
            continue
        evidence = [by_id[i] for i in rule.evidence if i in by_id]
        if any(c.get("commands") for c in evidence):
            found.append((rule, evidence))
    return found


def _apply(rule, result: Result, **fields) -> bool:
    """Write the guard into the note as it is now; skip it if the rule changed meanwhile."""
    fresh = profile._read(rule.path) if rule.path.exists() else None
    if fresh is None or (fresh.status, fresh.rule) != (rule.status, rule.rule):
        result.status = "changed"
        return False
    rule = fresh
    for name, value in fields.items():
        setattr(rule, name, value)
    rule.guard = {"tool": "shell", "pattern": result.pattern, "message": result.message,
                  "where": "command"}  # fmt: skip
    if rule.repo:
        rule.guard["repo"] = rule.repo
    rule.level = "block"
    rule.why += (
        f"\n\nGuard: `{result.pattern}` caught {result.caught} of {result.evidence} evidence "
        f"commands and none of {result.quiet_on} commands from the last {RECENT_DAYS} days. "
        "Delete the guard and set the level to advice to keep the rule as advice only."
    )
    profile._write(rule, rule.path)
    return True


def propose_guards(config, candidates: list, *, model=None, now: datetime | None = None) -> list:
    """Try a guard for each eligible proposal; returns what happened to each."""
    now, model = now or datetime.now(UTC), model or learn.claude_model()
    ledger, results = _ledger(config), []
    for rule, evidence in candidates_for(config, candidates):
        evidence = _with_whole_commands(config, evidence)
        recent = recent_commands(config, exclude={c["session"] for c in evidence}, now=now)
        result = check(rule, evidence, recent, model=model)
        if result.status == "guarded":
            _apply(rule, result)
        ledger[rule.id] = {"key": _key(rule), "status": result.status, "pattern": result.pattern,
                           "hits": result.hits, "date": now.date().isoformat()}  # fmt: skip
        learn._save_ledger(config, "guards.json", ledger)
        results.append(result)
    return results


def guard_rule(config, rule_id: str, candidates, labels, *, model=None, now=None) -> Result:
    """Try a guard for one active rule, from its evidence and the sessions that restate it.

    The user asked for it by name, so a passing pattern is enforced at once and clears the
    rule's review flag; `ax profile compile --apply` then loads it.
    """
    from ax import learn_life

    rule = learn_life._active(config, rule_id)
    by_id = {c["id"]: c for c in candidates}
    restated = learn_life.events(config, candidates, labels).get(rule.id, [])
    ids = dict.fromkeys([*rule.evidence, *(e.candidate for e in restated if e.candidate)])
    evidence = _with_whole_commands(config, [by_id[i] for i in ids if i in by_id])
    if not any(c.get("commands") for c in evidence):
        return Result(rule.id, "no-commands")
    recent = recent_commands(
        config, exclude={c["session"] for c in evidence}, now=now or datetime.now(UTC)
    )
    result = check(rule, evidence, recent, model=model or learn.claude_model())
    if result.status == "guarded":
        # Guarding the rule is the review: the recurrences behind the flag predate it.
        today = learn.local_day((now or datetime.now(UTC)).isoformat())
        _apply(rule, result, review="", reviewed=today)
    return result


_WHY_NOT = {
    "missed": "the pattern missed an evidence command",
    "uncheckable": "the model found no command to check",
    "invalid": "the pattern was not a valid regular expression",
    "untested": "no recent commands to test it on",
    "no-commands": "its evidence ran no commands",
    "changed": "the note changed while the model answered; run it again",
}


def report(results: list) -> list[str]:
    lines = []
    for r in results:
        if r.status == "guarded":
            lines.append(f"{r.rule}: guard {r.pattern} (caught {r.caught}/{r.evidence}, "
                         f"quiet on {r.quiet_on} recent commands)")  # fmt: skip
        elif r.status == "noisy":
            lines.append(f"{r.rule}: no guard; {r.pattern} also matched {json.dumps(r.hits)}")
        else:
            lines.append(f"{r.rule}: no guard ({_WHY_NOT.get(r.status, r.status)})")
    return lines

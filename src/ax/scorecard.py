"""A weekly scorecard of how the agent setup is doing, from the archive alone.

Each week counts, in the user's own sessions of both tools: messages, corrections
(and the "I said" or "again" kind that repeat one), progress nudges, frustration
moments (those `ax learn label` confirmed, plus marked ones it hasn't checked yet),
guard blocks, permission denials in headless Claude workers, and cost by model and
effort (Codex reports no cost, only sessions). Across the whole window it lists each
active rule with how often its guard fired, errors that recur across sessions, and
installed skills nobody used. Nothing calls a model.
"""

import html
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ax import learn, profile
from ax.sources.common import first_line

NUDGE = re.compile(
    r"(?i)^\s*(?:any\s+)?(?:progress|status|update|news)\s*\??\s*$|did it finish|is it (?:done|finished)"
    r"|how(?:'s| is) it going"
)
REPEAT = re.compile(r"(?i)\b(?:i said|i told you|again|as i said)\b")
_ERROR_LINE = re.compile(r"(?i)\b(?:error|warning|denied|exception|traceback|failed)\b")
# On a raw JSON line an escaped newline ("\\nWARNING") hides word boundaries.
_ERROR_ANYWHERE = re.compile(r"(?i)error|warning|denied|exception|traceback|failed")
_DENIAL = "Permission to use "
_MIN_FRICTION = 3
_FRICTION_SHOWN = 8
_EXAMPLES = 3
_TRANSCRIPT_VERSION = 2  # bump when what is read from a transcript changes


def _week(when: datetime) -> str:
    year, week, _ = when.isocalendar()
    return f"{year}-W{week:02d}"


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        found = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            found = datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _windows(weeks: int, now: datetime) -> tuple[datetime, list[str]]:
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = monday - timedelta(weeks=weeks - 1)
    return start, [_week(start + timedelta(weeks=i)) for i in range(weeks)]


def _rows(config, sql: str, args=()) -> list[dict]:
    from ax.store import Store

    if not config.db_path.exists():
        return []
    with Store(config.db_path) as store:
        return [dict(r) for r in store.db.execute(sql, args)]


def _human(alias: str = "s") -> str:
    marks = ", ".join(f"'{e}'" for e in learn._HEADLESS)
    return f"{alias}.kind = 'main' AND COALESCE({alias}.entrypoint, '') NOT IN ({marks})"


_ERROR_START = re.compile(r"(?i)^(?:[\w.]*(?:error|exception|warning)\b|fatal\b|failed\b|npm err!)")
_SHELL_ERROR = re.compile(
    r"(?i)\b(?:permission denied|command not found|no such file or directory)\b"
)
_LISTING = re.compile(r"^\s*\d+(?:\t|→|:)")  # a numbered line of a file being read
_READS = ("sed ", "cat ", "head ", "tail ", "rg ", "grep ", "nl ", "less ", "git show", "git diff")


def _signature(text: str) -> str | None:
    """A tool output's error, made generic: numbers, paths and quoted parts replaced.

    A traceback is named by its last exception line; otherwise the first line that
    starts like an error or carries a shell error counts. Numbered file listings are
    skipped, since code that mentions errors isn't one.
    """
    lines = [x.strip() for x in text.splitlines() if x.strip() and not _LISTING.match(x)]
    if "Traceback (most recent call last)" in text:
        raised = [x for x in lines if re.match(r"^[\w.]*(?:Error|Exception)\b", x)]
        line = raised[-1] if raised else None
    else:
        line = next((x for x in lines if _ERROR_START.match(x) or _SHELL_ERROR.search(x)), None)
    if line is None:
        return None
    line = re.sub(r"(?:/[\w.@-]+)+", "PATH", line.lower())
    line = re.sub(r"(['\"`]).*?\1", "'…'", line)
    return re.sub(r"\d+", "N", line)[:120]


def _calls(record: dict) -> dict:
    """Claude's shell commands in one transcript line, by tool call id."""
    found = {}
    content = (record.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            command = (block.get("input") or {}).get("command")
            if block.get("name") == "Bash" and isinstance(command, str):
                found[block.get("id")] = first_line(command, 160)
    return found


def _outputs(record: dict, calls: dict) -> list[tuple[str, str | None]]:
    """Tool output in one transcript line, with the command that produced it when known:
    Claude's tool results, Codex's command output."""
    if record.get("type") == "user":
        found = []
        for block in (record.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                if isinstance(content, str):
                    found.append((content, calls.get(block.get("tool_use_id"))))
        return found
    payload = record.get("payload") or {}
    item = payload.get("item") or {}
    if payload.get("type") == "item_completed" and item.get("type") == "CommandExecution":
        command = item.get("command") or ""
        command = command if isinstance(command, str) else " ".join(map(str, command))
        if any(read in command for read in _READS):
            return []  # a file being shown, not a command failing
        return [(item.get("aggregated_output") or "", first_line(command, 160) or None)]
    return []


def _skills_used(texts) -> Counter:
    used = Counter()
    for text in texts:
        match = re.match(r"used skill `(?:[\w.-]+:)?([\w.-]+)`", text)
        if not match:
            match = re.search(r"/skills/(?:\.system/)?([\w.-]+)/SKILL\.md", text)
        if match:
            used[match.group(1)] += 1
    return used


def _installed(config) -> list[str]:
    names = set()
    for root in (config.claude_home / "skills", config.agents_home / "skills",
                 config.codex_home / "skills"):  # fmt: skip
        if root.is_dir():
            names |= {p.name for p in root.iterdir() if not p.name.startswith(".") and
                      (p / "SKILL.md").exists()}  # fmt: skip
    return sorted(names)


def _transcripts(config, sessions: list[dict]) -> dict:
    """Denied tool calls and error signatures per raw transcript, cached by size and mtime.

    The archive keeps a one-line summary of each tool call, not its output, so these
    come from the transcripts themselves.
    """
    cache_path = config.data / "scorecard-transcripts.json"
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    found = {}
    for s in sessions:
        path = Path(s["source_path"] or "")
        if not path.is_file():
            continue
        stat = path.stat()
        key, stamp = str(path), f"{stat.st_size}:{stat.st_mtime_ns}"
        if cache.get(key, {}).get("stamp") != stamp or cache[key].get("v") != _TRANSCRIPT_VERSION:
            cache[key] = {"stamp": stamp, **_read_transcript(path)}
        found[s["key"]] = cache[key]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache))
    return found


def _read_transcript(path: Path) -> dict:
    denials, signatures, examples, calls = 0, set(), {}, {}
    with path.open(errors="replace") as f:
        for line in f:
            call = '"tool_use"' in line and '"Bash"' in line
            result = ("tool_result" in line or "CommandExecution" in line) and bool(
                _ERROR_ANYWHERE.search(line)
            )
            if not (call or result):
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            calls.update(_calls(record))
            for output, command in _outputs(record, calls):
                if output.startswith(_DENIAL):
                    denials += 1
                elif signature := _signature(output):
                    signatures.add(signature)
                    if command:
                        examples.setdefault(signature, command)
    return {
        "v": _TRANSCRIPT_VERSION,
        "denials": denials,
        "signatures": sorted(signatures),
        "examples": examples,
    }


def _guard_log(config) -> list[dict]:
    path = config.data / "guard.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        when = _parse(entry.get("ts"))
        if when:
            entries.append({**entry, "when": when})
    return entries


_COSTED = (
    "SELECT key, provider, project, model, effort, cost_usd, ended, entrypoint, source_path "
    "FROM sessions WHERE kind = 'main' AND ended >= ?"
)


def _friction(sessions: list[dict], transcripts: dict) -> list[dict]:
    """Error signatures seen in at least three sessions, most widespread first."""
    found = defaultdict(lambda: {"sessions": set(), "last": "", "projects": set(), "examples": []})
    for s in sorted(sessions, key=lambda s: s["ended"] or "", reverse=True):
        record = transcripts.get(s["key"], {})
        for signature in record.get("signatures", []):
            entry = found[signature]
            entry["sessions"].add(s["key"])
            entry["last"] = max(entry["last"], s["ended"] or "")
            if s["project"]:
                entry["projects"].add(s["project"])
            example = record.get("examples", {}).get(signature)
            if example and example not in entry["examples"] and len(entry["examples"]) < _EXAMPLES:
                entry["examples"].append(example)
    return sorted(
        (
            {"signature": k, "sessions": len(v["sessions"]), "last_seen": v["last"][:10],
             "projects": sorted(v["projects"]), "examples": v["examples"]}
            for k, v in found.items()
            if len(v["sessions"]) >= _MIN_FRICTION
        ),
        key=lambda f: -f["sessions"],
    )  # fmt: skip


def recurring(config, *, weeks: int = 8, now: datetime | None = None) -> list[dict]:
    """Every error that recurs across sessions in the window, with example commands."""
    start, _ = _windows(weeks, now or datetime.now(UTC))
    sessions = _rows(config, _COSTED, (start.isoformat(),))
    return _friction(sessions, _transcripts(config, sessions))


def build(config, *, weeks: int = 6, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    start, names = _windows(weeks, now)
    since = start.isoformat()
    week = {
        n: {"week": n, "sessions": Counter(), "user_messages": 0, "corrections": 0, "repeats": 0,
            "nudges": 0, "frustration": 0, "frustration_unchecked": 0, "guard_fires": 0,
            "denials": 0,
            "cost": defaultdict(lambda: {"sessions": 0, "usd": None})}
        for n in names
    }  # fmt: skip

    def slot(value):
        when = _parse(value)
        return week.get(_week(when)) if when and when >= start else None

    for s in _rows(
        config, f"SELECT provider, ended FROM sessions s WHERE {_human()} AND ended >= ?", (since,)
    ):
        if (w := slot(s["ended"])) is not None:
            w["sessions"][s["provider"]] += 1
    users = _rows(
        config,
        "SELECT m.id, m.text, COALESCE(m.ts, s.ended) AS ts FROM messages m JOIN sessions s "
        f"ON s.key = m.session_key WHERE {_human()} AND m.role = 'user' AND s.ended >= ?",
        (since,),
    )
    labels = learn.load_labels(config)
    for m in users:
        text = learn._request(m["text"])
        if not text or text.startswith(learn._BOILERPLATE) or (w := slot(m["ts"])) is None:
            continue
        w["user_messages"] += 1
        if learn._CORRECTION.search(learn._BENIGN.sub("", text)):
            w["corrections"] += 1
        if REPEAT.search(text):
            w["repeats"] += 1
        if NUDGE.search(text):
            w["nudges"] += 1
        if learn.frustrated(text):
            confirmed = labels.get(f"m{m['id']}", {}).get("frustrated")
            if confirmed is None:
                w["frustration_unchecked"] += 1
            elif confirmed:
                w["frustration"] += 1
    fires = Counter()
    for entry in _guard_log(config):
        fires[entry.get("rule")] += 1
        if (w := slot(entry["when"].isoformat())) is not None:
            w["guard_fires"] += 1
    costed = _rows(config, _COSTED, (since,))
    transcripts = _transcripts(config, costed)
    for s in costed:
        w = slot(s["ended"])
        if w is None or not s["model"]:
            continue
        entry = w["cost"][f"{s['model']} · {s['effort'] or '-'}"]
        entry["sessions"] += 1
        if s["provider"] == "claude" and s["cost_usd"] is not None:
            entry["usd"] = round((entry["usd"] or 0) + s["cost_usd"], 2)
        if s["entrypoint"] == "sdk-cli":
            w["denials"] += transcripts.get(s["key"], {}).get("denials", 0)
    tools = _rows(
        config,
        "SELECT m.text FROM messages m JOIN sessions s ON s.key = m.session_key "
        "WHERE m.role = 'tool' AND s.ended >= ? AND "
        "(m.text LIKE 'used skill%' OR m.text LIKE '%SKILL.md%')",
        (since,),
    )
    used = _skills_used(t["text"] for t in tools)
    rules = []
    for rule in profile.load_rules(config):
        if rule.status == "active":
            rules.append({"id": rule.id, "level": rule.level, "added": rule.added,
                          "guard_fires": fires.get(rule.id, 0)})  # fmt: skip
    return {
        "generated": now.isoformat(timespec="seconds"),
        "weeks": [
            {**w, "sessions": dict(w["sessions"]), "cost": dict(w["cost"])} for w in week.values()
        ],
        "rules": rules,
        "friction": _friction(costed, transcripts)[:_FRICTION_SHOWN],
        "skills": {
            "used": dict(sorted(used.items())),
            "unused": [n for n in _installed(config) if n not in used],
        },
    }


def _frustration(week: dict, *, long: bool = False) -> str:
    """Confirmed frustration moments, and those the labeller hasn't checked yet."""
    unchecked = week["frustration_unchecked"]
    if not unchecked:
        return str(week["frustration"])
    return (
        f"{week['frustration']} (+{unchecked} unchecked)"
        if long
        else f"{week['frustration']}+{unchecked}?"
    )


def text(card: dict) -> str:
    """The scorecard for a terminal."""
    lines = ["week      sessions  messages  corrections  repeats  nudges  frustr.  guard  denials"]
    for w in card["weeks"]:
        sessions = sum(w["sessions"].values())
        rate = (
            f"{w['corrections']} ({100 * w['corrections'] / w['user_messages']:.0f}%)"
            if w["user_messages"]
            else "0"
        )
        lines.append(
            f"{w['week']:<9} {sessions:>8}  {w['user_messages']:>8}  {rate:>11}  {w['repeats']:>7}  "
            f"{w['nudges']:>6}  {_frustration(w):>7}  {w['guard_fires']:>5}  {w['denials']:>7}"
        )
    quiet = [r["id"] for r in card["rules"] if r["level"] == "block" and not r["guard_fires"]]
    if quiet:
        lines.append(f"block rules that never fired: {', '.join(quiet)}")
    for f in card["friction"]:
        lines.append(f"recurring: {f['sessions']} sessions · {f['signature']}")
    if card["skills"]["unused"]:
        lines.append(f"skills never used: {', '.join(card['skills']['unused'])}")
    return "\n".join(lines)


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")


def markdown(card: dict) -> str:
    """The scorecard as a vault note, regenerated by `ax scorecard --note`."""
    lines = [
        "---",
        "type: scorecard",
        f"generated: {card['generated'][:16]}",
        f"weeks: {len(card['weeks'])}",
        "---",
        "",
        "# Scorecard",
        "",
        f"Generated {_local(card['generated'])} by `ax scorecard --note` from your own "
        "sessions in both tools; it is regenerated, so don't edit it.",
        "",
        "## Weeks",
        "",
        '| Week | Sessions | Messages | Corrections | "I said" / again | Nudges | Frustration '
        "| Guard blocks | Worker denials |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for w in card["weeks"]:
        share = (
            f" ({100 * w['corrections'] / w['user_messages']:.0f}%)" if w["user_messages"] else ""
        )
        lines.append(
            f"| {w['week']} | {sum(w['sessions'].values())} | {w['user_messages']} | "
            f"{w['corrections']}{share} | {w['repeats']} | {w['nudges']} | "
            f"{_frustration(w, long=True)} | {w['guard_fires']} | {w['denials']} |"
        )
    lines += [
        "",
        "## Rules",
        "",
        "| Rule | Level | Added | Guard blocks |",
        "| --- | --- | --- | ---: |",
    ]
    for r in card["rules"]:
        lines.append(
            f"| [[Profile/rules/{r['id']}\\|{r['id']}]] | {r['level']} | {r['added'] or ''} | "
            f"{r['guard_fires']} |"
        )
    lines += ["", "## Errors that recur", ""]
    if card["friction"]:
        lines += [f"- {f['sessions']} sessions: `{f['signature']}`" for f in card["friction"]]
    else:
        lines.append("No error recurs across three sessions.")
    used = ", ".join(f"{k} ({v})" for k, v in card["skills"]["used"].items()) or "none"
    lines += ["", "## Skills", "", f"- Used: {used}"]
    lines.append(f"- Never used: {', '.join(card['skills']['unused']) or 'none'}")
    if card["weeks"]:
        latest = card["weeks"][-1]
        lines += ["", f"## Cost by model and effort, {latest['week']}", "",
                  "| Model · effort | Sessions | Cost |", "| --- | ---: | ---: |"]  # fmt: skip
        for name, c in sorted(latest["cost"].items()):
            cost = "" if c["usd"] is None else f"${c['usd']:,.2f}"
            lines.append(f"| {name} | {c['sessions']} | {cost} |")
        lines.append("")
        lines.append("Codex reports no cost; only its sessions are counted.")
    return "\n".join(lines) + "\n"


def render(card: dict) -> str:
    """The weekly page served at /scorecard."""
    e = html.escape
    head = "".join(f"<th>{e(h)}</th>" for h in (
        "Week", "Sessions", "Messages", "Corrections", "“I said”/again", "Nudges",
        "Frustration", "Guard blocks", "Worker denials"))  # fmt: skip
    rows = "".join(
        f"<tr><td>{e(w['week'])}</td><td>{sum(w['sessions'].values())}</td>"
        f"<td>{w['user_messages']}</td><td>{w['corrections']}</td><td>{w['repeats']}</td>"
        f"<td>{w['nudges']}</td><td>{e(_frustration(w, long=True))}</td>"
        f"<td>{w['guard_fires']}</td><td>{w['denials']}</td></tr>"
        for w in card["weeks"]
    )
    cost_rows = "".join(
        f"<tr><td>{e(w['week'])}</td><td>{e(name)}</td><td>{c['sessions']}</td>"
        f"<td>{'' if c['usd'] is None else f'${c['usd']:,.2f}'}</td></tr>"
        for w in card["weeks"] for name, c in sorted(w["cost"].items())
    )  # fmt: skip
    rule_rows = "".join(
        f"<tr><td>{e(r['id'])}</td><td>{e(r['level'])}</td><td>{e(r['added'] or '')}</td>"
        f"<td>{r['guard_fires']}</td></tr>"
        for r in card["rules"]
    )
    friction = (
        "".join(
            f"<li><strong>{f['sessions']}</strong> sessions · <code>{e(f['signature'])}</code>"
            f" <span class='muted'>last {e(f['last_seen'])}</span></li>"
            for f in card["friction"]
        )
        or "<li class='muted'>No error recurs across three sessions.</li>"
    )
    used = ", ".join(f"{e(k)} ({v})" for k, v in card["skills"]["used"].items()) or "none"
    unused = ", ".join(e(n) for n in card["skills"]["unused"]) or "none"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ax scorecard</title>
<style>{_STYLE}</style></head><body><main>
<header><h1>Scorecard</h1><p class="muted">{e(card["generated"][:16].replace("T", " "))} · <a href="/">dashboard</a></p></header>
<section class="panel"><h2>Weeks</h2><div class="scroll"><table><tr>{head}</tr>{rows}</table></div></section>
<section class="panel"><h2>Rules</h2><table><tr><th>Rule</th><th>Level</th><th>Added</th><th>Guard blocks</th></tr>{rule_rows}</table></section>
<section class="panel"><h2>Errors that recur</h2><ul>{friction}</ul></section>
<section class="panel"><h2>Skills</h2><p>Used: {used}</p><p>Never used: {unused}</p></section>
<section class="panel"><h2>Cost by model and effort</h2><p class="muted">Codex reports no cost; only its sessions are counted.</p>
<div class="scroll"><table><tr><th>Week</th><th>Model · effort</th><th>Sessions</th><th>Cost</th></tr>{cost_rows}</table></div></section>
</main></body></html>"""


_STYLE = """
:root { --bg:#f6f6f7; --panel:#fff; --text:#1c1c1f; --muted:#6b6b74; --line:#e4e4e8; --accent:#4f46e5; }
@media (prefers-color-scheme: dark) { :root { --bg:#111113; --panel:#1a1a1e; --text:#ececf0;
  --muted:#9a9aa4; --line:#2b2b31; --accent:#818cf8; } }
body { margin:0; background:var(--bg); color:var(--text);
  font:15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width:1120px; margin:0 auto; padding:24px 16px 48px; }
header { display:flex; align-items:baseline; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
h1 { font-size:22px; margin:0; } h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); margin:0 0 12px; font-weight:600; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px;
  margin-bottom:12px; }
.muted { color:var(--muted); } .scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:6px 8px; border-top:1px solid var(--line); white-space:nowrap; }
th { color:var(--muted); font-weight:600; border-top:none; font-size:13px; }
ul { margin:0; padding-left:18px; } li { margin:4px 0; }
a { color:var(--text); text-decoration:none; border-bottom:1px solid var(--line); }
code { font-size:13px; }
"""

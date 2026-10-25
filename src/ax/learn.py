"""Propose profile rules from the user's own corrections in both tools, for approval.

The learner reads only what the user wrote: messages in human sessions of Claude Code
and Codex (never headless workers, subagents or the forum's characters), the reasons
the user gave when refusing a Claude tool call, plus the preference signals Codex
already extracted into its raw memories. It never changes the profile on its own:
proposals are rule notes with status "proposed", settled with `ax learn accept` or
`ax learn reject`.

1. scan, with no model: messages with correction phrases, the message right after an
   interruption, explicit requests to remember something, praise for what the agent
   had just done (unless it only moves on to the next task), frustration markers with
   the episode that led to them, tool-rejection reasons, and Codex's preference
   signals. Pasted plans, attached-file headers and form answers are skipped.
2. label, with Claude Haiku through `claude -p`, redacted first: a kind, a one-sentence
   rule, a topic slug (an existing rule's id when it restates one), a scope, and
   whether losing it would cause a repeat mistake. A frustration moment is labelled
   from its whole episode: the model confirms the frustration and names the lesson.
   Labels are cached; nothing is labelled twice.
3. propose: labels are grouped by topic and wording. A group needs a support of two to
   become a proposal, where a session counts once, an explicit request twice and a
   confirmed frustration moment three times, and two projects to be global. A group
   that restates an active rule reinforces it instead, and quotes dated after the rule
   was added count as recurrences. A rejected proposal returns only once its support
   has doubled.
"""

import hashlib
import json
import os
import re
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ax import profile
from ax.redact import redact

KINDS = (
    "preference", "never-rule", "quality-bar", "domain-fact", "workflow", "environment-fix",
    "permission", "none",
)  # fmt: skip
# One session's evidence counts once, an explicit request to remember twice and a confirmed
# frustration moment three times; a group needs MIN_SUPPORT to become a proposal.
WEIGHTS = {"frustration": 3, "explicit": 2}
MIN_SUPPORT = 2
MIN_PROJECTS_GLOBAL = 2
QUOTES = 3
MAX_MESSAGE = 2000
EPISODE_BATCH = 5
EPISODE_CHARS = 4000
_TURN_CHARS = 600
_REQUEST_CHARS = 60  # a user message this long starts the work an episode covers
_EPISODE_REQUESTS = 3  # look back at most this many user messages for that start
_COMMANDS = 10
_MIN_PRAISED = 25  # praise needs this much of the agent's turn to say what it praises
_HEADLESS = ("sdk-cli", "codex_exec", "requirements_forum")
_BOILERPLATE = (
    "PLEASE IMPLEMENT THIS PLAN", '[{"questionItemId"', "Complete only the supplied assignment",
    "Implement the proposed plan", "[Request interrupted", "<", "Caveat:",
)  # fmt: skip
_REQUEST = "## My request for Codex:"
_INTERRUPTED = "[Request interrupted by user"
_BENIGN = re.compile(r"(?i)\bI (?:don'?t|do not) (?:know|understand|remember|see|think|get)\b")
_CORRECTION = re.compile(
    r"(?i)\b(?:never|don'?t|do not|stop|avoid|instead|i said|i told you|again|as i said|"
    r"not what i asked|why did you|you should(?:n'?t)? have|no need to|remember to|always|"
    r"must not|shouldn'?t|stop doing)\b"
)
_EXPLICIT = re.compile(
    r"(?i)(?:^|[.!?\n]\s*)(?:please\s+)?remember\b(?:\s+(?:this|that))?\s*[:,]|\bremember to\b"
    r"|\bfrom now on\b|\bgoing forward\b|\bin (?:the )?future\b|\bkeep in mind\b"
    r"|\bfor future (?:sessions|reference)\b"
)
_FRUSTRATION = re.compile(
    r"(?i)\b(?:disappoint\w*|frustrat\w*|unacceptable|ridiculous|terrible|awful|useless|pathetic"
    r"|sloppy|careless|wtf|what the (?:hell|heck|fuck)|for (?:god'?s|christ'?s) sake|seriously"
    r"|come on|how many times|i (?:already|just) (?:told|said|asked)|you (?:just )?had to"
    r"|you (?:broke|ruined|wasted|destroyed)|waste of (?:my )?time|not again)\b|!!|\?!|!\?"
)
_SHOUT = re.compile(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,}){2,}\b")
_PRAISE = re.compile(
    r"(?i)^\W*(?:great|perfect|excellent|awesome|amazing|nice|beautiful|brilliant|fantastic"
    r"|good job|well done|love (?:it|this)|exactly|that'?s (?:it|perfect|great|exactly))\b"
)
# Praise followed by the next task is an acknowledgement, not an approach to repeat.
_PIVOT = re.compile(
    r"(?i)^\W*(?:now|next|then|also|and|but|so|ok(?:ay)?|let'?s|can you|could you|would you"
    r"|please|go ahead|proceed|continue|run|do|make|add|fix|commit|push|merge|create|write"
    r"|implement|build|start)\b"
)
_REASON = re.compile(
    r"(?i)\b(?:because|that'?s (?:exactly )?(?:how|what)|this is (?:exactly )?(?:how|what)"
    r"|i (?:like|love|prefer|want)|keep (?:doing|it)|like this|this way|the way you)\b"
)
_RAN = re.compile(r"ran (?:[\w.-]+ )?(`+) ?(.*?) ?\1$")
_REJECTED = "The user doesn't want to proceed with this tool use."
_SAID = "the user said:\n"
_STOP = frozenset(
    re.findall(
        r"\S+",
        "a an the to of in on for and or but is are be it its this that with as at by from do "
        "don't dont not no never always any all each when if then than so you your we our i my "
        "me use using used should must",
    )
)
_RETIRE = "Review it if it hasn't fired in 90 days, or if the correction keeps coming back."


def folder(config) -> Path:
    return config.data / "learn"


# 1. scan


def _request(text: str) -> str:
    """The user's own words in a message that starts with attached context."""
    return text.split(_REQUEST, 1)[1].strip() if _REQUEST in text else text.strip()


def _messages(config):
    from ax.store import Store

    if not config.db_path.exists():
        return []
    marks = ", ".join("?" for _ in _HEADLESS)
    with Store(config.db_path) as store:
        return [
            dict(r)
            for r in store.db.execute(
                "SELECT m.id, m.session_key, m.ts, m.role, m.text, s.session_id, s.project, "
                "s.provider, s.note_path FROM messages m JOIN sessions s ON s.key = m.session_key "
                f"WHERE s.kind = 'main' AND COALESCE(s.entrypoint, '') NOT IN ({marks}) "
                "ORDER BY m.session_key, m.seq",
                _HEADLESS,
            )
        ]


def frustrated(text: str) -> bool:
    """Whether a message carries a frustration marker; the labeller confirms it."""
    return bool(_FRUSTRATION.search(text) or _SHOUT.search(text))


def _praise(text: str, context: str) -> bool:
    match = _PRAISE.match(text)
    if not match or len(context.strip()) < _MIN_PRAISED:
        return False
    if _REASON.search(text):
        return True
    return not _PIVOT.match(text[match.end() :].lstrip(" ,.!:;-"))


def _signals(text: str, context: str, interrupted: bool) -> list[str]:
    found = []
    if frustrated(text):
        found.append("frustration")
    if _EXPLICIT.search(text):
        found.append("explicit")
    if interrupted:
        found.append("interrupted")
    if _praise(text, context):
        found.append("praise")
    if _CORRECTION.search(_BENIGN.sub("", text)):
        found.append("phrase")
    return found


def _squash(text: str, limit: int, *, tail: bool = False) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:] if tail else text[:limit] + "…"


def _episode(turns: list) -> str:
    """The turns since the request that started the work a message reacts to."""
    start, asked = 0, 0
    for i in range(len(turns) - 1, -1, -1):
        if turns[i][0] != "user":
            continue
        asked += 1
        if len(turns[i][1]) >= _REQUEST_CHARS or asked == _EPISODE_REQUESTS:
            start = i
            break
    lines = [
        f"tool: {text}" if role == "tool" else
        f"user: {_squash(text, _TURN_CHARS)}" if role == "user" else
        f"agent: {_squash(text, _TURN_CHARS, tail=True)}"
        for role, text in turns[start:]
    ]  # fmt: skip
    text = "\n".join(lines)
    if len(text) <= EPISODE_CHARS:
        return text
    head = lines[0]
    rest = text[-(EPISODE_CHARS - len(head)) :]
    return head + "\n…\n" + rest[rest.find("\n") + 1 :]


def _command(text: str) -> str | None:
    """The command in an archived "ran `…`" tool line."""
    match = _RAN.match(text)
    return match.group(2) if match else None


def _candidate(row: dict, text: str, signals: list, context: str, commands: list) -> dict:
    return {
        "id": f"m{row['id']}",
        "source": "message",
        "session": row["session_id"],
        "project": row["project"],
        "provider": row["provider"],
        "ts": row["ts"],
        "note": row["note_path"],
        "text": text,
        "context": context[-300:],
        "signals": signals,
        "commands": commands[-_COMMANDS:],
    }


def _from_messages(config) -> list[dict]:
    found, session = [], None
    for row in _messages(config):
        if row["session_key"] != session:
            session, context, interrupted, turns, commands = row["session_key"], "", False, [], []
        if row["role"] == "assistant":
            context = row["text"]
            turns.append(("assistant", row["text"]))
            continue
        if row["role"] == "tool":
            command = _command(row["text"])
            if command:
                commands.append(command)
            turns.append(("tool", command or row["text"]))
            continue
        if row["role"] != "user":
            continue
        raw = row["text"].strip()
        if raw.startswith(_INTERRUPTED):
            interrupted = True
            continue
        text = _request(raw)
        if not text or text.startswith(_BOILERPLATE) or len(text) > MAX_MESSAGE:
            turns.append(("user", text or raw))
            interrupted, commands = False, []
            continue
        signals = _signals(text, context, interrupted)
        if signals:
            candidate = _candidate(row, text, signals, context, commands)
            if "frustration" in signals:
                candidate["episode"] = _episode([*turns, ("user", text)])
            found.append(candidate)
        turns.append(("user", text))
        interrupted, commands = False, []
    return found


def _human_claude_sessions(config) -> list[dict]:
    from ax.store import Store

    if not config.db_path.exists():
        return []
    marks = ", ".join("?" for _ in _HEADLESS)
    with Store(config.db_path) as store:
        return [
            dict(r)
            for r in store.db.execute(
                "SELECT session_id, project, note_path, source_path FROM sessions "
                "WHERE provider = 'claude' AND kind = 'main' AND source_path IS NOT NULL "
                f"AND COALESCE(entrypoint, '') NOT IN ({marks})",
                _HEADLESS,
            )
        ]


def _tool_call(block: dict) -> tuple[str, str | None]:
    """A tool call as one line, and its shell command when it has one."""
    from ax.sources.common import first_line

    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    command = args.get("command") if isinstance(args.get("command"), str) else None
    detail = command or args.get("file_path") or args.get("url") or ""
    summary = f"{block.get('name') or 'tool'} {first_line(str(detail))}".strip()
    return summary, first_line(command) if command else None


def _read_rejections(path: Path) -> list[dict]:
    calls, found = {}, []
    with path.open(errors="replace") as f:
        for line in f:
            if '"tool_use"' not in line and _REJECTED not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    calls[block.get("id")] = _tool_call(block)
                    continue
                result = block.get("content")
                if isinstance(result, list):
                    result = "\n".join(c.get("text", "") for c in result if isinstance(c, dict))
                if not (isinstance(result, str) and result.startswith(_REJECTED)):
                    continue
                if _SAID not in result:
                    continue
                summary, command = calls.get(block.get("tool_use_id"), ("", None))
                found.append(
                    {
                        "call": str(block.get("tool_use_id")),
                        "ts": record.get("timestamp"),
                        "text": result.split(_SAID, 1)[1].strip(),
                        "summary": summary,
                        "command": command,
                    }
                )
    return found


def _from_rejections(config) -> list[dict]:
    """The reasons the user gave when refusing a Claude tool call, cached per transcript."""
    cache_path = folder(config) / "rejections.json"
    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}
    found = []
    for s in _human_claude_sessions(config):
        path = Path(s["source_path"])
        if not path.is_file():
            continue
        stat = path.stat()
        stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
        if cache.get(str(path), {}).get("stamp") != stamp:
            cache[str(path)] = {"stamp": stamp, "found": _read_rejections(path)}
        for r in cache[str(path)]["found"]:
            if not r["text"] or len(r["text"]) > MAX_MESSAGE:
                continue
            digest = hashlib.sha1(f"{s['session_id']}\n{r['call']}".encode()).hexdigest()[:12]
            found.append(
                {
                    "id": f"r{digest}",
                    "source": "rejection",
                    "session": s["session_id"],
                    "project": s["project"],
                    "provider": "claude",
                    "ts": r["ts"],
                    "note": s["note_path"],
                    "text": r["text"],
                    "context": f"refused tool call: {r['summary']}",
                    "signals": ["rejection"],
                    "commands": [r["command"]] if r["command"] else [],
                }
            )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache))
    return found


def _notes_by_session(config) -> dict:
    from ax.store import Store

    if not config.db_path.exists():
        return {}
    with Store(config.db_path) as store:
        return {r["session_id"]: r["note_path"] for r in store.all_sessions() if r["note_path"]}


def _from_codex_memories(config) -> list[dict]:
    """The "Preference signals" bullets of Codex's raw memories, one candidate each."""
    path = config.codex_home / "memories" / "raw_memories.md"
    if not path.exists():
        return []
    notes = _notes_by_session(config)
    found = []
    for block in re.split(r"(?m)^## Thread `", path.read_text(errors="replace"))[1:]:
        thread = block.split("`", 1)[0]
        cwd = re.search(r"(?m)^cwd: (.+)$", block)
        updated = re.search(r"(?m)^updated_at: (.+)$", block)
        for section in re.findall(r"(?ms)^Preference signals:\n(.*?)(?:\n\s*\n|\Z)", block):
            for bullet in re.findall(r"(?m)^- (.+)$", section):
                digest = hashlib.sha1(f"{thread}\n{bullet}".encode()).hexdigest()[:12]
                found.append(
                    {
                        "id": f"c{digest}",
                        "source": "codex-memory",
                        "session": thread,
                        "project": Path(cwd.group(1).strip()).name if cwd else None,
                        "provider": "codex",
                        "ts": updated.group(1).strip() if updated else None,
                        "note": notes.get(thread),
                        "text": bullet.strip(),
                        "context": "",
                        "signals": ["codex-memory"],
                        "commands": [],
                    }
                )
    return found


def scan(config) -> list[dict]:
    """Every candidate in the archive and Codex's memories, without calling a model."""
    return _from_messages(config) + _from_rejections(config) + _from_codex_memories(config)


def save_candidates(config, candidates: list[dict]) -> Path:
    path = folder(config) / "candidates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in candidates))
    return path


def load_candidates(config) -> list[dict]:
    path = folder(config) / "candidates.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# 2. label


_FIELDS = """- "id": the item's id
- "kind": one of preference, never-rule, quality-bar, domain-fact, workflow,
  environment-fix, permission, none. Use none for a one-off instruction, a question,
  thanks, or anything not meant to hold beyond the task at hand.
- "lasting": true only if losing it would make an agent repeat the mistake later
- "rule": the rule as one imperative sentence an agent can follow, or "" for none
- "topic": a kebab-case slug of two to four words naming the rule. If it restates one
  of the existing rules below, use that rule's id.
- "scope": "global" if it applies to any project, "repo" if it is specific to this
  codebase"""

_PROMPT = """You label messages a user wrote to their coding agents (Claude Code and Codex).
Each item is one message, with the end of the agent's previous turn as context. Decide
whether the message states a lasting preference or rule about how agents should work
for this user. An item's signals say how it was found: "explicit" means the user asked
for it to be remembered; "praise" means the user approved what the agent had just done,
so the rule is that approach, if it is general; "rejection" means the user refused a
tool call (the context names it) and this is the reason they gave.

Return only a JSON array with one object per item:
{fields}

Existing rules:
{rules}

Items:
{items}
"""

_EPISODE_PROMPT = """You read episodes from a user's work with coding agents (Claude Code
and Codex). Each episode is the request that started the work, what the agent said and
ran ("tool:" lines are commands and tool calls), and the user's message at the end,
which may show frustration or disappointment with the agent.

Return only a JSON array with one object per item:
- "frustrated": true if the final message expresses real frustration or disappointment
  with the agent, even when it is phrased politely; false for a joke, a quote, plain
  emphasis, or frustration with something other than the agent
{fields}
For "rule", give the lesson that would have prevented this episode: what the agent
should do differently next time, judged from what went wrong in the episode and not
only from the final message.

Existing rules:
{rules}

Items:
{items}
"""


def _existing_rules(config) -> str:
    rules = "\n".join(
        f"- {r.id}: {r.rule}" for r in profile.load_rules(config) if r.status != "retired"
    )
    return rules or "(none yet)"


def _prompt(config, batch: list[dict]) -> str:
    items = "\n".join(
        json.dumps(
            {
                "id": c["id"],
                "project": c["project"],
                "signals": c["signals"],
                "context": redact(c["context"]),
                "message": redact(c["text"]),
            },
            ensure_ascii=False,
        )
        for c in batch
    )
    return _PROMPT.format(fields=_FIELDS, rules=_existing_rules(config), items=items)


def _episode_prompt(config, batch: list[dict]) -> str:
    items = "\n".join(
        json.dumps(
            {
                "id": c["id"],
                "project": c["project"],
                "episode": redact(c.get("episode") or c["context"]),
                "message": redact(c["text"]),
            },
            ensure_ascii=False,
        )
        for c in batch
    )
    return _EPISODE_PROMPT.format(fields=_FIELDS, rules=_existing_rules(config), items=items)


def claude_model(model: str = "haiku"):
    """A labeller that asks Claude through `claude -p`, with no tools, hooks or memory."""
    from ax.job_wake import clean_env

    def ask(prompt: str) -> str:
        done = subprocess.run(
            [
                "claude", "-p", "--model", model, "--output-format", "json", "--safe-mode",
                "--tools", "", "--no-session-persistence",
            ],
            input=prompt, capture_output=True, text=True, timeout=600,
            env=clean_env(os.environ),
        )  # fmt: skip
        if done.returncode != 0:
            raise RuntimeError((done.stderr or done.stdout).strip()[-300:] or "claude failed")
        return json.loads(done.stdout).get("result", "")

    return ask


def _parse(answer: str) -> list[dict]:
    start, end = answer.find("["), answer.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        found = json.loads(answer[start : end + 1])
    except ValueError:
        return []
    return [x for x in found if isinstance(x, dict) and isinstance(x.get("id"), str)]


def _clean_label(raw: dict) -> dict:
    kind = raw.get("kind") if raw.get("kind") in KINDS else "none"
    topic = re.sub(r"[^a-z0-9]+", "-", str(raw.get("topic") or "").lower()).strip("-")[:60]
    return {
        "kind": kind,
        "lasting": raw.get("lasting") is True,
        "rule": str(raw.get("rule") or "").strip(),
        "topic": topic,
        "scope": "repo" if raw.get("scope") == "repo" else "global",
        "frustrated": raw.get("frustrated") is True,
    }


def load_labels(config) -> dict:
    path = folder(config) / "labels.json"
    return json.loads(path.read_text()) if path.exists() else {}


def label(config, candidates, *, model=None, batch: int = 20, workers: int = 4) -> dict:
    """Label every candidate that has no label yet; returns all labels."""
    labels = load_labels(config)
    todo = [c for c in candidates if c["id"] not in labels]
    if not todo:
        return labels
    model = model or claude_model()
    path = folder(config) / "labels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    def run(job):
        chunk, build = job
        answer = _parse(model(build(config, chunk)))
        wanted = {c["id"] for c in chunk}
        with lock:
            for raw in answer:
                if raw["id"] in wanted:
                    labels[raw["id"]] = _clean_label(raw)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(labels, indent=1))
            tmp.replace(path)

    episodes = [c for c in todo if "frustration" in c["signals"]]
    plain = [c for c in todo if "frustration" not in c["signals"]]
    jobs = [(plain[i : i + batch], _prompt) for i in range(0, len(plain), batch)]
    jobs += [
        (episodes[i : i + EPISODE_BATCH], _episode_prompt)
        for i in range(0, len(episodes), EPISODE_BATCH)
    ]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(run, jobs))
    return labels


# 3. group, propose, reinforce


def _words(text: str) -> set:
    found = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in _STOP or len(word) < 3:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if len(word) > 5 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        found.add(word)
    return found


def _overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def weight(candidate: dict, label: dict) -> int:
    """How much one candidate counts toward a group's support."""
    if "frustration" in candidate["signals"] and label.get("frustrated"):
        return WEIGHTS["frustration"]
    if "explicit" in candidate["signals"]:
        return WEIGHTS["explicit"]
    return 1


@dataclass
class Group:
    topic: str
    members: list = field(default_factory=list)  # (candidate, label)

    @property
    def sessions(self) -> set:
        return {c["session"] for c, _ in self.members}

    @property
    def support(self) -> int:
        """Each session counts once, at the weight of its strongest candidate."""
        best: dict = {}
        for c, lab in self.members:
            best[c["session"]] = max(best.get(c["session"], 0), weight(c, lab))
        return sum(best.values())

    @property
    def projects(self) -> set:
        return {c["project"] for c, _ in self.members if c["project"]}

    @property
    def rule(self) -> str:
        """The wording that shares the most words with the others."""
        texts = [lab["rule"] for _, lab in self.members if lab["rule"]]
        if not texts:
            return ""
        return max(texts, key=lambda t: sum(_overlap(_words(t), _words(o)) for o in texts))

    @property
    def words(self) -> set:
        return _words(self.rule + " " + self.topic.replace("-", " "))


def groups(candidates, labels) -> list[Group]:
    by_topic: dict[str, Group] = {}
    for c in candidates:
        lab = labels.get(c["id"])
        if not lab or lab["kind"] == "none" or not lab["lasting"] or not lab["topic"]:
            continue
        by_topic.setdefault(lab["topic"], Group(lab["topic"])).members.append((c, lab))
    merged: list[Group] = []
    for group in sorted(by_topic.values(), key=lambda g: -len(g.members)):
        twin = next((m for m in merged if _overlap(m.words, group.words) >= 0.75), None)
        if twin:
            twin.members += group.members
        else:
            merged.append(group)
    return merged


def _matches(group: Group, rule) -> bool:
    if group.topic == rule.id or group.topic in rule.covers:
        return True
    return _overlap(group.words, _words(rule.rule)) >= 0.6


def _ledger(config, name: str) -> dict:
    path = folder(config) / name
    return json.loads(path.read_text()) if path.exists() else {}


def _save_ledger(config, name: str, data: dict) -> None:
    path = folder(config) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _rule_id(topic: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", topic.lower()).strip("-")[:56] or "learned-rule"
    if not base[0].isalnum():
        base = "rule-" + base
    rid, n = base, 1
    while rid in taken:
        n += 1
        rid = f"{base}-{n}"
    return rid


def _link(note: str | None) -> str:
    return f"[[{note.removesuffix('.md')}]]" if note else "(no archived note)"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _strong(group: Group) -> list[str]:
    moments = sum(
        "frustration" in c["signals"] and lab.get("frustrated") for c, lab in group.members
    )
    asked = sum("explicit" in c["signals"] for c, _ in group.members)
    found = [_plural(moments, "frustration moment")] if moments else []
    if asked:
        found.append(f"asked to remember {_plural(asked, 'time')}")
    return found


def _why(group: Group, kinds: Counter) -> str:
    # Strong evidence first: it is what a reviewer most needs to see.
    quotes = sorted(
        group.members,
        key=lambda m: (weight(*m), m[0]["ts"] or ""),
        reverse=True,
    )[:QUOTES]
    strong = "; ".join(_strong(group))
    lines = [
        f"Proposed by `ax learn` on {date.today().isoformat()} from "
        f"{_plural(len(group.sessions), 'session')} in {len(group.projects) or 1} project(s) "
        f"(kind: {kinds.most_common(1)[0][0]}{'; ' + strong if strong else ''}).",
        "",
        "Evidence:",
    ]
    for c, lab in quotes:
        quote = re.sub(r"\s+", " ", redact(c["text"]))[:240]
        line = f'- {_link(c["note"])} {str(c["ts"] or "")[:10]}: "{quote}"'
        if c.get("episode") and lab.get("frustrated"):
            request = c["episode"].split("\n", 1)[0].removeprefix("user: ")
            line += f' (after: "{_squash(redact(request), 160)}")'
        lines.append(line)
    return "\n".join(lines)


def _scope(group: Group) -> str:
    projects = Counter(c["project"] for c, _ in group.members if c["project"])
    repo_votes = sum(lab["scope"] == "repo" for _, lab in group.members)
    if projects and (repo_votes * 2 > len(group.members) or len(projects) < MIN_PROJECTS_GLOBAL):
        return f"repo:{projects.most_common(1)[0][0]}"
    return "global"


def propose(config, candidates, labels) -> list:
    """Write a proposal note for each new group with enough support; returns them.

    Groups that land on one note (a pending proposal, or what a merge folded into it
    through its `covers`) are combined first. A pending proposal keeps its wording,
    scope and level, which the user may have edited; only its evidence is refreshed.
    """
    rules = profile.load_rules(config)
    rejected = _ledger(config, "rejected.json")
    proposals = _ledger(config, "proposals.json")
    taken = {r.id for r in rules}
    pending: dict = {}
    targets: dict[str, Group] = {}
    for group in groups(candidates, labels):
        if any(r.status in ("active", "retired") and _matches(group, r) for r in rules):
            continue
        rule = next((r for r in rules if r.status == "proposed" and _matches(group, r)), None)
        if rule:
            rid = pending.setdefault(rule.id, rule).id
        else:
            folded = (k for k, v in rejected.items() if group.topic in v.get("covers", ()))
            rid = next(folded, None) or _rule_id(group.topic, taken)
            taken.add(rid)
        targets.setdefault(rid, Group(group.topic)).members.extend(group.members)
    written = []
    for rid, group in targets.items():
        if group.support < MIN_SUPPORT:
            continue
        if rid in rejected and group.support < 2 * rejected[rid]["support"]:
            continue
        kinds = Counter(lab["kind"] for _, lab in group.members)
        evidence = [c["id"] for c, _ in group.members][:20]
        if rid in pending:
            rule = pending[rid]
            # Keep the tidy pass's contradiction notes; they hold until the user decides.
            notes = [n for n in rule.why.split("\n\n") if n.startswith("May contradict")]
            rule.why, rule.evidence = "\n\n".join([_why(group, kinds), *notes]), evidence
            profile._write(rule, rule.path)
        else:
            rule = profile.add(
                config, rid, rule=group.rule, scope=_scope(group), status="proposed",
                why=_why(group, kinds), retire_when=_RETIRE, evidence=evidence,
            )  # fmt: skip
        proposals[rid] = {
            "support": group.support,
            "sessions": len(group.sessions),
            "projects": len(group.projects),
            "kind": kinds.most_common(1)[0][0],
            "date": date.today().isoformat(),
        }
        written.append(rule)
    _save_ledger(config, "proposals.json", proposals)
    return written


def reinforcement(config, candidates, labels) -> dict:
    """For each active rule: sessions that restate it, and how many came after it was added."""
    found = {}
    active = [r for r in profile.load_rules(config) if r.status == "active"]
    for group in groups(candidates, labels):
        for rule in active:
            if not _matches(group, rule):
                continue
            entry = found.setdefault(rule.id, {"sessions": set(), "after": set()})
            for c, _ in group.members:
                entry["sessions"].add(c["session"])
                if rule.added and (c["ts"] or "")[:10] > rule.added:
                    entry["after"].add(c["session"])
    return {
        k: {"support": len(v["sessions"]), "recurrences": len(v["after"])} for k, v in found.items()
    }


def recall(config, candidates, labels) -> dict:
    """Which active rules the labelled corrections rediscover: a check on the learner."""
    seen = reinforcement(config, candidates, labels)
    active = [r.id for r in profile.load_rules(config) if r.status == "active"]
    return {
        "found": [r for r in active if r in seen],
        "missed": [r for r in active if r not in seen],
    }


def _proposed(config, rule_id: str):
    rule = next((r for r in profile.load_rules(config) if r.id == rule_id), None)
    if rule is None or rule.status != "proposed":
        raise ValueError(f"no proposal {rule_id!r}; see `ax learn list`")
    return rule


def accept(config, rule_id: str):
    rule = _proposed(config, rule_id)
    rule.status = "active"
    profile._write(rule, rule.path)
    return rule


def reject(config, rule_id: str) -> None:
    rule = _proposed(config, rule_id)
    support = _ledger(config, "proposals.json").get(rule_id, {}).get("support", MIN_SUPPORT)
    rejected = _ledger(config, "rejected.json")
    rejected[rule_id] = {
        "support": support,
        "covers": rule.covers,
        "date": date.today().isoformat(),
    }
    _save_ledger(config, "rejected.json", rejected)
    rule.path.unlink()

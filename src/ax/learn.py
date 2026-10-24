"""Propose profile rules from the user's own corrections in both tools, for approval.

The learner reads only what the user wrote: messages in human sessions of Claude Code
and Codex (never headless workers, subagents or the forum's characters), plus the
preference signals Codex already extracted into its raw memories. It never changes
the profile on its own: proposals are rule notes with status "proposed", settled with
`ax learn accept` or `ax learn reject`.

1. scan, with no model: messages with correction phrases, the message right after an
   interruption, and Codex's preference signals. Pasted plans, attached-file headers
   and form answers are skipped.
2. label, with Claude Haiku through `claude -p`, redacted first: a kind, a one-sentence
   rule, a topic slug (an existing rule's id when it restates one), a scope, and
   whether losing it would cause a repeat mistake. Labels are cached; nothing is
   labelled twice.
3. propose: labels are grouped by topic and wording. A group needs two sessions to
   become a proposal and two projects to be global. A group that restates an active
   rule reinforces it instead, and quotes dated after the rule was added count as
   recurrences. A rejected proposal returns only once its support has doubled.
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
MIN_SESSIONS = 2
MIN_PROJECTS_GLOBAL = 2
QUOTES = 3
MAX_MESSAGE = 2000
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


def _candidate(row: dict, text: str, signals: list, context: str) -> dict:
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
    }


def _from_messages(config) -> list[dict]:
    found, session, context, interrupted = [], None, "", False
    for row in _messages(config):
        if row["session_key"] != session:
            session, context, interrupted = row["session_key"], "", False
        if row["role"] != "user":
            if row["role"] == "assistant":
                context = row["text"]
            continue
        raw = row["text"].strip()
        if raw.startswith(_INTERRUPTED):
            interrupted = True
            continue
        text = _request(raw)
        if not text or text.startswith(_BOILERPLATE) or len(text) > MAX_MESSAGE:
            interrupted = False
            continue
        signals = ["interrupted"] if interrupted else []
        if _CORRECTION.search(_BENIGN.sub("", text)) and not signals:
            signals = ["phrase"]
        interrupted = False
        if signals:
            found.append(_candidate(row, text, signals, context))
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
                    }
                )
    return found


def scan(config) -> list[dict]:
    """Every candidate in the archive and Codex's memories, without calling a model."""
    return _from_messages(config) + _from_codex_memories(config)


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


_PROMPT = """You label messages a user wrote to their coding agents (Claude Code and Codex).
Each item is one message, with the end of the agent's previous turn as context. Decide
whether the message states a lasting preference or rule about how agents should work
for this user.

Return only a JSON array with one object per item:
- "id": the item's id
- "kind": one of preference, never-rule, quality-bar, domain-fact, workflow,
  environment-fix, permission, none. Use none for a one-off instruction, a question,
  thanks, or anything not meant to hold beyond the task at hand.
- "lasting": true only if losing it would make an agent repeat the mistake later
- "rule": the rule as one imperative sentence an agent can follow, or "" for none
- "topic": a kebab-case slug of two to four words naming the rule. If it restates one
  of the existing rules below, use that rule's id.
- "scope": "global" if it applies to any project, "repo" if it is specific to this
  codebase

Existing rules:
{rules}

Items:
{items}
"""


def _prompt(config, batch: list[dict]) -> str:
    rules = "\n".join(
        f"- {r.id}: {r.rule}" for r in profile.load_rules(config) if r.status != "retired"
    )
    items = "\n".join(
        json.dumps(
            {
                "id": c["id"],
                "project": c["project"],
                "context": redact(c["context"]),
                "message": redact(c["text"]),
            },
            ensure_ascii=False,
        )
        for c in batch
    )
    return _PROMPT.format(rules=rules or "(none yet)", items=items)


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

    def run(chunk):
        answer = _parse(model(_prompt(config, chunk)))
        wanted = {c["id"] for c in chunk}
        with lock:
            for raw in answer:
                if raw["id"] in wanted:
                    labels[raw["id"]] = _clean_label(raw)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(labels, indent=1))
            tmp.replace(path)

    chunks = [todo[i : i + batch] for i in range(0, len(todo), batch)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(run, chunks))
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


@dataclass
class Group:
    topic: str
    members: list = field(default_factory=list)  # (candidate, label)

    @property
    def sessions(self) -> set:
        return {c["session"] for c, _ in self.members}

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


def _why(group: Group, kinds: Counter) -> str:
    quotes = sorted(group.members, key=lambda m: m[0]["ts"] or "", reverse=True)[:QUOTES]
    lines = [
        f"Proposed by `ax learn` on {date.today().isoformat()} from {len(group.sessions)} "
        f"sessions in {len(group.projects) or 1} project(s) (kind: {kinds.most_common(1)[0][0]}).",
        "",
        "Evidence:",
    ]
    for c, _ in quotes:
        quote = re.sub(r"\s+", " ", redact(c["text"]))[:240]
        lines.append(f'- {_link(c["note"])} {str(c["ts"] or "")[:10]}: "{quote}"')
    return "\n".join(lines)


def propose(config, candidates, labels) -> list:
    """Write a proposal note for each new group with enough support; returns them."""
    rules = profile.load_rules(config)
    rejected = _ledger(config, "rejected.json")
    proposals = _ledger(config, "proposals.json")
    taken = {r.id for r in rules}
    written = []
    for group in groups(candidates, labels):
        if len(group.sessions) < MIN_SESSIONS:
            continue
        settled = [r for r in rules if r.status in ("active", "retired") and _matches(group, r)]
        if settled:
            continue
        pending = next((r for r in rules if r.status == "proposed" and _matches(group, r)), None)
        rid = pending.id if pending else _rule_id(group.topic, taken)
        if rid in rejected and len(group.sessions) < 2 * rejected[rid]["sessions"]:
            continue
        kinds = Counter(lab["kind"] for _, lab in group.members)
        projects = Counter(c["project"] for c, _ in group.members if c["project"])
        repo_votes = sum(lab["scope"] == "repo" for _, lab in group.members)
        if projects and (
            repo_votes * 2 > len(group.members) or len(projects) < MIN_PROJECTS_GLOBAL
        ):
            scope = f"repo:{projects.most_common(1)[0][0]}"
        else:
            scope = "global"
        rule = profile.add(
            config, rid, rule=group.rule, scope=scope, status="proposed",
            why=_why(group, kinds), retire_when=_RETIRE,
            evidence=[c["id"] for c, _ in group.members][:20], replace=bool(pending),
        )  # fmt: skip
        taken.add(rid)
        proposals[rid] = {
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
    support = _ledger(config, "proposals.json").get(rule_id, {}).get("sessions", MIN_SESSIONS)
    rejected = _ledger(config, "rejected.json")
    rejected[rule_id] = {"sessions": support, "date": date.today().isoformat()}
    _save_ledger(config, "rejected.json", rejected)
    rule.path.unlink()

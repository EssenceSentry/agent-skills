"""Bring an earlier conversation into this one: an outline, a card, or what a task needs.

- outline, with no model call: the user's turns as a table of contents, where the
  conversation ended, the files it changed, its links and the note's path, so the
  agent can read any part of it in full.
- card: a summary Haiku writes once per conversation (goal, outcome, decisions, open
  items, facts), cached until the conversation changes.
- focus: a model reads the whole conversation against the task at hand and returns
  only what the task needs, citing turn times; cached per task.

The model reads the dialogue only: user and agent messages, never tool output.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from ax import handles
from ax.store import Store

TURNS = 60
HEAD = 15
TURN_CHARS = 300
END_CHARS = 2000
DIALOGUE_CHARS = 150_000  # what a model reads; a longer conversation keeps its start and end
_CHANGED = ("edited ", "wrote ", "patched ", "deleted ")

_CARD = """You summarize an earlier conversation between a user and a coding agent (Claude Code
or Codex) so that a later conversation can build on it. Return only a JSON object:
{{"goal": "what the user wanted, one sentence",
  "outcome": "where it ended, one or two sentences",
  "decisions": ["a decision and its reason, one sentence each"],
  "open": ["what was left unfinished or undecided"],
  "facts": ["something learned that stays true: a path, command, number or name"],
  "files": ["files created or changed"]}}
Use [] for an empty list. Leave out greetings, progress chatter and anything later undone.

The conversation, "{title}":
{dialogue}
"""

_FOCUS = """A user is starting this task with a coding agent:

{task}

Below is an earlier conversation, "{title}". Bring back only what helps with the task:
decisions and their reasons, facts (paths, commands, numbers, names), what was tried and
failed, and open questions. Cite each item with the time of the turn it comes from, like
(10:42). Be brief: at most 400 words, as a Markdown list. If nothing in it bears on the
task, say so in one line.

The conversation:
{dialogue}
"""


def _messages(config, row) -> list[dict]:
    with Store(config.db_path) as store:
        return [
            dict(r)
            for r in store.db.execute(
                "SELECT ts, role, text FROM messages WHERE session_key = ? ORDER BY seq",
                (row["key"],),
            )
        ]


def _links(config, row) -> tuple[list, list]:
    with Store(config.db_path) as store:
        return store.links_from(row["key"]), store.links_to(row["key"])


def _clock(ts, *, day: bool = False) -> str:
    try:
        when = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    return when.strftime("%Y-%m-%d %H:%M" if day else "%H:%M")


def _line(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _names(rows) -> str:
    seen = {}
    for r in rows:
        seen.setdefault(
            r["session_id"], f"{r['title'] or 'Untitled'} ({handles.tag(r['session_id'])})"
        )
    return "; ".join(seen.values())


def header(config, row) -> str:
    """Title, handle, where and when, links, and the note to read in full."""
    span = _clock(row["started"], day=True)
    if row["ended"]:
        span += f"–{_clock(row['ended'])}"
    lines = [
        f"# {row['title'] or 'Untitled'} · {handles.tag(row['session_id'])}",
        " · ".join(
            x
            for x in (
                row["provider"].title(),
                row["project"],
                span,
                f"{row['user_turns'] or 0} turns",
            )
            if x
        ),  # fmt: skip
    ]
    before, after = _links(config, row)
    if before:
        lines.append(f"Builds on: {_names(before)}")
    if after:
        lines.append(f"Built on by: {_names(after)}")
    if row["note_path"]:
        lines.append(f"Full conversation: {config.vault / row['note_path']}")
    return "\n".join(lines)


def outline(config, row) -> str:
    """The conversation at a glance, with no model call."""
    messages = _messages(config, row)
    asked = [m for m in messages if m["role"] == "user"]
    lines = [header(config, row), "", "## Your turns"]
    shown = asked if len(asked) <= TURNS else asked[:HEAD] + asked[-(TURNS - HEAD) :]
    for i, m in enumerate(shown):
        if len(asked) > TURNS and i == HEAD:
            lines.append(f"- … {len(asked) - TURNS} more turns …")
        stamp = _clock(m["ts"])
        lines.append(f"- {stamp + ' ' if stamp else ''}{_line(m['text'], TURN_CHARS)}")
    said = [m for m in messages if m["role"] == "assistant"]
    if said:
        last = said[-1]["text"].strip()
        tail = last if len(last) <= END_CHARS else last[:END_CHARS] + " …"
        lines += ["", "## Where it ended", tail]
    changed = []
    for m in messages:
        if m["role"] == "tool" and m["text"].startswith(_CHANGED):
            changed += re.findall(r"`([^`]+)`", m["text"])
    if changed:
        lines += ["", "## Files it changed", *(f"- {f}" for f in dict.fromkeys(changed))]
    return "\n".join(lines)


def dialogue(config, row) -> str:
    """User and agent messages with their times, without tool output, for a model to read."""
    parts = [
        f"[{_clock(m['ts'])}] {'User' if m['role'] == 'user' else 'Agent'}: {m['text'].strip()}"
        for m in _messages(config, row)
        if m["role"] in ("user", "assistant") and m["text"].strip()
    ]
    text = "\n\n".join(parts)
    if len(text) <= DIALOGUE_CHARS:
        return text
    head, tail = text[: DIALOGUE_CHARS // 5], text[-(DIALOGUE_CHARS - DIALOGUE_CHARS // 5) :]
    return f"{head}\n\n[… the middle of the conversation is left out …]\n\n{tail}"


def _cache(config, name: str) -> Path:
    return config.data / "recall" / name


def _cached(config, name: str, stamp: str, make) -> str:
    path = _cache(config, name)
    try:
        saved = json.loads(path.read_text())
        if saved.get("stamp") == stamp:
            return saved["text"]
    except (OSError, ValueError):
        pass
    text = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stamp": stamp, "text": text}))
    return text


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _card_text(answer: str) -> str:
    start, end = answer.find("{"), answer.rfind("}")
    try:
        found = json.loads(answer[start : end + 1]) if 0 <= start < end else {}
    except ValueError:
        found = {}
    if not isinstance(found, dict) or not found:
        return answer.strip()
    lines = []
    for key, title in (("goal", "Goal"), ("outcome", "Outcome")):
        if found.get(key):
            lines.append(f"**{title}:** {found[key]}")
    for key, title in (("decisions", "Decisions"), ("open", "Open"), ("facts", "Facts"),
                       ("files", "Files")):  # fmt: skip
        items = [str(x) for x in found.get(key) or [] if str(x).strip()]
        if items:
            lines += ["", f"### {title}", *(f"- {x}" for x in items)]
    return "\n".join(lines)


def card(config, row, *, model) -> str:
    """The conversation's card, written by the model once until the conversation changes."""
    text = dialogue(config, row)

    def make():
        return _card_text(model(_CARD.format(title=row["title"] or "Untitled", dialogue=text)))

    body = _cached(config, f"{row['session_id']}.card.json", _digest(text), make)
    return f"{header(config, row)}\n\n## Card\n{body}"


def focus(config, row, task: str, *, model) -> str:
    """Only what `task` needs from the conversation, read by the model; cached per task."""
    text = dialogue(config, row)

    def make():
        prompt = _FOCUS.format(task=task.strip(), title=row["title"] or "Untitled", dialogue=text)
        return model(prompt).strip()

    name = f"{row['session_id']}.{_digest(task.strip())}.focus.json"
    body = _cached(config, name, _digest(text), make)
    return f"{header(config, row)}\n\n## For: {task.strip()}\n{body}"


def record(config, row, env=None, *, fresh: float | None = None) -> str | None:
    """Link the conversation this runs in to the recalled one; returns the source key."""
    here = handles.current(config, env, fresh=fresh)
    if not here or here[1] == row["session_id"]:
        return None
    source = f"{here[0]}:{here[1]}"
    with Store(config.db_path) as store:
        store.add_link(source, row["key"], "recall")
        store.commit()
    return source

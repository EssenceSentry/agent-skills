"""What a session is doing now, in one line, and the task list of its current turn, read
from its transcript as it grows.

Claude: the tool running now (a call with no result yet), said as the desktop app says
it, "Listing the uncommitted work" from a command described "List the uncommitted work";
and the turn's list from the desktop app's `update_plan` calls, replayed, or Claude Code's
own `TodoWrite`. Codex: what it last said it would do this turn, its commentary, or the
command it runs; its plan reaches ax only live, through a thread ax holds.

Each transcript is read from where the last reading stopped, so a poll costs only what
was written since.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ax.sources.common import first_line

PLAN_TOOL = "mcp__ccd_turn__update_plan"
WRAP_TOOL = "mcp__ccd_turn__wrap_up"
# Tools that keep the list or ask the user: not what the agent is doing.
_QUIET = {PLAN_TOOL, WRAP_TOOL, "TodoWrite", "AskUserQuestion", "ExitPlanMode", "ToolSearch"}


@dataclass
class _State:
    offset: int = 0
    tasks: list | None = None
    explanation: str | None = None
    running: dict = field(default_factory=dict)  # call id -> {text, since}
    said: dict | None = None  # Codex: what it last said it would do this turn
    finished: bool = False  # Codex: the turn has ended

    def new_turn(self) -> None:
        self.tasks, self.explanation, self.said, self.finished = None, None, None, False
        self.running.clear()

    def view(self, provider: str) -> dict:
        tasks = None
        if self.tasks is not None:
            tasks = {"items": [dict(t) for t in self.tasks], "explanation": self.explanation}
        if provider == "codex":
            last = None if self.finished else self.said or _last(self.running)
        else:
            last = _last(self.running)
        return {"activity": dict(last) if last else None, "tasks": tasks}


def _last(running: dict) -> dict | None:
    return next(reversed(running.values()), None)


_states: dict[str, _State] = {}


def clear_cache() -> None:
    _states.clear()


def read(path: Path, provider: str) -> dict:
    """The line and the list as of the transcript's last complete record."""
    key = str(path)
    try:
        size = path.stat().st_size
    except OSError:
        return {"activity": None, "tasks": None}
    state = _states.get(key)
    if state is None or size < state.offset:  # new, or replaced by a shorter file
        state = _states[key] = _State()
    if size > state.offset:
        with path.open("rb") as f:
            f.seek(state.offset)
            chunk = f.read(size - state.offset)
        end = chunk.rfind(b"\n")  # a line still being written waits for the next read
        if end >= 0:
            take = _claude if provider == "claude" else _codex
            for line in chunk[: end + 1].splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    take(state, record)
            state.offset += end + 1
    return state.view(provider)


# Saying what a command does: "List the files" -> "Listing the files"

_NOT_VERBS = {"a", "all", "already", "an", "ax", "each", "git", "new", "no", "npm", "one",
              "that", "the", "these", "this", "two", "uv"}  # fmt: skip
_DOUBLED = {"admit", "begin", "commit", "compel", "control", "equip", "forget", "format",
            "occur", "omit", "outrun", "patrol", "permit", "prefer", "quit", "refer",
            "regret", "rerun", "reset", "submit", "unzip", "upset"}  # fmt: skip
_SHORT = re.compile(r"[^aeiou]*[aeiou][^aeiouwxy]")  # one syllable ending vowel-consonant


def _ing(word: str) -> str | None:
    lower = word.lower()
    if not lower.isalpha() or lower in _NOT_VERBS or lower.endswith("ing"):
        return None
    if lower in _DOUBLED or _SHORT.fullmatch(lower):
        return f"{word}{word[-1]}ing"
    if lower.endswith("ie"):
        return f"{word[:-2]}ying"
    if lower.endswith("e") and not lower.endswith(("ee", "ye", "oe")) and len(lower) > 2:
        return f"{word[:-1]}ing"
    return f"{word}ing"


def doing(text: str) -> str:
    """An imperative description as what is being done; anything else as it is."""
    first, gap, rest = text.strip().partition(" ")
    if not first or not first[0].isupper():
        return text
    ing = _ing(first)
    return f"{ing}{gap}{rest}" if ing else text


def _name(path) -> str:
    return Path(str(path or "")).name or str(path or "")


def _describe(tool: str, given: dict) -> str:
    """One line on what a Claude tool call does."""
    if given.get("action_summary"):  # browser and computer actions say it themselves
        return str(given["action_summary"])
    described = str(given.get("description") or "").strip()
    if tool == "Bash":
        if described:
            return doing(described)
        return f"Running `{first_line(str(given.get('command') or ''), 80)}`"
    if tool == "Read":
        return f"Reading {_name(given.get('file_path'))}"
    if tool in ("Edit", "MultiEdit", "NotebookEdit"):
        return f"Editing {_name(given.get('file_path') or given.get('notebook_path'))}"
    if tool == "Write":
        return f"Writing {_name(given.get('file_path'))}"
    if tool == "Grep":
        return f"Searching for {first_line(str(given.get('pattern') or ''), 60)}"
    if tool == "Glob":
        return f"Finding {given.get('pattern') or 'files'}"
    if tool == "WebSearch":
        return f"Searching the web for {first_line(str(given.get('query') or ''), 60)}"
    if tool == "WebFetch":
        return f"Fetching {urlparse(str(given.get('url') or '')).netloc or 'a page'}"
    if tool == "Skill":
        return f"Using the {given.get('skill') or ''} skill".replace("  ", " ")
    if described:
        return doing(described)
    return f"Using {tool.rsplit('__', 1)[-1]}"


def _status(given) -> str:
    if given in ("in_progress", "inProgress"):
        return "in_progress"
    return "completed" if given == "completed" else "pending"


def _plan(state: _State, given: dict) -> None:
    """The desktop app's list: a whole list, or a step moved on."""
    items = given.get("items")
    if isinstance(items, list):
        state.tasks = [{"text": str(i.get("content") or ""), "status": _status(i.get("status"))}
                       for i in items if isinstance(i, dict)]  # fmt: skip
        return
    if state.tasks is None:
        return
    if given.get("advance"):
        now = next((t for t in state.tasks if t["status"] == "in_progress"), None)
        if now:
            now["status"] = "completed"
        following = next((t for t in state.tasks if t["status"] == "pending"), None)
        if following:
            following["status"] = "in_progress"
    for n in given.get("done") or []:
        if isinstance(n, int) and 1 <= n <= len(state.tasks):
            state.tasks[n - 1]["status"] = "completed"
    start = given.get("start")
    if isinstance(start, int) and 1 <= start <= len(state.tasks):
        state.tasks[start - 1]["status"] = "in_progress"


def _is_prompt(record: dict) -> bool:
    if record.get("isMeta") or record.get("isCompactSummary"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _claude(state: _State, record: dict) -> None:
    kind = record.get("type")
    content = (record.get("message") or {}).get("content")
    if kind == "user":
        if _is_prompt(record):
            state.new_turn()
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    state.running.pop(block.get("tool_use_id"), None)
    elif kind == "assistant" and isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool, given = block.get("name") or "", block.get("input") or {}
            if tool == PLAN_TOOL:
                _plan(state, given)
            elif tool == "TodoWrite" and isinstance(given.get("todos"), list):
                state.tasks = [{"text": str(t.get("content") or ""), "status": _status(t.get("status"))}
                               for t in given["todos"] if isinstance(t, dict)]  # fmt: skip
            elif tool == WRAP_TOOL and state.tasks:
                for task in state.tasks:  # wrapping up checks the list off
                    task["status"] = "completed"
            if tool not in _QUIET:
                state.running[block.get("id")] = {"text": _describe(tool, given),
                                                  "since": record.get("timestamp")}  # fmt: skip


_CMD = re.compile(r'cmd:\s*"((?:[^"\\]|\\.)*)"')


def _command(payload: dict) -> str:
    """What a Codex tool call runs: the first command in its script, or its name."""
    found = _CMD.search(str(payload.get("input") or payload.get("arguments") or ""))
    if found:
        command = found.group(1).replace('\\"', '"').replace("\\n", "\n")
        return f"Running `{first_line(command, 80)}`"
    return f"Running {payload.get('name') or 'a tool'}"


def _codex(state: _State, record: dict) -> None:
    payload = record.get("payload") or {}
    kind, what = record.get("type"), payload.get("type")
    if kind == "event_msg":
        if what in ("task_started", "user_message"):
            state.new_turn()
        elif what == "task_complete":
            state.finished = True
            state.running.clear()
        return
    if kind != "response_item":
        return
    if what == "message" and payload.get("role") == "user":
        state.new_turn()
    elif what == "message" and payload.get("role") == "assistant":
        text = "\n".join(c.get("text") or "" for c in payload.get("content") or []
                         if isinstance(c, dict)).strip()  # fmt: skip
        if text:
            state.said = {"text": first_line(text, 140), "since": record.get("timestamp")}
    elif what in ("custom_tool_call", "function_call"):
        state.running[payload.get("call_id")] = {"text": _command(payload),
                                                 "since": record.get("timestamp")}  # fmt: skip
    elif what in ("custom_tool_call_output", "function_call_output"):
        state.running.pop(payload.get("call_id"), None)

"""To-dos kept where every conversation sees them: one vault note each.

A to-do is global or belongs to one project, and remembers the conversation it was
raised in (its handle) and the one that closed it. The notes live in the vault's
`Todos/` folder, so the user reads and edits them in Obsidian; the start digest lists
the open ones for the project at hand. Ids count up (T1, T2, …) and are never reused,
even when a note is deleted.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from ax.render import safe_title

STATUSES = ("open", "done", "dropped")
_ID = re.compile(r"T(\d+)")


@dataclass
class Todo:
    id: str
    text: str
    status: str = "open"
    scope: str = "global"  # global or project:<repo>
    origin: str | None = None  # the handle of the conversation that raised it
    created: str = ""
    closed: str | None = None
    closed_in: str | None = None
    detail: str = ""
    path: Path | None = field(default=None, compare=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "status": self.status, "scope": self.scope,
                "from": self.origin, "created": self.created, "closed": self.closed,
                "closed_in": self.closed_in, "detail": self.detail,
                "path": str(self.path) if self.path else None}  # fmt: skip


def folder(config) -> Path:
    return config.vault / "Todos"


def _number(todo_id: str) -> int:
    match = _ID.fullmatch(str(todo_id or ""))
    return int(match.group(1)) if match else 0


def _read(path: Path) -> Todo | None:
    text = path.read_text(errors="replace")
    match = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict) or not _number(meta.get("id")):
        return None
    return Todo(
        id=str(meta["id"]), text=str(meta.get("text") or path.stem), path=path,
        status=str(meta.get("status") or "open"), scope=str(meta.get("scope") or "global"),
        origin=meta.get("from"), created=str(meta.get("created") or ""),
        closed=str(meta["closed"]) if meta.get("closed") else None,
        closed_in=meta.get("closed_in"), detail=match.group(2).strip(),
    )  # fmt: skip


def _text(todo: Todo) -> str:
    meta = {"type": "todo", "id": todo.id, "text": todo.text, "status": todo.status,
            "scope": todo.scope, "from": todo.origin, "created": todo.created,
            "closed": todo.closed, "closed_in": todo.closed_in}  # fmt: skip
    meta = {k: v for k, v in meta.items() if v not in (None, "")}
    body = todo.detail.strip()
    return (
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
        + "---\n"
        + (f"\n{body}\n" if body else "")
    )


def everything(config) -> list[Todo]:
    found = [t for p in sorted(folder(config).glob("*.md")) if (t := _read(p))]
    return sorted(found, key=lambda t: _number(t.id))


def get(config, todo_id: str) -> Todo:
    found = next((t for t in everything(config) if t.id == todo_id.upper()), None)
    if found is None:
        raise ValueError(f"no to-do {todo_id}; see `ax todo list --all`")
    return found


def _counter(config) -> Path:
    return config.data / "todos.json"


def add(
    config, text: str, *, scope: str = "global", origin=None, origin_note=None, detail: str = ""
) -> Todo:
    """Write a new open to-do; ids count up from the highest ever given. `origin_note`,
    the raising conversation's note, becomes a link Obsidian follows."""
    text = " ".join(text.split())
    if origin_note:
        detail = f"{detail.strip()}\n\nRaised in [[{origin_note}]].".strip()
    if not text:
        raise ValueError("a to-do needs its text")
    if scope != "global" and not re.fullmatch(r"project:[A-Za-z0-9._-]+", scope):
        raise ValueError(f"scope {scope!r} must be 'global' or 'project:NAME'")
    folder(config).mkdir(parents=True, exist_ok=True)
    try:
        last = json.loads(_counter(config).read_text()).get("last", 0)
    except (OSError, ValueError):
        last = 0
    number = max([last, *(_number(t.id) for t in everything(config))]) + 1
    while True:  # another agent may take the same id at the same moment
        todo = Todo(f"T{number}", text, scope=scope, origin=origin, detail=detail,
                    created=date.today().isoformat())  # fmt: skip
        path = folder(config) / f"{todo.id} {safe_title(text)[:60]}.md"
        try:
            with open(path, "x") as f:
                f.write(_text(todo))
            break
        except FileExistsError:
            number += 1
    todo.path = path
    _counter(config).parent.mkdir(parents=True, exist_ok=True)
    _counter(config).write_text(json.dumps({"last": number}))
    return todo


def close(config, todo_id: str, status: str, *, closed_in=None) -> Todo:
    if status not in ("done", "dropped"):
        raise ValueError("a to-do closes as done or dropped")
    todo = get(config, todo_id)
    if todo.status != "open":
        raise ValueError(f"{todo.id} is already {todo.status}")
    todo.status, todo.closed, todo.closed_in = status, date.today().isoformat(), closed_in
    tmp = todo.path.with_name(f".{todo.path.name}.tmp")
    tmp.write_text(_text(todo))
    os.replace(tmp, todo.path)
    return todo


def listing(config, *, project=None, include_closed=False) -> list[Todo]:
    """Open to-dos (or all), of one project plus the global ones when `project` is given."""
    return [
        t for t in everything(config)
        if (include_closed or t.status == "open")
        and (project is None or t.scope in ("global", f"project:{project}"))
    ]  # fmt: skip


def line(todo: Todo) -> str:
    where = todo.scope.removeprefix("project:")
    origin = f", from {todo.origin}" if todo.origin else ""
    state = "" if todo.status == "open" else f" [{todo.status}]"
    return f"{todo.id} ({where}{origin}){state}: {todo.text}"

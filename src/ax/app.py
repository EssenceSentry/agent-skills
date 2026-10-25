"""The ax app's server side: what waits for the user, the actions on it, and the vault reader.

`ax serve` hosts the built pages (shipped in `web/`, built from `ui/`) and these as JSON.
Each action calls the function its CLI command calls, so the app and the command do the
same thing. The reader serves Markdown notes from inside the vault only, with
`[[wiki links]]` turned into links between the app's pages.
"""

import hashlib
import mimetypes
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import yaml

from ax import handles, learn, learn_guards, learn_life, profile, todos, usage
from ax.store import Store

WEB = Path(__file__).parent / "web"
COOKIE = "ax_token"
NEAR_LIMIT = 80  # percent of a usage window that puts it on the waiting list
RUNS_OUT_SOON = timedelta(days=1)  # or a forecast that runs out this soon
CONVERSATIONS = 15
BUDGET_ENTRIES = 8  # each budget's latest ledger lines on the Now screen
_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}  # not SVG: it can carry script
_COMPILE = "run `ax profile compile --apply` to"


class NotFound(ValueError):
    """A path the reader won't serve: missing, outside the vault, or hidden."""


# The Now state


def now_state(config, *, usage_of=None, credits_of=None) -> dict:
    from ax import serve

    state = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_sync": None,
        "usage": [],
        "credits": [],
        "waiting": [],
        "jobs": [],
        "budgets": [],
        "conversations": [],
        "errors": [],
    }
    found: dict[str, list] = {"job": [], "usage": [], "budget": [], "proposal": [], "review": [],
                              "todo": []}  # fmt: skip

    def gather_usage():
        state["usage"] = serve._usage_rows(config, usage_of or serve._cached_usage)
        found["usage"] = [_usage_item(u) for u in state["usage"] if _near_limit(u)]

    def gather_credits():
        state["credits"] = [_credits_row(c) for c in (credits_of or _credits)(config)]

    def gather_jobs():
        rows = serve._jobs(config)
        state["jobs"] = [j for j in rows if j["status"] == "running"]
        # Only what can still be acted on: running jobs a health check flagged.
        found["job"] = [_job_item(j) for j in state["jobs"] if j["check_error"]]

    def gather_rules():
        problems: list = []
        for rule in profile.load_rules(config, problems=problems):
            if rule.status == "proposed":
                found["proposal"].append(_rule_item(config, rule, "proposal", rule.why))
            elif rule.status == "active" and (rule.review or rule.extra.get("workshop")):
                found["review"].append(_rule_item(config, rule, "review", _flag(rule)))
        state["errors"].extend(f"rules: {p}" for p in problems)

    def gather_todos():
        found["todo"] = [_todo_item(config, t) for t in todos.listing(config)]

    def gather_conversations():
        state["conversations"] = _conversations(config)

    def gather_budgets():
        state["budgets"] = _budgets(config)
        found["budget"] = [_budget_item(b) for b in state["budgets"] if b["state"] == "over"]

    for name, gather in (
        ("usage", gather_usage),
        ("credits", gather_credits),
        ("jobs", gather_jobs),
        ("rules", gather_rules),
        ("to-dos", gather_todos),
        ("budgets", gather_budgets),
        ("conversations", gather_conversations),
    ):
        try:
            gather()
        except Exception as exc:  # one broken source must not blank the page
            state["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
    state["waiting"] = [item for items in found.values() for item in items]
    if config.db_path.exists():
        with Store(config.db_path) as store:
            state["last_sync"] = store.get_meta("last_sync")
    return state


def _credits(config) -> list:
    found = usage.codex_credits(config.codex_home)
    return [found] if found else []


def _credits_row(c) -> dict:
    return {
        "provider": c.provider,
        "balance": c.balance,
        "unlimited": c.unlimited,
        "has_credits": c.has_credits,
        "observed_at": c.observed_at.isoformat(),
        "status": c.status,
    }


def _flag(rule) -> str:
    suggestion = rule.extra.get("workshop") or {}
    if rule.review or suggestion.get("suggest") != "retire":
        return rule.review
    return f"The rules workshop suggests retiring it: {suggestion.get('why') or 'see its report'}"


def _near_limit(row: dict) -> bool:
    """Nearly used, or running out within a day. Early in a window the forecast projects a
    few busy hours over the whole week, so a later run-out shows only on the usage band."""
    if row["used"] is None:
        return False
    if row["used"] >= NEAR_LIMIT:
        return True
    if not (row["runs_out_at"] and row["observed_at"]):
        return False
    left = datetime.fromisoformat(row["runs_out_at"]) - datetime.fromisoformat(row["observed_at"])
    return left <= RUNS_OUT_SOON


def _usage_item(row: dict) -> dict:
    name = f"{row['provider'].capitalize()} {row['window'].replace('_', ' ')}"
    return {
        "kind": "usage",
        "id": f"{row['provider']}-{row['window']}",
        "title": f"{name}: {row['used']:.0f}% used",
        "detail": _left(row),
        "resets_at": row["resets_at"],
        "actions": [],
    }


def _left(row: dict) -> str:
    """What the window leaves: per day until it resets, or in all when that is under a day.
    Counted from the reading, as the app's usage band counts from now."""
    left = max(0.0, 100 - row["used"])
    if not (row["resets_at"] and row["observed_at"]):
        return f"{left:.0f}% left"
    span = datetime.fromisoformat(row["resets_at"]) - datetime.fromisoformat(row["observed_at"])
    days = span.total_seconds() / 86400
    if days < 1:
        return f"{left:.0f}% left before it resets"
    span_text = f"{days:.1f}".removesuffix(".0")
    return f"{left / days:.0f}% a day left for {span_text} {'day' if span_text == '1' else 'days'}"


def _job_item(job: dict) -> dict:
    return {
        "kind": "job",
        "id": job["key"],
        "title": job["label"],
        "detail": job["check_error"] or job["status"],
        "status": job["status"],
        "updated": job["updated"],
        "actions": [],
    }


def _relative(config, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(config.vault.resolve()).as_posix()
    except ValueError:
        return None


def _rule_item(config, rule, kind: str, detail: str) -> dict:
    return {
        "kind": kind,
        "id": rule.id,
        "title": rule.rule,
        "detail": detail,
        "scope": rule.scope,
        "level": rule.level,
        "maturity": rule.maturity,
        "note": _relative(config, rule.path),
        "actions": ["accept", "reject"] if kind == "proposal" else ["keep", "retire", "guard"],
    }


def _todo_item(config, todo) -> dict:
    return {
        "kind": "todo",
        "id": todo.id,
        "title": todo.text,
        "detail": todo.detail,
        "scope": todo.scope,
        "origin": todo.origin,
        "created": todo.created,
        "note": _relative(config, todo.path),
        "actions": ["done", "drop"],
    }


def _budgets(config) -> list[dict]:
    from ax import budget

    found = budget.statuses(config.data)
    for b in found:
        b["entries"] = budget.entries(config.data, b["name"], limit=BUDGET_ENTRIES)
        b["owner_note"] = _note_of(config, b["owner"])
    return found


def _note_of(config, handle: str | None) -> str | None:
    """The vault note of the conversation behind a handle, when it is archived."""
    if not handle:
        return None
    try:
        row = handles.resolve(config, handle)
    except (handles.NotFound, handles.Ambiguous):
        return None
    return row["note_path"]


def _budget_item(b: dict) -> dict:
    from ax.budget import number

    reasons = [e["intent"] for e in b["entries"] if e["intent"]][:2]
    passed = "; ".join(f'"{r}"' for r in reasons)
    return {
        "kind": "budget",
        "id": b["name"],
        "title": f"{b['name']} is over its limit: {number(b['spent'] + b['reserved'])} of "
        f"{number(b['cap'])} {b['unit']}",
        "detail": f"Passed with {passed}." if passed else (b["why"] or ""),
        "origin": b["owner"],
        "note": b["owner_note"],
        "actions": [],
    }


def _conversations(config) -> list[dict]:
    if not config.db_path.exists():
        return []
    with Store(config.db_path) as store:
        rows = store.recent_sessions(CONVERSATIONS)
    return [
        {
            "handle": handles.tag(r["session_id"]),
            "title": r["title"] or "Untitled",
            "provider": r["provider"],
            "project": r["project"],
            "ended": r["ended"],
            "note": r["note_path"],
        }
        for r in rows
    ]


# Actions


def _field(payload: dict, name: str, *, required: str | None = None) -> str:
    value = payload.get(name)
    if value is None or value == "":
        if required:
            raise ValueError(required)
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    return value


def _id(payload: dict) -> str:
    return _field(payload, "id", required="this action needs an id").strip()


def _accept(config, payload, model):
    rule = learn.accept(config, _id(payload))
    return f"accepted {rule.id}; {_COMPILE} load it"


def _reject(config, payload, model):
    learn.reject(config, rule_id := _id(payload))
    return f"rejected {rule_id}"


def _keep(config, payload, model):
    return f"kept {learn_life.keep(config, _id(payload)).id}"


def _retire(config, payload, model):
    return f"retired {learn_life.retire(config, _id(payload)).id}; {_COMPILE} unload it"


def _guard(config, payload, model):
    result = learn_guards.guard_rule(
        config, _id(payload), learn.load_candidates(config), learn.load_labels(config),
        model=model,
    )  # fmt: skip
    said = "\n".join(learn_guards.report([result]))
    return f"{said}; {_COMPILE} load the guard" if result.status == "guarded" else said


def _todo_add(config, payload, model):
    item = todos.add(
        config,
        _field(payload, "text"),
        scope=_field(payload, "scope") or "global",
        detail=_field(payload, "detail"),
    )
    return f"added {todos.line(item)}"


def _closer(status: str):
    def close(config, payload, model):
        return f"{status} {todos.line(todos.close(config, _id(payload), status))}"

    return close


ACTIONS = {
    "accept": _accept,
    "reject": _reject,
    "keep": _keep,
    "retire": _retire,
    "guard": _guard,  # the one action that calls a model (Haiku), as `ax learn guard` does
    "todo-add": _todo_add,
    "todo-done": _closer("done"),
    "todo-drop": _closer("dropped"),
}


def act(config, action: str, payload: dict, *, model=None) -> str:
    """Run one action and say what it did; a ValueError says why it could not."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    return ACTIONS[action](config, payload, model)


# The reader


def _inside(config, rel) -> tuple[Path, str]:
    """The real path of `rel` inside the vault and its clean relative form, or NotFound.
    Hidden folders (.git, .obsidian) and links that lead outside are refused."""
    if not isinstance(rel, str) or rel.startswith("/") or "\\" in rel or "\0" in rel:
        raise NotFound(f"no such path {rel!r}")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." or p.startswith(".") for p in parts):
        raise NotFound(f"no such path {rel!r}")
    root = config.vault.resolve()
    real = root.joinpath(*parts).resolve()
    if not real.is_relative_to(root) or any(
        p.startswith(".") for p in real.relative_to(root).parts
    ):
        raise NotFound(f"no such path {rel!r}")
    return real, "/".join(parts)


def _walk(config):
    root = config.vault.resolve()
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.startswith("."):
                yield (Path(folder) / name).relative_to(root).as_posix()


class _Index:
    """Where each `[[name]]` leads: by file name anywhere, ignoring case, the shortest path
    winning as in Obsidian; or by its path from the vault's top."""

    def __init__(self, config):
        self.by_name: dict[str, list[str]] = {}
        self.by_path: dict[str, str] = {}
        for rel in _walk(config):
            name = rel.rsplit("/", 1)[-1].lower()
            keys = [rel.lower()]
            if name.endswith(".md"):
                keys.append(rel.lower().removesuffix(".md"))
                name = name.removesuffix(".md")
            self.by_name.setdefault(name, []).append(rel)
            for key in keys:
                self.by_path.setdefault(key, rel)

    def find(self, target: str) -> str | None:
        key = target.strip().lower()
        if "/" in key:
            return self.by_path.get(key)
        found = self.by_name.get(key) or self.by_name.get(key.removesuffix(".md"))
        return min(found, key=lambda r: (r.count("/"), len(r))) if found else None


_LINK = re.compile(
    r"(?P<code>(?P<ticks>`+).+?(?P=ticks))"
    r"|(?P<embed>!?)\[\[(?P<target>[^\[\]|]+?)(?:\|(?P<alias>[^\[\]]*))?\]\]"
)
_FENCE = re.compile(r"^\s*(```|~~~)")


def _link(match: re.Match, index: _Index) -> str:
    if match.group("code"):
        return match.group(0)
    name = match.group("target").split("#", 1)[0].strip()
    text = (match.group("alias") or "").strip() or name
    found = index.find(name) if name else None
    if found is None:
        return f"[{text}](#/missing/{quote(name, safe='')})" if name else text
    if not found.endswith(".md"):
        if match.group("embed") and Path(found).suffix.lower() in _IMAGES:
            return f"![{text}](/api/file?path={quote(found, safe='/')})"
        return f"_{text} (an Obsidian view the app doesn't show)_"
    return f"[{text}](#/read/{quote(found, safe='/')})"


def resolve_links(markdown: str, index: _Index) -> str:
    lines, fenced = [], False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        lines.append(line if fenced or _FENCE.match(line) else _LINK.sub(
            lambda m: _link(m, index), line))  # fmt: skip
    return "\n".join(lines)


def _value(value, index: _Index) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_value(v, index) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_value(v, index)}" for k, v in value.items())
    return resolve_links(str(value), index)


def _split(text: str) -> tuple[dict, str]:
    match = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text
    return (meta, match.group(2)) if isinstance(meta, dict) else ({}, text)


def _modified(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def note(config, rel: str) -> dict:
    path, clean = _inside(config, rel)
    if path.suffix.lower() != ".md" or not path.is_file():
        raise NotFound(f"no note {rel!r}")
    meta, body = _split(path.read_text(errors="replace"))
    index = _Index(config)
    return {
        "path": clean,
        "title": str(meta.get("title") or path.stem),
        "properties": [
            {"key": str(k), "value": _value(v, index)} for k, v in meta.items() if k != "title"
        ],
        "markdown": resolve_links(body, index),
        "modified": _modified(path),
    }


def _folder_order(name: str) -> tuple:
    # Year and month folders read newest first; everything else alphabetically.
    return (not name.isdigit(), -int(name) if name.isdigit() else 0, name.lower())


def folder(config, rel: str = "") -> dict:
    path, clean = _inside(config, rel) if rel else (config.vault.resolve(), "")
    if not path.is_dir():
        raise NotFound(f"no folder {rel!r}")
    prefix = f"{clean}/" if clean else ""
    dirs = sorted(
        (p.name for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=_folder_order,
    )
    notes = sorted(
        (p for p in path.iterdir() if p.suffix.lower() == ".md" and p.is_file()),
        key=lambda p: (-p.stat().st_mtime, p.name.lower()),
    )
    return {
        "path": clean,
        "parent": None if not clean else clean.rpartition("/")[0],
        "folders": [{"name": d, "path": prefix + d} for d in dirs],
        "notes": [
            {"path": prefix + p.name, "title": p.stem, "modified": _modified(p)} for p in notes
        ],
    }


def file(config, rel: str) -> tuple[bytes, str]:
    path, _ = _inside(config, rel)
    if path.suffix.lower() not in _IMAGES or not path.is_file():
        raise NotFound(f"no image {rel!r}")
    return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"


# Access and the build


def token(config) -> str:
    """The app's access token, made once and kept owner-only, so a bookmark keeps working."""
    path = config.data / "serve-token"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_urlsafe(32))
    return path.read_text().strip()


UI_SOURCES = ("src", "public", "theme", "index.html", "package.json", "package-lock.json",
              "vite.config.ts", "app.config.json", "components.json", "tsconfig.json",
              "tsconfig.app.json", "tsconfig.node.json")  # fmt: skip
_SKIP = {"node_modules", ".DS_Store"}


def ui_digest(ui: Path) -> str:
    """A digest of the app's sources; `ui/scripts/stamp.mjs` writes the same one into
    `web/BUILD` after a build, so a test can tell when the shipped build is stale."""
    files = []
    for name in UI_SOURCES:
        top = ui / name
        if top.is_file():
            files.append(top)
        elif top.is_dir():
            files += [
                p
                for p in top.rglob("*")
                if p.is_file() and not _SKIP & set(p.relative_to(ui).parts)
            ]
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(ui).as_posix()):
        digest.update(path.relative_to(ui).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()

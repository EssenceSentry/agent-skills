"""A digest of recent work, for the start of every conversation in either tool.

An agent searches past work only when it thinks to. The digest gives each new
conversation a map instead: the user's own conversations of the last week (never
workers or subagents), newest first with the current project's first, each with its
handle, the open to-dos of this project and the global ones, and the jobs still
running with their descriptions. It reads the archive only,
with no sync and no model, so a conversation starts about as fast as before.
"""

from datetime import UTC, datetime, timedelta

from ax import handles, jobs, learn, todos
from ax.sources.common import project_name

DAYS = 7
LIMIT = 30
TODOS = 10
TITLE = 70


def _rows(config, since: str) -> list[dict]:
    from ax.store import Store

    if not config.db_path.exists():
        return []
    marks = ", ".join("?" for _ in learn._HEADLESS)
    with Store(config.db_path) as store:
        return [
            dict(r)
            for r in store.db.execute(
                "SELECT session_id, provider, project, title, started, ended FROM sessions "
                "WHERE kind = 'main' AND note_path IS NOT NULL AND ended >= ? "
                f"AND COALESCE(entrypoint, '') NOT IN ({marks}) ORDER BY ended DESC",
                (since, *learn._HEADLESS),
            )
        ]


def _last_sync(config) -> str | None:
    from ax.store import Store

    if not config.db_path.exists():
        return None
    with Store(config.db_path) as store:
        return store.get_meta("last_sync")


def _when(value) -> str:
    try:
        return (
            datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%m-%d")
        )
    except ValueError:
        return "?"


def _short(text: str | None) -> str:
    text = " ".join((text or "Untitled").split())
    return text if len(text) <= TITLE else text[: TITLE - 1] + "…"


def _age(started: str, now: datetime) -> str:
    minutes = max(0, int((now - jobs.parse_iso(started)).total_seconds() // 60))
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def build(config, *, cwd=None, exclude=None, now=None, days=DAYS, limit=LIMIT) -> str:
    """The digest as Markdown, or "" when there is nothing recent to show."""
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=days)).isoformat()
    rows = [r for r in _rows(config, since) if r["session_id"] != exclude]
    here = project_name(cwd) if cwd else None
    rows.sort(key=lambda r: r["project"] != here)  # stable: newest first within each part
    running = [j for j in jobs.list_jobs(config, refresh_active=False) if not j.terminal]
    open_todos = [t for t in todos.listing(config, project=here) if here or t.scope == "global"]
    if not rows and not running and not open_todos:
        return ""
    synced = _last_sync(config)
    lines = [
        f"## Recent work (from ax: your own Claude Code and Codex conversations, last {days} "
        f"days{', archived at the last sync, ' + synced[11:16] + ' UTC' if synced else ''})",
        "Bring one into this conversation with `ax recall <handle>` (or the ax MCP tool "
        '`recall`) before relying on it; search wider with `ax find "…"`.',
        "",
    ]
    for r in rows[:limit]:
        lines.append(f"- {_when(r['ended'])} · {r['provider']} · {r['project'] or '?'} · "
                     f"{_short(r['title'])} · {handles.tag(r['session_id'])}")  # fmt: skip
    if len(rows) > limit:
        lines.append(f"- … and {len(rows) - limit} more (`ax find --since {days}d`)")
    if open_todos:
        lines += ["", "Open to-dos here and global (`ax todo list`; close with `ax todo done ID`):"]
        lines += [f"- {todos.line(t)}" for t in open_todos[:TODOS]]
        if len(open_todos) > TODOS:
            lines.append(f"- … and {len(open_todos) - TODOS} more")
    if running:
        lines += ["", "Jobs still running (`ax job show KEY`):"]
        for j in running:
            lines.append(
                f"- {j.key} (running {_age(j.created, now)}): {j.label or 'no description'}"
            )
    return "\n".join(lines)


def hook_output(text: str) -> dict:
    """What a SessionStart hook prints so both tools add the text to the conversation."""
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}

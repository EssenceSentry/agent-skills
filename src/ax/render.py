"""Turn a session into an Obsidian note: YAML frontmatter plus a readable transcript."""

import json
import re
from datetime import datetime
from pathlib import Path

from ax.model import Event, Session
from ax.redact import redact
from ax.sources.common import first_line

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_DISPLAY = {"claude": "Claude", "codex": "Codex"}


def safe_title(title: str | None) -> str:
    """A title that is legal in a file name on every OS and in an Obsidian link."""
    text = re.sub(r"\s+", " ", _UNSAFE.sub(" ", title or "")).strip()
    if len(text) > 80:
        text = text[:80].rsplit(" ", 1)[0]
    return text or "Untitled"


def note_stem(session: Session, *, full_id: bool = False) -> str:
    if session.kind != "main":
        return f"{session.provider} {session.session_id}"
    day = _local(session.started).strftime("%Y-%m-%d") if session.started else "undated"
    project = safe_title(redact(session.project))
    title = safe_title(redact(session.title or ""))
    # Codex ids are time-ordered UUIDs, so only their tail tells close sessions apart.
    short = session.session_id if full_id else session.session_id[-8:]
    return f"{day} {session.provider} {project} - {title} ({short})"


def note_relpath(session: Session, *, full_id: bool = False) -> Path:
    if session.started:
        local = _local(session.started)
        folder = Path("Sessions") / f"{local:%Y}" / f"{local:%m}"
    else:
        folder = Path("Sessions") / "undated"
    if session.kind != "main":
        folder = folder / "_subagents"
    return folder / f"{note_stem(session, full_id=full_id)}.md"


def render(
    session: Session,
    *,
    parent_note: str | None = None,
    raw_path: str | None = None,
    children: list[tuple[str, str]] = (),
    builds_on: list[tuple[str, str]] = (),
) -> str:
    """The full note text. `children` lists (note stem, title) of known subagents, and
    `builds_on` the conversations this one recalled or mentioned."""
    title = redact(session.title or "Untitled")
    front = {
        "type": "session",
        "provider": session.provider,
        "kind": session.kind,
        "session_id": session.session_id,
        "title": title,
        "project": redact(session.project),
        "cwd": redact(session.cwd or ""),
        "branch": redact(session.branch or ""),
        "model": session.model,
        "effort": session.effort,
        "entrypoint": session.entrypoint,
        "version": session.version,
        "started": session.started,
        "ended": session.ended,
        "user_turns": session.user_turns,
        "tool_calls": session.tool_calls,
        "tokens_in": session.tokens_in,
        "tokens_out": session.tokens_out,
        "cost_usd": session.cost_usd,
        "parent": f"[[{parent_note}]]" if parent_note else None,
        "builds_on": [f"[[{stem}]]" for stem, _ in builds_on] or None,
        "raw": raw_path,
        "tags": ["session", session.provider, _tag(redact(session.project))],
    }
    lines = ["---", *_yaml(front), "---", "", f"# {title}", "", _byline(session)]
    if parent_note:
        lines += ["", f"Parent: [[{parent_note}]]"]
    if builds_on:
        links = ", ".join(f"[[{stem}|{redact(t or stem)}]]" for stem, t in builds_on)
        lines += ["", f"Builds on: {links}"]
    body = _transcript(session)
    lines += ["", body] if body else []
    linked = {e.child for e in session.events if e.child}
    unlinked = [(stem, t) for stem, t in children if stem.split(" ", 1)[-1] not in linked]
    if unlinked:
        lines += ["", "## Subagents", ""]
        lines += [f"- [[{stem}|{redact(t or stem)}]]" for stem, t in unlinked]
    # A NUL makes git treat the note as binary, which also hides it from secret scans.
    return "\n".join(lines).replace("\0", "").rstrip() + "\n"


def _transcript(session: Session) -> str:
    agent = _DISPLAY.get(session.provider, session.provider)
    chunks: list[str] = []
    tools: list[str] = []
    in_agent_block = False

    def flush_tools():
        if tools:
            chunks.append("\n".join(tools))
            tools.clear()

    for event in session.events:
        if event.kind == "user":
            flush_tools()
            stamp = f"{_local(event.ts):%H:%M} · " if event.ts else ""
            chunks += [f"## {stamp}You", _text(event.text)]
            in_agent_block = False
            continue
        if event.kind in ("assistant", "tool") and not in_agent_block:
            flush_tools()
            chunks.append(f"### {agent}")
            in_agent_block = True
        if event.kind == "assistant":
            flush_tools()
            chunks.append(_text(event.text))
        elif event.kind == "tool":
            tools.append(_tool_line(session, event))
        elif event.kind == "notice":
            flush_tools()
            chunks.append(f"> [!note] {redact(event.text)}")
        elif event.kind == "message":
            flush_tools()
            quoted = "\n".join(f"> {ln}".rstrip() for ln in _text(event.text).splitlines())
            chunks.append(f"> [!quote] {redact(event.tool or '')}\n{quoted}")
    flush_tools()
    return "\n\n".join(chunks)


def _tool_line(session: Session, event: Event) -> str:
    line = f"- {redact(event.text)}"
    if event.ok is False:
        last = next((ln.strip() for ln in reversed(event.output.splitlines()) if ln.strip()), "")
        if last:
            line += f" · failed: {redact(first_line(last, 160))}"
        else:
            line += " · failed"
    if event.child:
        line += f" → [[{session.provider} {event.child}|subagent note]]"
    return line


def _text(text: str) -> str:
    text = redact(text.strip())
    fences = sum(ln.lstrip().startswith("```") for ln in text.splitlines())
    return text + "\n```" if fences % 2 else text


def _byline(session: Session) -> str:
    parts = [_DISPLAY.get(session.provider, session.provider), redact(session.project)]
    if session.started:
        start = _local(session.started)
        span = f"{start:%Y-%m-%d %H:%M}"
        if session.ended:
            span += f"–{_local(session.ended):%H:%M}"
        parts.append(span)
    if session.model:
        parts.append(session.model)
    return " · ".join(parts)


def _yaml(front: dict) -> list[str]:
    lines = []
    for key, value in front.items():
        if value is None or value == "":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines += [f"  - {json.dumps(v, ensure_ascii=False)}" for v in value]
        elif isinstance(value, datetime):
            lines.append(f"{key}: {_local(value):%Y-%m-%dT%H:%M:%S}")
        elif isinstance(value, bool | int | float):
            lines.append(f"{key}: {json.dumps(value)}")
        else:
            lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    return lines


def _tag(text: str) -> str:
    return re.sub(r"[^a-z0-9_/-]+", "-", text.lower()).strip("-") or "unknown"


def _local(ts: datetime) -> datetime:
    return ts.astimezone()

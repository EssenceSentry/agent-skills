"""Codex rollouts: `sessions/YYYY/MM/DD/rollout-*.jsonl[.zst]` and `archived_sessions/`."""

import json
import re
from pathlib import Path

from ax.model import Event, Session
from ax.sources.common import (
    as_text,
    code,
    first_line,
    iter_records,
    parse_ts,
    project_name,
    relative,
)

_TOP_LEVEL = {
    "session_meta",
    "response_item",
    "event_msg",
    "turn_context",
    "token_usage_record",
    "compacted",
    "world_state",
    "realtime_item",
    "inter_agent_communication_metadata",
    "retained_context",
}
_ITEMS = {
    "message",
    "agent_message",
    "compaction",
    "additional_tools",
    "reasoning",
    "function_call",
    "function_call_output",
    "custom_tool_call",
    "custom_tool_call_output",
    "web_search_call",
    "tool_search_call",
    "tool_search_output",
    "local_shell_call",
    "image_generation_call",
}
# Calls that only poll or feed a running process; they add noise, not information.
_QUIET = {"write_stdin", "wait", "sleep"}
# Injected user-role messages whose inner text is still the user's own words.
_KEEP_TAGS = {"send_user_message_question_reply", "user_message"}
_IDE_REQUEST = "## My request for Codex:"
_EXIT = re.compile(r"(?:Process exited with code|Exit code:?)\s*(-?\d+)")
_PATCH_FILE = re.compile(r"\*\*\* (Add|Update|Delete) File: (.+)")
_ID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
_KEEP_OUTPUT = 4000


def discover(home: Path) -> list[Path]:
    """One file per rollout: the newest copy across `.jsonl`, `.jsonl.zst` and the archive."""
    home = Path(home)
    found: dict[str, tuple[int, Path]] = {}
    for root in (home / "sessions", home / "archived_sessions"):
        for path in [*root.rglob("rollout-*.jsonl"), *root.rglob("rollout-*.jsonl.zst")]:
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:  # compressed or archived while we were listing
                continue
            key = session_id_from_name(path) or path.name.removesuffix(".zst")
            if key not in found or mtime > found[key][0]:
                found[key] = (mtime, path)
    return sorted(path for _, path in found.values())


def read_titles(home: Path) -> dict[str, str]:
    """Thread names from `session_index.jsonl`, the names the Codex app shows."""
    titles = {}
    index = Path(home) / "session_index.jsonl"
    if index.exists():
        for line in index.read_text(errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id") and row.get("thread_name"):
                titles[row["id"]] = row["thread_name"]
    return titles


def session_id_from_name(path: Path) -> str | None:
    """A rollout's own id: the last UUID in its name (forks carry the parent's id first)."""
    ids = _ID.findall(Path(path).name)
    return ids[-1] if ids else None


def parse(path: Path, titles: dict[str, str] | None = None) -> Session:
    path = Path(path)
    own_id = session_id_from_name(path)
    session = Session(provider="codex", session_id=own_id or path.stem, source_path=path)
    calls: dict[str, Event | None] = {}
    repo_url = None
    meta_seen = False
    history_start = 0
    stamps = []
    for rec in iter_records(path, session.unknown):
        rtype = rec.get("type")
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        if rtype == "session_meta":
            # Only the first one describes this rollout; a subagent's file then
            # repeats its parent's metadata and history up to `history_start`.
            if not meta_seen:
                meta_seen = True
                repo_url = _meta(session, payload, keep_id=own_id is not None)
                history_start = payload.get("subagent_history_start_ordinal") or 0
                stamps.append(parse_ts(payload.get("timestamp") or rec.get("timestamp")))
            continue
        ordinal = rec.get("ordinal")
        if isinstance(ordinal, int) and ordinal < history_start:
            continue
        ts = parse_ts(rec.get("timestamp"))
        stamps.append(ts)
        if rtype == "turn_context":
            session.model = as_text(payload.get("model")) or session.model
            session.effort = as_text(payload.get("effort")) or session.effort
            session.cwd = session.cwd or as_text(payload.get("cwd"))
        elif rtype == "response_item":
            _item(session, payload, ts, calls)
        elif rtype == "event_msg":
            _event(session, payload, ts)
        elif rtype == "compacted":
            session.events.append(Event("notice", "context compacted", ts))
        elif rtype not in _TOP_LEVEL:
            session.unknown[str(rtype)] += 1

    first_prompt = next((e.text for e in session.events if e.kind == "user"), "")
    session.title = (titles or {}).get(session.session_id) or first_line(first_prompt, 80) or None
    stamps = [ts for ts in stamps if ts]
    if stamps:
        session.started, session.ended = min(stamps), max(stamps)
    session.project = project_name(session.cwd, repo_url)
    return session


def _meta(session: Session, meta: dict, *, keep_id: bool) -> str | None:
    if not keep_id:
        session.session_id = (
            as_text(meta.get("id")) or as_text(meta.get("session_id")) or session.session_id
        )
    session.cwd = as_text(meta.get("cwd")) or session.cwd
    session.entrypoint = as_text(meta.get("originator")) or session.entrypoint
    session.version = as_text(meta.get("cli_version")) or session.version
    git = meta.get("git") if isinstance(meta.get("git"), dict) else {}
    session.branch = as_text(git.get("branch")) or session.branch
    source = meta.get("source")
    if meta.get("thread_source") == "guardian_review":
        session.kind = "guardian"
    elif isinstance(source, dict) and "subagent" in source:
        session.kind = "subagent"
        spawn = (
            source["subagent"].get("thread_spawn") if isinstance(source["subagent"], dict) else None
        )
        if isinstance(spawn, dict):
            session.parent_id = as_text(spawn.get("parent_thread_id"))
    return as_text(git.get("repository_url"))


def _item(session: Session, item: dict, ts, calls: dict) -> None:
    kind = item.get("type")
    if kind == "message":
        texts = [c.get("text", "") for c in item.get("content") or [] if isinstance(c, dict)]
        if item.get("role") == "user":
            for text in texts:
                text = _user_text(text)
                if text:
                    session.events.append(Event("user", text, ts))
        elif item.get("role") == "assistant":
            text = "\n\n".join(t.strip() for t in texts if t.strip())
            if text:
                session.events.append(Event("assistant", text, ts))
    elif kind == "agent_message":
        # A message between agents of one multi-agent run, e.g. a brief or a result.
        texts = [c.get("text", "") for c in item.get("content") or [] if isinstance(c, dict)]
        text = "\n\n".join(t.strip() for t in texts if t.strip())
        if text:
            route = f"{item.get('author') or '?'} → {item.get('recipient') or '?'}"
            session.events.append(Event("message", text, ts, tool=route))
    elif kind == "function_call":
        name = item.get("name") or "tool"
        if name in _QUIET or item.get("namespace") == "clock":
            calls[item.get("call_id")] = None
            return
        event = Event("tool", _summarize_function(name, item, session.cwd), ts, tool=name)
        session.events.append(event)
        calls[item.get("call_id")] = event
    elif kind == "custom_tool_call":
        name = item.get("name") or "tool"
        raw = str(item.get("input") or "")
        if name == "apply_patch":
            text = _patch_summary(raw, session.cwd)
        else:
            text = f"ran {name} {code(first_line(raw, 80))}" if raw.strip() else f"ran {name}"
        event = Event("tool", text, ts, tool=name)
        session.events.append(event)
        calls[item.get("call_id")] = event
    elif kind in ("function_call_output", "custom_tool_call_output"):
        event = calls.get(item.get("call_id"))
        if event is not None:
            _attach_output(event, _output_text(item.get("output")))
    elif kind == "web_search_call":
        action = item.get("action") if isinstance(item.get("action"), dict) else {}
        query = action.get("query")
        text = f"searched the web for “{query}”" if query else "searched the web"
        session.events.append(Event("tool", text, ts, tool="web_search"))
    elif kind not in _ITEMS:
        session.unknown[f"response_item:{kind}"] += 1


def _event(session: Session, event: dict, ts) -> None:
    kind = event.get("type")
    if kind == "token_count":
        info = event.get("info") if isinstance(event.get("info"), dict) else {}
        total = info.get("total_token_usage")
        if isinstance(total, dict):
            session.tokens_in = total.get("input_tokens", session.tokens_in)
            session.tokens_out = total.get("output_tokens", session.tokens_out)
    elif kind == "turn_aborted":
        session.events.append(Event("notice", "turn interrupted", ts))


def _user_text(text: str) -> str:
    text = text.strip()
    if text.startswith("<"):
        tag = re.match(r"<([\w-]+)", text)
        if tag and tag.group(1) in _KEEP_TAGS:
            return re.sub(r"</?[\w-]+[^>]*>", "", text).strip()
        return ""
    if text.startswith("# AGENTS.md instructions"):
        return ""
    if text.startswith("# Context from my IDE setup:"):
        _, found, request = text.partition(_IDE_REQUEST)
        return request.strip() if found else ""
    return text


def _summarize_function(name: str, item: dict, cwd: str | None) -> str:
    try:
        args = json.loads(item.get("arguments") or "{}")
    except ValueError:
        args = {}
    args = args if isinstance(args, dict) else {}
    if name == "exec_command":
        return f"ran {code(first_line(str(args.get('cmd') or '')))}"
    if name == "update_plan":
        return "updated the plan"
    if name.startswith("request_user_input"):
        return "asked you a question"
    namespace = item.get("namespace")
    if namespace:
        return f"called {namespace.removeprefix('mcp__')} · {name}"
    return f"called {name}"


def _patch_summary(patch: str, cwd: str | None) -> str:
    files: list[list] = []
    for line in patch.splitlines():
        match = _PATCH_FILE.match(line)
        if match:
            files.append([match.group(1), relative(match.group(2).strip(), cwd), 0, 0])
        elif line.startswith("***") or not files:
            continue
        elif line.startswith("+"):
            files[-1][2] += 1
        elif line.startswith("-"):
            files[-1][3] += 1
    if not files:
        return "applied a patch"
    parts = []
    for action, path, added, removed in files:
        if action == "Delete":
            parts.append(f"deleted {code(path)}")
        else:
            parts.append(f"{code(path)} +{added} −{removed}")
    return "patched " + ", ".join(parts)


def _attach_output(event: Event, text: str) -> None:
    event.output = text[-_KEEP_OUTPUT:]
    exit_code = _EXIT.search(text)
    if exit_code:
        event.ok = int(exit_code.group(1)) == 0
    elif event.tool == "apply_patch":
        event.ok = text.lstrip().startswith("Success")


def _output_text(output) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(o.get("text", "") for o in output if isinstance(o, dict))
    if isinstance(output, dict):
        return str(output.get("output") or output.get("content") or "")
    return ""

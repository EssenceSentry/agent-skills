"""Claude Code transcripts: `projects/<project>/<session>.jsonl` and their subagents."""

import json
import re
from collections import Counter
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

# Record types that hold nothing the archive needs.
_IGNORED = {
    "api-request",
    "api-request-blob",
    "api-request-shape",
    "artifact-autoreact-ledger",
    "artifact-comment-monitor",
    "atis-latch",
    "attachment",
    "bridge-session",
    "file-history-delta",
    "file-history-snapshot",
    "frame-link",
    "isolation-latch",
    "last-prompt",
    "mode",
    "queue-operation",
    "summary",
}

_WRAPPED = re.compile(
    r"<(system-reminder|ide_opened_file|ide_selection|artifact-view-context|command-message"
    r"|local-command-stdout|local-command-stderr)\b[^>]*>.*?</\1>",
    re.S,
)
_SELF_CLOSING = re.compile(r"<artifact-content-authored-by-others\s*/>")
_PASTED = re.compile(r"<pasted_content\b[^>]*>(.*?)</pasted_content>", re.S)
_COMMAND = re.compile(
    r"<command-name>(.*?)</command-name>(?:\s*<command-args>(.*?)</command-args>)?", re.S
)
_SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.S)
_TAG = re.compile(r"</?[\w-]+[^>]*>")
_KEEP_OUTPUT = 4000


def discover(home: Path) -> list[Path]:
    projects = Path(home) / "projects"
    mains = projects.glob("*/*.jsonl")
    subagents = projects.glob("*/*/subagents/**/agent-*.jsonl")
    return sorted([*mains, *subagents])


def parse(path: Path) -> Session:
    path = Path(path)
    # Raw backups add ".zst"; the session id is the name without either suffix.
    stem = path.name.removesuffix(".zst").removesuffix(".jsonl")
    session = Session(provider="claude", session_id=stem, source_path=path)
    meta = {}
    if "subagents" in path.parts:
        session.kind = "subagent"
        session.parent_id = path.parts[path.parts.index("subagents") - 1]
        meta = _read_meta(path.with_name(stem + ".meta.json"))

    titles: dict[str, str] = {}
    pending: dict[str, Event] = {}
    usage: dict[str, dict] = {}
    models: Counter = Counter()
    stamps = []
    for rec in iter_records(path, session.unknown):
        rtype = rec.get("type")
        ts = parse_ts(rec.get("timestamp"))
        if ts:
            stamps.append(ts)
        session.cwd = session.cwd or as_text(rec.get("cwd"))
        session.entrypoint = session.entrypoint or as_text(rec.get("entrypoint"))
        session.branch = as_text(rec.get("gitBranch")) or session.branch
        session.version = as_text(rec.get("version")) or session.version

        if rtype == "user":
            _user(rec, ts, session, pending)
        elif rtype == "assistant":
            _assistant(rec, ts, session, pending, usage, models)
        elif rtype == "system":
            if rec.get("subtype") == "compact_boundary":
                session.events.append(Event("notice", "context compacted", ts))
        elif rtype == "custom-title":
            titles["custom"] = as_text(rec.get("customTitle"))
        elif rtype == "ai-title":
            titles["ai"] = as_text(rec.get("aiTitle"))
        elif rtype == "agent-name":
            titles["agent"] = as_text(rec.get("agentName"))
        elif rtype == "cost-state":
            cost = rec.get("totalCostUSD")
            if isinstance(cost, int | float):
                session.cost_usd = cost
        elif rtype not in _IGNORED:
            session.unknown[str(rtype)] += 1

    first_prompt = next((e.text for e in session.events if e.kind == "user"), "")
    session.title = (
        titles.get("custom")
        or titles.get("ai")
        or as_text(meta.get("description"))
        or titles.get("agent")
        or first_line(first_prompt, 80)
        or None
    )
    session.model = models.most_common(1)[0][0] if models else None
    session.tokens_in = sum(
        _count(u, "input_tokens")
        + _count(u, "cache_creation_input_tokens")
        + _count(u, "cache_read_input_tokens")
        for u in usage.values()
    )
    session.tokens_out = sum(_count(u, "output_tokens") for u in usage.values())
    if stamps:
        session.started, session.ended = min(stamps), max(stamps)
    session.project = project_name(session.cwd)
    return session


def _count(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def _read_meta(meta: Path) -> dict:
    try:
        value = json.loads(meta.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _user(rec, ts, session, pending):
    if rec.get("isMeta"):
        return
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list) and any(_is(i, "tool_result") for i in content):
        for item in content:
            if _is(item, "tool_result"):
                _attach_result(pending.get(item.get("tool_use_id")), item, rec.get("toolUseResult"))
        return
    text = _prompt_text(content)
    if rec.get("isCompactSummary"):
        session.events.append(Event("notice", "context compacted; summary carried forward", ts))
        return
    if rec.get("promptSource") == "system" or text.lstrip().startswith("<task-notification"):
        match = _SUMMARY.search(text)
        note = match.group(1).strip() if match else first_line(_TAG.sub("", text))
        if note:
            session.events.append(Event("notice", note, ts))
        return
    text = _clean(text)
    if text:
        session.events.append(Event("user", text, ts))


def _assistant(rec, ts, session, pending, usage, models):
    msg = rec.get("message") or {}
    model = as_text(msg.get("model"))
    if model and model != "<synthetic>":
        models[model] += 1
    if msg.get("id") and isinstance(msg.get("usage"), dict):
        usage[msg["id"]] = msg["usage"]
    session.effort = as_text(rec.get("effort")) or session.effort
    blocks = msg.get("content") or []
    if rec.get("isApiErrorMessage"):
        text = " ".join(b.get("text", "") for b in blocks if _is(b, "text"))
        session.events.append(Event("notice", first_line(text) or "API error", ts))
        return
    for block in blocks:
        if _is(block, "text") and block.get("text", "").strip():
            session.events.append(Event("assistant", block["text"].strip(), ts))
        elif _is(block, "tool_use"):
            name = as_text(block.get("name")) or "tool"
            event = Event(
                "tool", _summarize(name, block.get("input") or {}, session.cwd), ts, tool=name
            )
            session.events.append(event)
            pending[block.get("id")] = event


def _attach_result(event: Event | None, item: dict, result) -> None:
    if event is None:
        return
    event.ok = not item.get("is_error", False)
    event.output = _result_text(item.get("content"))[-_KEEP_OUTPUT:]
    if not isinstance(result, dict):
        return
    if result.get("agentId"):
        event.child = f"agent-{result['agentId']}"
    patch = result.get("structuredPatch")
    if event.tool in ("Edit", "MultiEdit") and isinstance(patch, list) and patch:
        lines = [ln for hunk in patch if isinstance(hunk, dict) for ln in hunk.get("lines", [])]
        added = sum(ln.startswith("+") for ln in lines)
        removed = sum(ln.startswith("-") for ln in lines)
        event.text = re.sub(r"\+\d+ −\d+$", f"+{added} −{removed}", event.text)


def _summarize(name: str, args: dict, cwd: str | None) -> str:
    def rel(key):
        return code(relative(str(args.get(key) or ""), cwd))

    if name == "Bash":
        return f"ran {code(first_line(str(args.get('command') or '')))}"
    if name == "Edit":
        return f"edited {rel('file_path')} +{_lines(args.get('new_string'))} −{_lines(args.get('old_string'))}"
    if name == "MultiEdit":
        edits = [e for e in args.get("edits") or [] if isinstance(e, dict)]
        added = sum(_lines(e.get("new_string")) for e in edits)
        removed = sum(_lines(e.get("old_string")) for e in edits)
        return f"edited {rel('file_path')} +{added} −{removed}"
    if name == "Write":
        return f"wrote {rel('file_path')} ({_lines(args.get('content'))} lines)"
    if name == "Read":
        return f"read {rel('file_path')}"
    if name == "NotebookEdit":
        return f"edited notebook {rel('notebook_path')}"
    if name == "Grep":
        where = f" in {rel('path')}" if args.get("path") else ""
        return f"searched for {code(str(args.get('pattern') or ''))}{where}"
    if name == "Glob":
        return f"listed {code(str(args.get('pattern') or ''))}"
    if name in ("Agent", "Task"):
        kind = args.get("subagent_type")
        text = f"started subagent “{args.get('description') or 'subagent'}”"
        return f"{text} ({kind})" if kind else text
    if name == "WebFetch":
        return f"fetched {args.get('url', '')}".strip()
    if name == "WebSearch":
        return f"searched the web for “{args.get('query', '')}”"
    if name == "Skill":
        return f"used skill {code(str(args.get('skill') or ''))}"
    if name.startswith("mcp__"):
        _, server, tool = (name.split("__", 2) + ["", ""])[:3]
        return f"called {server} · {tool}"
    return name


def _prompt_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        if _is(item, "text"):
            parts.append(item.get("text", ""))
        elif _is(item, "image"):
            parts.append("[image]")
    return "\n\n".join(parts)


def _clean(text: str) -> str:
    text = _COMMAND.sub(
        lambda m: f"/{m.group(1).strip().lstrip('/')} {(m.group(2) or '').strip()}", text
    )
    text = _PASTED.sub(
        lambda m: f"[pasted text, {len(m.group(1).strip().splitlines())} lines]", text
    )
    text = _WRAPPED.sub("", text)
    text = _SELF_CLOSING.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(i.get("text", "") for i in content if _is(i, "text"))
    return ""


def _lines(text) -> int:
    return len(text.splitlines()) if isinstance(text, str) and text else 0


def _is(item, kind: str) -> bool:
    return isinstance(item, dict) and item.get("type") == kind

"""ax over MCP: find, recall and here for agents, on stdio with no dependencies.

MCP's stdio transport is newline-delimited JSON-RPC 2.0. The server answers
`initialize`, `ping`, `tools/list` and `tools/call`, ignores notifications, and
returns a tool's failure as a result marked `isError`, so the agent sees why.
"""

import json
import os
import sys

from ax import find, handles, recall

VERSION = "2025-06-18"
FRESH = 600  # seconds: this server's conversation id counts only if written to lately

TOOLS = [
    {
        "name": "find",
        "description": (
            "Search the user's past Claude Code and Codex conversations, both tools' "
            "memories, their vault notes and the code in their repositories, in one go. "
            "Use it before redoing an investigation or a decision, for 'have we done this "
            "before', 'what did we decide about X' and 'where is X in the code'. "
            "Conversation hits carry a handle (ax:xxxxxxxx) to pass to recall. Confirm "
            "anything you rely on against the current code or data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(find.SOURCES)},
                    "description": "Where to look; default conversations, memories, notes, code.",
                },
                "project": {"type": "string", "description": "Only this project (repo name)."},
                "provider": {"type": "string", "enum": ["claude", "codex"]},
                "since": {"type": "string", "description": "Only conversations since YYYY-MM-DD."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recall",
        "description": (
            "Bring an earlier conversation into this one by its handle (ax:xxxxxxxx), id or "
            "note name: an outline of the user's turns, where it ended and the files it "
            "changed, with the path of the full note. Pass `task` to get only what that task "
            "needs, read by a model; `card` for a cached summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Handle, session id or note name."},
                "task": {"type": "string", "description": "Bring back only what this needs."},
                "card": {"type": "boolean", "description": "Add the cached summary card."},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "here",
        "description": (
            "This conversation's handle, for the user to build on it from another "
            "conversation. If it fails, run `ax here` in a shell instead."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class ToolError(Exception):
    pass


def _find(config, args: dict, env) -> str:
    if not find.ready(config):
        raise ToolError("no search index yet; the user needs to run `ax index setup`")
    try:
        hits = find.find(
            config, str(args["query"]), sources=args.get("sources") or find.DEFAULT,
            limit=int(args.get("limit") or 10), project=args.get("project"),
            provider=args.get("provider"), since=args.get("since"),
        )  # fmt: skip
    except find.FindError as exc:
        raise ToolError(str(exc)) from None
    return find.text(hits)


def _recall(config, args: dict, env) -> str:
    from ax import learn

    try:
        row = handles.resolve(config, str(args["ref"]))
    except (handles.NotFound, handles.Ambiguous) as exc:
        raise ToolError(str(exc)) from None
    if args.get("task"):
        text = recall.focus(config, row, str(args["task"]), model=learn.claude_model("sonnet"))
    elif args.get("card"):
        text = recall.card(config, row, model=learn.claude_model("haiku"))
    else:
        text = recall.outline(config, row)
    recall.record(config, row, env, fresh=FRESH)
    return text


def _here(config, args: dict, env) -> str:
    found = handles.current(config, env, fresh=FRESH)
    if not found:
        raise ToolError("this server can't see which conversation it serves; run `ax here`")
    return handles.tag(found[1])


_CALLS = {"find": _find, "recall": _recall, "here": _here}


def _call(config, params: dict, env) -> dict:
    name, args = params.get("name"), params.get("arguments") or {}
    try:
        if name not in _CALLS:
            raise ToolError(f"no tool {name!r}")
        text, failed = _CALLS[name](config, args, env), False
    except (ToolError, KeyError, ValueError, TypeError) as exc:
        text, failed = str(exc) or type(exc).__name__, True
    return {"content": [{"type": "text", "text": text}], "isError": failed}


def _answer(config, message: dict, env) -> dict | None:
    method, i = message.get("method"), message.get("id")
    if i is None:
        return None  # a notification
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion") or VERSION
        result = {"protocolVersion": asked, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "ax", "version": "1"}}  # fmt: skip
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = _call(config, message.get("params") or {}, env)
    else:
        return {"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": f"no {method}"}}
    return {"jsonrpc": "2.0", "id": i, "result": result}


def serve(config, *, stdin=None, stdout=None, env=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    env = os.environ if env is None else env
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
        else:
            reply = _answer(config, message, env) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()

"""Minimal Claude transcripts for tests that need conversations of their own."""

import json
from datetime import datetime, timedelta


def claude_chat(env, session_id, *turns, day="2026-10-21", cwd="/Users/me/Repos/demo"):
    """Write a Claude Code transcript of (role, text) turns and return its path."""
    folder = env.claude_home / "projects" / "-Users-me-Repos-demo"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for i, (role, text) in enumerate(turns):
        record = {"cwd": cwd, "sessionId": session_id, "version": "2.1.283",
                  "entrypoint": "claude-desktop", "gitBranch": "main", "uuid": f"{session_id[:6]}{i}",
                  "timestamp": _at(day, i), "type": role}  # fmt: skip
        if role == "user":
            record |= {"message": {"role": "user", "content": text}, "turnOrigin": "human"}
        elif role == "edit":  # an Edit tool call on the file `text`
            use = {"type": "tool_use", "id": f"t{i}", "name": "Edit",
                   "input": {"file_path": text, "old_string": "a", "new_string": "b"}}  # fmt: skip
            record |= {"type": "assistant", "message": {
                "id": f"m{i}", "role": "assistant", "model": "claude-opus-5-5", "content": [use],
                "usage": {"input_tokens": 1, "output_tokens": 1}}}  # fmt: skip
        else:
            record["message"] = {"id": f"m{i}", "role": "assistant", "model": "claude-opus-5-5",
                                 "content": [{"type": "text", "text": text}],
                                 "usage": {"input_tokens": 1, "output_tokens": 1}}  # fmt: skip
        records.append(record)
    path = folder / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _at(day: str, minute: int) -> str:
    return (datetime.fromisoformat(f"{day}T12:00:00") + timedelta(minutes=minute)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

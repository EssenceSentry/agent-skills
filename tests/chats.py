"""Minimal Claude transcripts for tests that need conversations of their own."""

import json


def claude_chat(env, session_id, *turns, day="2026-10-21", cwd="/Users/me/Repos/demo"):
    """Write a Claude Code transcript of (role, text) turns and return its path."""
    folder = env.claude_home / "projects" / "-Users-me-Repos-demo"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for i, (role, text) in enumerate(turns):
        record = {"cwd": cwd, "sessionId": session_id, "version": "2.1.283",
                  "entrypoint": "claude-desktop", "gitBranch": "main", "uuid": f"{session_id[:6]}{i}",
                  "timestamp": f"{day}T12:{i:02d}:00.000Z", "type": role}  # fmt: skip
        if role == "user":
            record |= {"message": {"role": "user", "content": text}, "turnOrigin": "human"}
        else:
            record["message"] = {"id": f"m{i}", "role": "assistant", "model": "claude-opus-5-5",
                                 "content": [{"type": "text", "text": text}],
                                 "usage": {"input_tokens": 1, "output_tokens": 1}}  # fmt: skip
        records.append(record)
    path = folder / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path

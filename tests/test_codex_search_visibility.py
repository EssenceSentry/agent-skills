import json
from uuid import uuid4

import zstandard

from ax import catalog


def rollout(config, sid, source, *, compressed=False):
    folder = config.codex_home / ("archived_sessions" if compressed else "sessions")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-test-{sid}.jsonl"
    data = (
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"id": sid, "thread_source": "user", "source": source},
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Distinctive visibility fixture"}],
                },
            }
        )
    ).encode()
    if compressed:
        path = path.with_suffix(".jsonl.zst")
        data = zstandard.ZstdCompressor().compress(data)
    path.write_bytes(data)
    return path


def test_previously_indexed_and_new_workers_are_excluded_from_search_and_handoff(config):
    hidden, nested, visible = [str(uuid4()) for _ in range(3)]
    archived = rollout(config, hidden, "exec", compressed=True)
    original = archived.read_bytes()
    rollout(config, nested, {"subagent": {"thread_spawn": {}}})
    rollout(config, visible, "vscode")
    key = "codex:" + hidden
    stat = archived.stat()
    with catalog.connect(config) as db:
        db.execute(
            "INSERT INTO indexed_files VALUES(?,?,?)",
            (str(archived), stat.st_size, stat.st_mtime_ns),
        )
        db.execute(
            "INSERT INTO conversations(key,id,provider,source) VALUES(?,?,?,?)",
            (key, hidden, "codex", str(archived)),
        )
        db.execute(
            "INSERT INTO dialogue(key,role,text) VALUES(?,?,?)",
            (key, "assistant", "hiddenworkeronly"),
        )
    assert catalog.search(config, "hiddenworkeronly")
    assert catalog.refresh(config)["errors"] == []
    assert {r["id"] for r in catalog.search(config, "visibility")} == {visible}
    assert catalog.search(config, "hiddenworkeronly") == []
    assert catalog.handoff(config, "hiddenworkeronly", "codex:fixture")["sources"] == []
    assert catalog.refresh(config)["updated"] == 0
    assert archived.read_bytes() == original


def test_reclassified_transcript_replaces_old_hits_atomically(config):
    sid = str(uuid4())
    rollout(config, sid, "cli")
    catalog.refresh(config)
    assert catalog.search(config, "visibility")
    rollout(config, sid, "exec")
    catalog.refresh(config)
    assert catalog.search(config, "visibility") == []
    rollout(config, sid, "vscode")
    catalog.refresh(config)
    assert {r["id"] for r in catalog.search(config, "visibility")} == {sid}

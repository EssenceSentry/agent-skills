import json

from ax import live_sessions


def records(env, rows, sid="audit-history"):
    path = env.claude_home / "projects" / "audit" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    live_sessions.clear_cache()
    return path


def test_backwards_pages_cover_history_beyond_three_hundred_events(env):
    rows = [
        {"type": "user", "uuid": f"message-{i}", "message": {"content": f"Message {i}"}}
        for i in range(725)
    ]
    records(env, rows)
    last = live_sessions.transcript(env.config, "claude", "audit-history", include_tools=True)
    assert len(last["events"]) == 300 and last["earlier"] == 425
    older = live_sessions.transcript(
        env.config, "claude", "audit-history", before=last["first"], include_tools=True
    )
    first = live_sessions.transcript(
        env.config, "claude", "audit-history", before=older["first"], include_tools=True
    )
    indexes = [event["i"] for page in (first, older, last) for event in page["events"]]
    assert indexes == list(range(725))
    found = live_sessions.transcript(
        env.config, "claude", "audit-history", query="Message 3", include_tools=True
    )
    assert any(event["text"] == "Message 3" for event in found["events"])


def test_cursor_detects_rewritten_history(env):
    path = records(env, [{"type": "user", "uuid": "one", "message": {"content": "Old"}}])
    old = live_sessions.transcript(env.config, "claude", "audit-history")
    path.write_text(
        json.dumps({"type": "user", "uuid": "two", "message": {"content": "Replacement history"}})
        + "\n"
    )
    page = live_sessions.transcript(env.config, "claude", "audit-history", cursor=old["cursor"])
    assert page["reset"] and page["events"][0]["text"] == "Replacement history"


def test_completed_tool_output_is_available_in_full_pages(env):
    output = "EARLY_EVIDENCE" + "x" * 40000 + "LATE_EVIDENCE"
    records(
        env,
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "id": "tool",
                            "input": {"command": "pwd"},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "tool", "content": output}]
                },
            },
        ],
    )
    page = live_sessions.transcript(env.config, "claude", "audit-history", include_tools=True)
    assert page["events"][0]["kind"] == "tool"
    text, offset = "", 0
    while offset is not None:
        result = live_sessions.tool_output(env.config, "claude", "audit-history", 0, offset)
        text += result["text"]
        offset = result["next"]
    assert text == output


def test_full_history_search_finds_late_tool_evidence_and_paginates_matches(env):
    output = "x" * 30000 + "LATE_EVIDENCE"
    rows = [
        {"type": "user", "uuid": f"message-{i}", "message": {"content": f"Match {i}"}}
        for i in range(400)
    ]
    rows += [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Bash", "id": "tool", "input": {"command": "pwd"}}
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "tool", "content": output}]
            },
        },
    ]
    records(env, rows)
    found = live_sessions.transcript(
        env.config, "claude", "audit-history", query="LATE_EVIDENCE", include_tools=True
    )
    assert len(found["events"]) == 1 and "LATE_EVIDENCE" in found["events"][0]["output"]
    matches = live_sessions.transcript(
        env.config, "claude", "audit-history", query="Match", include_tools=True
    )
    assert matches["earlier"] == 100
    earlier = live_sessions.transcript(
        env.config,
        "claude",
        "audit-history",
        query="Match",
        include_tools=True,
        before=matches["first"],
    )
    assert len(earlier["events"]) == 100

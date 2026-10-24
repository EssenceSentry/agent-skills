"""Write the synthetic Claude Code and Codex transcripts used by the tests.

Every value here is invented. The record shapes follow Claude Code 2.1.283 and
Codex 0.163.0 as observed in October 2026. Run this file to regenerate the fixtures.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent
CWD = "/Users/me/Repos/demo"

CLAUDE_SESSION = "11111111-1111-4111-8111-111111111111"
CLAUDE_AGENT = "a1b2c3d4e5f6a7b8c"
CODEX_SESSION = "22222222-2222-4222-8222-222222222222"
CODEX_SUBAGENT = "33333333-3333-4333-8333-333333333333"
CODEX_GUARDIAN = "44444444-4444-4444-8444-444444444444"
CODEX_FORK = "55555555-5555-4555-8555-555555555555"


def claude_base(uuid, ts, **extra):
    return {
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": CWD,
        "sessionId": CLAUDE_SESSION,
        "version": "2.1.283",
        "gitBranch": "main",
        "entrypoint": "claude-desktop",
        "uuid": uuid,
        "timestamp": ts,
        **extra,
    }


def claude_user(uuid, ts, content, **extra):
    return claude_base(uuid, ts, type="user", message={"role": "user", "content": content}, **extra)


def claude_assistant(uuid, ts, msg_id, block, usage=None, **extra):
    message = {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [block],
        "stop_reason": None,
        "usage": usage or {"input_tokens": 0, "output_tokens": 0},
    }
    return claude_base(
        uuid,
        ts,
        type="assistant",
        message=message,
        requestId="req_" + msg_id,
        effort="xhigh",
        **extra,
    )


def tool_result(uuid, ts, tool_use_id, content, tool_use_result, is_error=False):
    item = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        item["is_error"] = True
    return claude_user(uuid, ts, [item], toolUseResult=tool_use_result)


USAGE_1 = {
    "input_tokens": 100,
    "cache_creation_input_tokens": 1000,
    "cache_read_input_tokens": 5000,
    "output_tokens": 50,
}
USAGE_2 = {
    "input_tokens": 20,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 6000,
    "output_tokens": 30,
}


def claude_main():
    t = "2026-10-20T12:{:02d}:00.000Z".format
    return [
        {
            "type": "ai-title",
            "aiTitle": "Add retries to the fetch helper",
            "sessionId": CLAUDE_SESSION,
        },
        claude_user(
            "u1",
            t(0),
            "Add a retry to the fetch helper\n\n<system-reminder>\nInjected context.\n</system-reminder>",
            promptSource="sdk",
            turnOrigin="human",
            promptId="p1",
        ),
        claude_user("u1m", t(0), "Caveat: injected meta message", isMeta=True),
        claude_assistant(
            "a1", t(1), "msg_1", {"type": "thinking", "thinking": "Private reasoning."}, USAGE_1
        ),
        claude_assistant(
            "a2", t(1), "msg_1", {"type": "text", "text": "I'll read the helper first."}, USAGE_1
        ),
        claude_assistant(
            "a3",
            t(1),
            "msg_1",
            {
                "type": "tool_use",
                "id": "toolu_read",
                "name": "Read",
                "input": {"file_path": CWD + "/src/fetch.py"},
            },
            USAGE_1,
        ),
        tool_result(
            "r1",
            t(2),
            "toolu_read",
            "1\tdef fetch(url):\n2\t    return get(url)",
            {
                "type": "text",
                "file": {"filePath": CWD + "/src/fetch.py", "content": "def fetch(url): ..."},
            },
        ),
        claude_assistant(
            "a4",
            t(3),
            "msg_2",
            {
                "type": "tool_use",
                "id": "toolu_edit",
                "name": "Edit",
                "input": {
                    "file_path": CWD + "/src/fetch.py",
                    "old_string": "    return get(url)",
                    "new_string": "    for _ in range(3):\n        return get(url)",
                },
            },
            USAGE_2,
        ),
        tool_result(
            "r2",
            t(3),
            "toolu_edit",
            "The file has been updated.",
            {
                "filePath": CWD + "/src/fetch.py",
                "structuredPatch": [
                    {
                        "oldStart": 2,
                        "oldLines": 1,
                        "newStart": 2,
                        "newLines": 2,
                        "lines": [
                            "-    return get(url)",
                            "+    for _ in range(3):",
                            "+        return get(url)",
                            "+    # retried up to three times",
                        ],
                    }
                ],
            },
        ),
        claude_assistant(
            "a5",
            t(4),
            "msg_2",
            {
                "type": "tool_use",
                "id": "toolu_bash_ok",
                "name": "Bash",
                "input": {"command": "uv run pytest -q\n# second line", "description": "Run tests"},
            },
            USAGE_2,
        ),
        tool_result(
            "r3",
            t(4),
            "toolu_bash_ok",
            "3 passed",
            {"stdout": "3 passed", "stderr": "", "interrupted": False, "isImage": False},
        ),
        claude_assistant(
            "a6",
            t(5),
            "msg_2",
            {
                "type": "tool_use",
                "id": "toolu_bash_bad",
                "name": "Bash",
                "input": {"command": "make lint"},
            },
            USAGE_2,
        ),
        tool_result(
            "r4",
            t(5),
            "toolu_bash_bad",
            "Exit code 2\nlint: 1 error",
            {"stdout": "", "stderr": "lint: 1 error", "interrupted": False, "isImage": False},
            is_error=True,
        ),
        claude_assistant(
            "a7",
            t(6),
            "msg_2",
            {
                "type": "tool_use",
                "id": "toolu_agent",
                "name": "Agent",
                "input": {
                    "description": "Review the retry change",
                    "subagent_type": "general-purpose",
                    "prompt": "Review src/fetch.py.",
                },
            },
            USAGE_2,
        ),
        tool_result(
            "r5",
            t(8),
            "toolu_agent",
            [{"type": "text", "text": "Looks good."}],
            {
                "agentId": CLAUDE_AGENT,
                "status": "completed",
                "description": "Review the retry change",
            },
        ),
        claude_assistant(
            "a8",
            t(9),
            "msg_2",
            {"type": "text", "text": "Done. Here is the snippet:\n\n```python\nfor _ in range(3):"},
            USAGE_2,
        ),
        claude_user(
            "u2",
            t(10),
            "<task-notification>\n<summary>Background build finished</summary>\n</task-notification>",
            promptSource="system",
            turnOrigin="task_notification",
        ),
        claude_user(
            "u3",
            t(11),
            "Store this key: AKIAABCDEFGHIJKLMNOP for later",
            promptSource="sdk",
            turnOrigin="human",
        ),
        {"type": "future-thing", "sessionId": CLAUDE_SESSION, "detail": 1},
        "THIS IS NOT JSON",
        {
            "type": "cost-state",
            "sessionId": CLAUDE_SESSION,
            "totalCostUSD": 0.42,
            "totalLinesAdded": 2,
        },
        {
            "type": "custom-title",
            "customTitle": "Retry for fetch helper",
            "sessionId": CLAUDE_SESSION,
        },
        {"type": "last-prompt", "lastPrompt": "Store this key", "sessionId": CLAUDE_SESSION},
    ]


def claude_subagent():
    t = "2026-10-20T12:{:02d}:30.000Z".format
    extra = {"isSidechain": True, "agentId": CLAUDE_AGENT}
    records = [
        claude_user("s1", t(6), "Review src/fetch.py.", **extra),
        claude_assistant("s2", t(7), "msg_s1", {"type": "text", "text": "Looks good."}, **extra),
    ]
    return records


def codex_meta(session_id, ts, thread_source, source, **extra):
    return {
        "timestamp": ts,
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "session_id": session_id,
            "timestamp": ts,
            "cwd": CWD,
            "originator": "codex_vscode",
            "cli_version": "0.163.0",
            "source": source,
            "thread_source": thread_source,
            "model_provider": "openai",
            "base_instructions": {"text": "You are Codex."},
            "git": {
                "branch": "main",
                "commit_hash": "0000000",
                "repository_url": "https://github.com/me/demo.git",
            },
            **extra,
        },
    }


def numbered(records):
    """Codex 0.162+ numbers every record; subagents use it to mark copied history."""
    for i, record in enumerate(records):
        record["ordinal"] = i
    return records


def codex_item(ts, payload_type, **payload):
    return {"timestamp": ts, "type": "response_item", "payload": {"type": payload_type, **payload}}


def codex_event(ts, event_type, **payload):
    return {"timestamp": ts, "type": "event_msg", "payload": {"type": event_type, **payload}}


def codex_text(role, text, phase=None):
    kind = "output_text" if role == "assistant" else "input_text"
    payload = {"role": role, "content": [{"type": kind, "text": text}]}
    if phase:
        payload["phase"] = phase
    return payload


PATCH = """*** Begin Patch
*** Update File: src/fetch.py
@@
-    return get(url)
+    for _ in range(3):
+        return get(url)
*** End Patch"""


def codex_main():
    t = "2026-10-20T13:{:02d}:00.000Z".format
    return [
        codex_meta(CODEX_SESSION, t(0), "user", "vscode"),
        {
            "timestamp": t(0),
            "type": "turn_context",
            "payload": {
                "cwd": CWD,
                "model": "gpt-5.5",
                "effort": "high",
                "approval_policy": "never",
            },
        },
        codex_item(t(0), "message", **codex_text("developer", "Developer instructions.")),
        codex_item(
            t(0),
            "message",
            **codex_text("user", "<environment_context>\n<cwd>x</cwd>\n</environment_context>"),
        ),
        codex_item(
            t(0),
            "message",
            **codex_text("user", "# AGENTS.md instructions for /Users/me/Repos/demo\n\nRules."),
        ),
        codex_item(
            t(1),
            "message",
            **codex_text(
                "user",
                "# Context from my IDE setup:\n\n## Active file: src/fetch.py\n\n## My request for Codex:\nMake the tests pass",
            ),
        ),
        codex_item(t(1), "reasoning", summary=[], content=None, encrypted_content="opaque"),
        codex_item(
            t(2), "message", **codex_text("assistant", "Running the tests first.", "commentary")
        ),
        codex_item(
            t(2),
            "function_call",
            name="exec_command",
            call_id="call_1",
            arguments=json.dumps({"cmd": "uv run pytest -q", "workdir": CWD}),
        ),
        codex_item(
            t(3),
            "function_call_output",
            call_id="call_1",
            output="Process exited with code 1\nOutput:\n1 failed",
        ),
        codex_item(
            t(4),
            "custom_tool_call",
            name="apply_patch",
            call_id="call_2",
            input=PATCH,
            status="completed",
        ),
        codex_item(
            t(4),
            "custom_tool_call_output",
            call_id="call_2",
            output=[
                {
                    "type": "input_text",
                    "text": "Success. Updated the following files:\nM src/fetch.py",
                }
            ],
        ),
        codex_item(t(5), "function_call", name="write_stdin", call_id="call_3", arguments="{}"),
        codex_item(t(5), "function_call_output", call_id="call_3", output="ok"),
        codex_event(
            t(6),
            "token_count",
            info={
                "total_token_usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 200,
                    "output_tokens": 300,
                },
                "last_token_usage": {"input_tokens": 10, "output_tokens": 3},
                "model_context_window": 400000,
            },
            rate_limits={
                "primary": {"used_percent": 12.0, "window_minutes": 10080, "resets_at": 1793000000}
            },
        ),
        codex_item(
            t(7),
            "message",
            **codex_text("assistant", "Fixed the retry; tests pass.", "final_answer"),
        ),
        codex_event(t(8), "turn_aborted", reason="interrupted", turn_id="turn_2"),
        {
            "timestamp": t(9),
            "type": "compacted",
            "payload": {"message": "", "replacement_history": []},
        },
        codex_item(t(9), "compaction", encrypted_content="opaque"),
        codex_item(t(9), "additional_tools", role="developer", tools=[]),
        {"timestamp": t(9), "type": "inter_agent_communication_metadata", "payload": {}},
        {"timestamp": t(9), "type": "future_record", "payload": {}},
        codex_item(t(9), "future_item", detail=1),
    ]


def codex_subagent():
    t = "2026-10-20T13:{:02d}:30.000Z".format
    source = {
        "subagent": {
            "thread_spawn": {
                "parent_thread_id": CODEX_SESSION,
                "depth": 1,
                "agent_path": "reviewer",
                "agent_nickname": "Reviewer",
                "agent_role": None,
            }
        }
    }
    return numbered(
        [
            # The child's own metadata comes first, then a copy of the parent's
            # metadata and history up to `subagent_history_start_ordinal`.
            codex_meta(CODEX_SUBAGENT, t(5), "subagent", source, subagent_history_start_ordinal=3),
            codex_meta(CODEX_SESSION, t(0), "user", "vscode"),
            codex_item(t(1), "message", **codex_text("user", "Make the tests pass")),
            codex_item(t(5), "message", **codex_text("user", "Check the retry loop.")),
            codex_item(
                t(5),
                "agent_message",
                author="/root",
                recipient="/root/reviewer",
                content=[{"type": "input_text", "text": "Please review the retry loop."}],
            ),
            codex_item(
                t(6),
                "message",
                **codex_text("assistant", "The loop returns early.", "final_answer"),
            ),
        ]
    )


def codex_guardian():
    t = "2026-10-20T13:{:02d}:45.000Z".format
    return [
        codex_meta(CODEX_GUARDIAN, t(4), "guardian_review", {"subagent": {"other": "guardian"}}),
        codex_item(t(4), "message", **codex_text("user", "Approve `rm -rf build`?")),
        codex_item(t(4), "message", **codex_text("assistant", "Approved.", "final_answer")),
    ]


def codex_fork():
    """A thread forked from another: its file name carries both ids, the fork's last."""
    t = "2026-10-20T14:{:02d}:00.000Z".format
    return [
        codex_meta(CODEX_SESSION, t(0), "user", "vscode"),
        codex_item(t(1), "message", **codex_text("user", "Try a different retry strategy")),
        codex_item(t(2), "message", **codex_text("assistant", "Using exponential backoff.")),
    ]


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    project = ROOT / "claude" / "projects" / "-Users-me-Repos-demo"
    write_jsonl(project / f"{CLAUDE_SESSION}.jsonl", claude_main())
    subagents = project / CLAUDE_SESSION / "subagents"
    write_jsonl(subagents / f"agent-{CLAUDE_AGENT}.jsonl", claude_subagent())
    meta = {
        "agentType": "general-purpose",
        "description": "Review the retry change",
        "spawnDepth": 1,
        "toolUseId": "toolu_agent",
    }
    (subagents / f"agent-{CLAUDE_AGENT}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    day = ROOT / "codex" / "sessions" / "2026" / "10" / "20"
    write_jsonl(day / f"rollout-2026-10-20T10-00-00-{CODEX_SESSION}.jsonl", codex_main())
    write_jsonl(day / f"rollout-2026-10-20T10-05-00-{CODEX_SUBAGENT}.jsonl", codex_subagent())
    write_jsonl(day / f"rollout-2026-10-20T10-06-00-{CODEX_GUARDIAN}.jsonl", codex_guardian())
    write_jsonl(
        day / f"rollout-2026-10-20T11-00-00-{CODEX_SESSION}_{CODEX_FORK}.jsonl", codex_fork()
    )
    write_jsonl(
        ROOT / "codex" / "session_index.jsonl",
        [
            {
                "id": CODEX_SESSION,
                "thread_name": "Fix flaky fetch tests",
                "updated_at": "2026-10-20T13:09:00Z",
            }
        ],
    )


if __name__ == "__main__":
    main()

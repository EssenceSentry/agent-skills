"""Writing to sessions from the ax app: Codex through its app-server or the app's queue,
Claude through a headless process once nothing else holds the session, streamed replies,
approvals as answers, and the same at once through a shared link."""

import json
import os
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

from ax import app, chat, live_sessions, serve

FAKE_CODEX = r"""
import json, sys
log = open(sys.argv[1], "a")
def say(message):
    print(json.dumps(message), flush=True)
for line in sys.stdin:
    message = json.loads(line)
    log.write(line); log.flush()
    method = message.get("method")
    if "id" in message and method is None:
        # the client's answer to our approval request: finish the turn
        say({"method": "item/agentMessage/delta", "params": {"delta": " Done."}})
        say({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
        continue
    if method == "initialize":
        say({"id": message["id"], "result": {"userAgent": "fake"}})
    elif method == "thread/resume":
        say({"id": message["id"], "result": {
            "thread": {"id": message["params"]["threadId"]}, "model": "gpt-6-astra",
            "reasoningEffort": "xhigh", "approvalsReviewer": "auto_review",
            "collaborationMode": None}})
    elif method == "model/list":
        say({"id": message["id"], "result": {"data": [
            {"model": "gpt-6-astra", "displayName": "GPT-6-Astra", "isDefault": True,
             "defaultReasoningEffort": "medium", "hidden": False,
             "supportedReasoningEfforts": [{"reasoningEffort": e} for e in ("low", "medium", "high", "xhigh")]},
            {"model": "gpt-6-sol", "displayName": "GPT-6-Sol", "isDefault": False,
             "defaultReasoningEffort": "low", "hidden": False,
             "supportedReasoningEfforts": [{"reasoningEffort": e} for e in ("low", "high")]},
            {"model": "old-secret", "displayName": "Hidden", "hidden": True,
             "supportedReasoningEfforts": []}]}})
    elif method == "thread/goal/get":
        say({"id": message["id"], "result": {"goal": None}})
    elif method == "thread/goal/set":
        goal = {"threadId": message["params"]["threadId"], "objective": message["params"]["objective"],
                "status": "active", "tokenBudget": message["params"].get("tokenBudget"),
                "tokensUsed": 0, "timeUsedSeconds": 0, "createdAt": 1, "updatedAt": 1}
        say({"id": message["id"], "result": {"goal": goal}})
        say({"method": "thread/goal/updated", "params": {"threadId": goal["threadId"], "goal": {
            **goal, "tokensUsed": 1200, "timeUsedSeconds": 90}}})
    elif method == "thread/goal/clear":
        say({"id": message["id"], "result": {"cleared": True}})
        say({"method": "thread/goal/cleared", "params": {"threadId": message["params"]["threadId"]}})
    elif method == "thread/start":
        say({"id": message["id"], "result": {"thread": {"id": "t-new"}}})
    elif method == "turn/start":
        say({"id": message["id"], "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        say({"method": "turn/started", "params": {"turn": {"id": "turn-1"}}})
        say({"method": "item/agentMessage/delta", "params": {"delta": "Running"}})
        say({"method": "item/agentMessage/delta", "params": {"delta": " the tests."}})
        text = message["params"]["input"][0]["text"]
        if "plan steps" in text:
            say({"method": "turn/plan/updated", "params": {
                "threadId": "t", "turnId": "turn-1", "explanation": "Two steps",
                "plan": [{"step": "Read", "status": "completed"},
                         {"step": "Fix", "status": "inProgress"}]}})
        if "ask me" in text:
            say({"id": 901, "method": "item/tool/requestUserInput", "params": {
                "threadId": "t", "turnId": "turn-1", "itemId": "c9", "isBlocking": True,
                "questions": [{"id": "scope", "header": "Scope", "question": "Which?",
                               "options": [{"label": "A", "description": "a"}],
                               "isOther": True, "isSecret": False}]}})
        elif "approve" in text:
            say({"id": 900, "method": "item/commandExecution/requestApproval",
                 "params": {"threadId": "t", "turnId": "turn-1", "itemId": "i",
                            "command": "rm -rf build", "reason": "clean the build"}})
        elif "slowly" in text:
            pass  # it works on until it is interrupted
        else:
            say({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
    elif method == "turn/steer":
        say({"id": message["id"], "result": {"turnId": message["params"]["expectedTurnId"]}})
    elif method == "turn/interrupt":
        say({"id": message["id"], "result": {}})
        say({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "interrupted"}}})
    elif "id" in message:
        say({"id": message["id"], "result": {}})
"""

FAKE_CLAUDE = r"""
import json, sys
log = open(sys.argv[1], "a")
log.write(json.dumps(sys.argv[2:]) + "\n"); log.flush()
def say(message):
    print(json.dumps(message), flush=True)
def delta(text):
    say({"type": "stream_event", "event": {"type": "content_block_delta",
                                           "delta": {"type": "text_delta", "text": text}}})
waiting, slow, queued = False, False, []
def turn(text):
    global waiting, slow
    say({"type": "system", "subtype": "init"})
    delta("Looking")
    delta(" at it.")
    if "slowly" in text:
        slow = True  # it works on until it is interrupted
    elif "approve" in text:
        waiting = True
        say({"type": "control_request", "request_id": "perm-1", "request": {
            "subtype": "can_use_tool", "tool_name": "Bash",
            "input": {"command": "rm -rf build"}}})
    elif "ask me" in text:
        waiting = True
        say({"type": "control_request", "request_id": "ask-1", "request": {
            "subtype": "can_use_tool", "tool_name": "AskUserQuestion", "tool_use_id": "tu-1",
            "input": {"questions": [
                {"question": "Which format?", "header": "Format", "multiSelect": False,
                 "options": [{"label": "Summary", "description": "Brief"},
                             {"label": "Detailed", "description": "Full"}]},
                {"question": "Which sections?", "header": "Sections", "multiSelect": True,
                 "options": [{"label": "Intro", "description": ""},
                             {"label": "End", "description": ""}]}]}}})
    elif "plan please" in text:
        waiting = True
        say({"type": "control_request", "request_id": "plan-1", "request": {
            "subtype": "can_use_tool", "tool_name": "ExitPlanMode",
            "input": {"plan": "# Plan\n1. Do it"}}})
    else:
        say({"type": "result", "subtype": "success"})
for line in sys.stdin:
    message = json.loads(line)
    log.write(line); log.flush()
    if message.get("type") == "control_request":
        subtype = message["request"]["subtype"]
        answer = {}
        if subtype == "initialize":
            answer = {"current_permission_mode": "default", "models": [
                {"value": "default", "displayName": "Default (recommended)",
                 "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
                {"value": "opus", "displayName": "Opus 5.5",
                 "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
                {"value": "haiku", "displayName": "Haiku 5.5", "supportedEffortLevels": []}]}
        elif subtype == "set_permission_mode":
            answer = {"mode": message["request"]["mode"]}
        elif subtype == "set_model":
            answer = {"model": message["request"]["model"]}
        say({"type": "control_response", "response": {"subtype": "success",
                                                      "request_id": message["request_id"],
                                                      "response": answer}})
        if subtype == "set_permission_mode":
            say({"type": "system", "subtype": "status", "permissionMode": answer["mode"]})
        if subtype == "interrupt":
            say({"type": "result", "subtype": "error_during_execution"})
            slow = False
            while queued and not waiting and not slow:
                turn(queued.pop(0))
    elif message.get("type") == "user":
        text = " ".join(b.get("text", "") for b in message["message"]["content"])
        if waiting or slow:  # as Claude Code does: the message waits, then runs as its own turn
            queued.append(text)
        else:
            turn(text)
    elif message.get("type") == "control_response":
        if message["response"]["request_id"] == "plan-1" and \
                message["response"]["response"]["behavior"] == "allow":
            say({"type": "system", "subtype": "status", "permissionMode": "default"})
        waiting = False
        say({"type": "result", "subtype": "success"})
        while queued and not waiting:
            turn(queued.pop(0))
"""


def script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body)
    return path


def until(check, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.02)
    raise AssertionError("timed out")


def logged(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith("{")]


@pytest.fixture
def chats(env, tmp_path, monkeypatch):
    """A fresh registry whose drivers run the fake tools, and no tool holding anything."""
    codex_log, claude_log = tmp_path / "codex.log", tmp_path / "claude.log"
    codex = script(tmp_path, "codex.py", FAKE_CODEX)
    claude = script(tmp_path, "claude.py", FAKE_CLAUDE)
    registry = chat.Chats(
        codex_command=lambda: [sys.executable, str(codex), str(codex_log)],
        claude_command=lambda sid, new=False, effort=None: [
            sys.executable,
            str(claude),
            str(claude_log),
            sid,
            "new" if new else "resume",
            effort or "-",
        ],
    )
    monkeypatch.setattr(chat, "CHATS", registry)
    monkeypatch.setattr(chat, "codex_open_in_app", lambda config, tid: False)
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: False)
    monkeypatch.setattr(chat, "_claude_agents", lambda: {})  # no Claude process but ax's
    yield registry, codex_log, claude_log
    registry.close_all()


# Codex


def test_a_codex_thread_ax_holds_streams_its_reply_and_finishes(env, chats):
    registry, codex_log, _ = chats
    said = chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                                 "text": "Run the tests", "cwd": "/repo"})  # fmt: skip
    assert said["ok"] and said["via"] == "ax"
    live = until(lambda: (s := chat.state(env.config, "codex", "t-1")) and not s["busy"] and s)
    assert live["holder"] == "ax" and live["partial"] == ""
    sent = logged(codex_log)
    resume = next(m for m in sent if m.get("method") == "thread/resume")
    # The thread keeps its own approval settings, as in the Codex app.
    assert resume["params"] == {"threadId": "t-1", "excludeTurns": True}
    turn = next(m for m in sent if m.get("method") == "turn/start")
    assert turn["params"]["input"] == [{"type": "text", "text": "Run the tests"}]


def test_a_codex_approval_waits_for_the_users_answer(env, chats):
    registry, codex_log, _ = chats
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    live = until(lambda: chat.state(env.config, "codex", "t-1")["approval"])
    assert live["summary"] == "run `rm -rf build`" and live["reason"] == "clean the build"
    assert chat.state(env.config, "codex", "t-1")["partial"] == "Running the tests."
    chat.act(env.config, {"action": "answer", "provider": "codex", "id": "t-1",
                          "request": live["id"], "allow": True})  # fmt: skip
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    answer = next(m for m in logged(codex_log) if m.get("id") == 900 and "result" in m)
    assert answer["result"] == {"decision": "accept"}


def test_a_codex_turn_can_be_stopped(env, chats):
    registry, codex_log, _ = chats
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    until(lambda: chat.state(env.config, "codex", "t-1")["approval"])
    chat.act(env.config, {"action": "stop", "provider": "codex", "id": "t-1"})
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    stop = next(m for m in logged(codex_log) if m.get("method") == "turn/interrupt")
    assert stop["params"] == {"threadId": "t-1", "turnId": "turn-1"}


def test_a_codex_turn_takes_a_message_while_it_works(env, chats):
    _, codex_log, _ = chats
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                          "text": "work slowly", "cwd": "/repo"})  # fmt: skip
    until(lambda: chat.state(env.config, "codex", "t-1")["partial"] == "Running the tests.")
    assert chat.state(env.config, "codex", "t-1")["can_send"] is True
    said = chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                                 "text": "also check the docs"})  # fmt: skip
    assert said["ok"]
    steer = next(m for m in logged(codex_log) if m.get("method") == "turn/steer")
    assert steer["params"] == {"threadId": "t-1", "expectedTurnId": "turn-1",
                               "input": [{"type": "text", "text": "also check the docs"}]}  # fmt: skip
    live = chat.state(env.config, "codex", "t-1")
    assert live["busy"] and live["mid_turn"] == ["also check the docs"]
    assert live["partial"] == "Running the tests."  # the reply so far stays
    chat.act(env.config, {"action": "stop", "provider": "codex", "id": "t-1"})
    done = until(lambda: (s := chat.state(env.config, "codex", "t-1")) and not s["busy"] and s)
    assert done["mid_turn"] == []
    assert [m.get("method") for m in logged(codex_log)].count("turn/start") == 1


def test_a_claude_turn_takes_a_message_while_it_works(env, chats):
    _, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "work slowly"})  # fmt: skip
    until(lambda: chat.state(env.config, "claude", "s-1")["partial"] == "Looking at it.")
    assert chat.state(env.config, "claude", "s-1")["can_send"] is True
    said = chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                                 "text": "also check the docs"})  # fmt: skip
    assert said["ok"]
    live = chat.state(env.config, "claude", "s-1")
    assert live["busy"] and live["mid_turn"] == ["also check the docs"]
    assert live["partial"] == "Looking at it."  # the reply so far stays
    chat.act(env.config, {"action": "stop", "provider": "claude", "id": "s-1"})
    # Stopped, the message waiting runs as a turn of its own, as in Claude Code.
    done = until(lambda: (s := chat.state(env.config, "claude", "s-1")) and not s["busy"] and s)
    assert done["mid_turn"] == []
    texts = [" ".join(b.get("text", "") for b in m["message"]["content"])
             for m in logged(claude_log) if m.get("type") == "user"]  # fmt: skip
    assert texts == ["work slowly", "also check the docs"]


def test_a_message_while_claude_waits_on_a_tool_refuses_it_and_says_what_to_do(env, chats):
    _, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "approve this"})  # fmt: skip
    until(lambda: chat.state(env.config, "claude", "s-1")["approval"])
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "use make clean instead"})  # fmt: skip
    answer = next(m for m in logged(claude_log) if m.get("type") == "control_response")
    assert answer["response"]["request_id"] == "perm-1"
    assert answer["response"]["response"] == {"behavior": "deny",
                                              "message": "use make clean instead"}  # fmt: skip
    done = until(lambda: (s := chat.state(env.config, "claude", "s-1")) and not s["busy"] and s)
    assert done["approval"] is None and done["mid_turn"] == []
    assert [m for m in logged(claude_log) if m.get("type") == "user"][-1]["message"]["content"][0][
        "text"
    ] == "approve this"  # no second message: the refusal carried it


def test_a_message_while_codex_waits_on_an_approval_declines_it_and_steers(env, chats):
    _, codex_log, _ = chats
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    until(lambda: chat.state(env.config, "codex", "t-1")["approval"])
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                          "text": "skip that, check the docs"})  # fmt: skip
    sent = logged(codex_log)
    answer = next(m for m in sent if m.get("id") == 900 and "result" in m)
    assert answer["result"] == {"decision": "decline"}
    texts = [m["params"]["input"][0]["text"] for m in sent
             if m.get("method") in ("turn/steer", "turn/start")]  # fmt: skip
    assert texts[-1] == "skip that, check the docs"


def test_a_claude_turn_that_starts_on_its_own_counts_as_working(env, chats):
    # A message sent mid-turn can run as a turn of its own once the first one ends: Claude
    # opens every turn with its init, and that is when ax shows it working again.
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "hi"})
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    chat.CHATS.get("claude", "s-1")._read({"type": "system", "subtype": "init"})
    assert chat.state(env.config, "claude", "s-1")["busy"] is True


def test_a_thread_open_in_the_codex_app_gets_the_message_through_its_queue(env, chats, monkeypatch):
    ran = []
    monkeypatch.setattr(chat, "codex_open_in_app", lambda config, tid: True)
    monkeypatch.setattr(chat, "_run", lambda argv, env: ran.append((argv, env)) or (0, ""))
    said = chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-2",
                                 "text": "Also check the docs"})  # fmt: skip
    assert said["via"] == "codex app"
    [(argv, environ)] = ran
    assert argv[1:] == ["queue", "--thread", "t-2", "--message", "Also check the docs"]
    assert "CODEX_THREAD_ID" not in environ
    state = chat.state(env.config, "codex", "t-2")
    assert state["holder"] == "codex app" and state["can_send"]
    assert chat.CHATS.get("codex", "t-2") is None  # ax holds nothing


# Claude


def test_a_claude_session_nothing_else_holds_continues_in_the_background(env, chats):
    registry, _, claude_log = chats
    said = chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                                 "text": "Fix it", "cwd": "/repo"})  # fmt: skip
    assert said["via"] == "ax"
    live = until(lambda: (s := chat.state(env.config, "claude", "s-1")) and not s["busy"] and s)
    assert live["holder"] == "ax" and "background" in live["note"]
    assert "claude --resume s-1" in live["note"]
    sent = logged(claude_log)
    assert sent[0]["request"]["subtype"] == "initialize"
    assert sent[1]["message"]["content"] == [{"type": "text", "text": "Fix it"}]


def test_a_claude_approval_can_be_refused(env, chats):
    registry, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    live = until(lambda: chat.state(env.config, "claude", "s-1")["approval"])
    assert live["tool"] == "Bash" and live["summary"] == "run `rm -rf build`"  # asked, not done
    assert chat.state(env.config, "claude", "s-1")["partial"] == "Looking at it."
    chat.act(env.config, {"action": "answer", "provider": "claude", "id": "s-1",
                          "request": live["id"], "allow": False})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    answer = next(m for m in logged(claude_log) if m.get("type") == "control_response")
    assert answer["response"]["request_id"] == "perm-1"
    assert answer["response"]["response"]["behavior"] == "deny"


def test_a_refusal_can_tell_claude_what_to_do_instead(env, chats):
    """As the apps do for a plan: no, and here is what to do differently."""
    registry, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    live = until(lambda: chat.state(env.config, "claude", "s-1")["approval"])
    chat.act(env.config, {"action": "answer", "provider": "claude", "id": "s-1",
                          "request": live["id"], "allow": False,
                          "message": "  Keep the old build; only rebuild the charts.  "})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    answer = next(m for m in logged(claude_log) if m.get("type") == "control_response")
    assert answer["response"]["response"] == {
        "behavior": "deny", "message": "Keep the old build; only rebuild the charts."}  # fmt: skip


def test_an_allowed_claude_tool_runs_with_its_input(env, chats):
    registry, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    live = until(lambda: chat.state(env.config, "claude", "s-1")["approval"])
    chat.act(env.config, {"action": "answer", "provider": "claude", "id": "s-1",
                          "request": live["id"], "allow": True})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    answer = next(m for m in logged(claude_log) if m.get("type") == "control_response")
    assert answer["response"]["response"] == {"behavior": "allow",
                                              "updatedInput": {"command": "rm -rf build"}}  # fmt: skip


def test_a_message_to_a_claude_session_open_elsewhere_waits_until_it_is_closed(
    env, chats, monkeypatch
):
    registry, _, claude_log = chats
    open_now = {"s-1": True}
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: open_now.get(sid, False))
    state = chat.state(env.config, "claude", "s-1")
    assert (state["holder"], state["can_send"], state["take_over"]) == ("elsewhere", True, True)
    said = chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                                 "text": "hi", "cwd": "/repo"})  # fmt: skip
    assert said["waiting"] and "as soon as it's closed" in said["message"]
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "and this"})
    state = chat.state(env.config, "claude", "s-1")
    assert state["pending"] and state["queued"] == "hi\n\nand this"
    assert chat.CHATS.get("claude", "s-1") is None  # nothing sent while the app holds it
    open_now["s-1"] = False  # the user closed it in the app
    chat.dispatch_pending(env.config)
    state = chat.state(env.config, "claude", "s-1")
    assert state["holder"] == "ax"
    sent = until(lambda: [m for m in logged(claude_log) if m.get("type") == "user"])
    assert [m["message"]["content"][0]["text"] for m in sent] == ["hi", "and this"]
    chat.state(env.config, "claude", "s-1")  # read again: sent once only
    assert len([m for m in logged(claude_log) if m.get("type") == "user"]) == 2


def test_a_take_over_without_a_message_still_waits_for_the_app(env, chats, monkeypatch):
    open_now = {"s-1": True}
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: open_now.get(sid, False))
    said = chat.act(env.config, {"action": "take-over", "provider": "claude", "id": "s-1",
                                 "cwd": "/repo"})  # fmt: skip
    assert said["waiting"] and "Close it in the Claude app" in said["message"]
    assert chat.state(env.config, "claude", "s-1")["pending"]
    open_now["s-1"] = False
    chat.dispatch_pending(env.config)
    state = chat.state(env.config, "claude", "s-1")
    assert state["holder"] == "ax" and state["can_send"]


def test_ax_continues_a_claude_session_by_its_id_and_asks_before_tools():
    command = chat.claude_command("s-1")
    assert command[command.index("--resume") + 1] == "s-1"
    assert command[command.index("--permission-prompt-tool") + 1] == "stdio"
    assert "--include-partial-messages" in command


def test_handing_a_session_back_closes_ax_s_process(env, chats):
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo"})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    chat.act(env.config, {"action": "release", "provider": "claude", "id": "s-1"})
    assert chat.CHATS.get("claude", "s-1") is None


def test_handing_back_adds_a_claude_session_the_app_missed(env, chats):
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo", "name": "Fix the axis"})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    # The app wasn't there when ax opened it; it is now, and Hand back adds it.
    folder = env.config.claude_app_sessions / "acct" / "org"
    folder.mkdir(parents=True)
    (folder / "local_app.json").write_text(
        json.dumps({"sessionId": "local_app", "cliSessionId": "other", "model": "claude-opus-5-5"})
    )
    said = chat.act(env.config, {"action": "release", "provider": "claude", "id": "s-1"})
    assert "Claude app" in said["message"]
    [record] = [json.loads(p.read_text()) for p in folder.glob("local_*.json")
                if p.name != "local_app.json"]  # fmt: skip
    assert (record["cliSessionId"], record["cwd"], record["title"]) == (
        "s-1", "/repo", "Fix the axis")  # fmt: skip
    assert "restarted" in said["message"]  # the app reads its sessions when it starts
    again = chat.act(env.config, {"action": "release", "provider": "claude", "id": "s-1",
                                  "cwd": "/repo", "name": "Fix the axis"})  # fmt: skip
    assert "Claude app" in again["message"] and "restarted" not in again["message"]
    assert len(list(folder.glob("local_*.json"))) == 2  # it was there already


def test_when_ax_stops_every_claude_session_it_holds_joins_the_claude_app(env, chats):
    folder = env.config.claude_app_sessions / "acct" / "org"
    folder.mkdir(parents=True)
    (folder / "local_app.json").write_text(json.dumps({"sessionId": "local_app"}))
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo", "name": "Fix the axis"})  # fmt: skip
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "Fix it",
                          "cwd": "/repo"})  # fmt: skip
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    chat.hand_back_all(env.config)
    assert chat.CHATS.get("claude", "s-1") is None and chat.CHATS.get("codex", "t-1") is None
    ids = [json.loads(p.read_text()).get("cliSessionId") for p in folder.glob("local_*.json")]
    assert sorted(i for i in ids if i) == ["s-1"]  # Codex's own app lists every thread


def test_handing_back_without_the_claude_app_only_lets_go(env, chats):
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo"})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    said = chat.act(env.config, {"action": "release", "provider": "claude", "id": "s-1"})
    assert said["message"] == "Handed back: ax no longer holds it."
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "Fix it",
                          "cwd": "/repo"})  # fmt: skip
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    said = chat.act(env.config, {"action": "release", "provider": "codex", "id": "t-1"})
    assert said["message"] == "Handed back: ax no longer holds it."


def app_folder(env):
    folder = env.config.claude_app_sessions / "acct" / "org"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "local_app.json").write_text(json.dumps({"sessionId": "local_app"}))
    return folder


def in_app(folder):
    ids = (json.loads(p.read_text()).get("cliSessionId") for p in folder.glob("local_*.json"))
    return sorted(i for i in ids if i)


def test_a_claude_session_ax_opens_joins_the_claude_app_at_once(env, chats):
    folder = app_folder(env)
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo", "name": "Fix the axis"})  # fmt: skip
    assert in_app(folder) == ["s-1"]  # before any hand back
    note = chat.state(env.config, "claude", "s-1")["note"]
    assert "Claude app" in note and "doesn't show" not in note


def test_a_new_claude_session_joins_the_claude_app_at_once(env, chats, tmp_path):
    folder = app_folder(env)
    said = chat.act(env.config, {"action": "start", "provider": "claude", "cwd": str(tmp_path),
                                 "text": "Plan the release"})  # fmt: skip
    assert in_app(folder) == [said["id"]]


def test_ax_lets_go_of_a_session_the_claude_app_opens(env, chats, monkeypatch):
    _, _, claude_log = chats
    app_folder(env)
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo"})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    # The app opened it: a process of its own runs the session now (any live one will do).
    monkeypatch.setattr(chat, "_claude_agents", lambda: {"s-1": {os.getpid()}})
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: sid == "s-1")
    chat.yield_held(env.config)
    state = chat.state(env.config, "claude", "s-1")
    assert state["holder"] == "elsewhere" and chat.CHATS.get("claude", "s-1") is None
    said = chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                                 "text": "and the docs"})  # fmt: skip
    assert said["waiting"] is True  # kept for when the app lets go, never written beside it
    texts = [m["message"]["content"][0]["text"] for m in logged(claude_log)
             if m.get("type") == "user"]  # fmt: skip
    assert texts == ["Fix it"]


def test_ax_knows_its_own_process_from_the_app_s(env, chats, monkeypatch):
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo"})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    mine = chat.CHATS.get("claude", "s-1").process.pid
    gone = 2**22 + 12345  # a process that has ended, as one ax restarted leaves behind
    monkeypatch.setattr(chat, "_claude_agents", lambda: {"s-1": {mine, gone, None}})
    assert chat.state(env.config, "claude", "s-1")["holder"] == "ax"


def test_the_sessions_list_lets_go_of_what_the_app_opened(env, chats, monkeypatch):
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "Fix it",
                          "cwd": "/repo"})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    monkeypatch.setattr(chat, "_claude_agents", lambda: {"s-1": {os.getpid()}})
    chat.yield_held(env.config)
    assert chat.CHATS.get("claude", "s-1") is None


def test_sessions_ax_holds_are_listed_with_their_state(env, chats):
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "approve",
                          "cwd": "/Users/me/Repos/demo", "name": "Fix the fetch helper"})  # fmt: skip
    until(lambda: chat.state(env.config, "claude", "s-1")["approval"])
    [held] = chat.held()
    assert (held["provider"], held["id"], held["name"], held["kind"]) == (
        "claude", "s-1", "Fix the fetch helper", "ax (background)",
    )  # fmt: skip
    assert (held["state"], held["waiting_for"]) == ("waiting", "approval")


# Through the app


@pytest.fixture
def served(env, tmp_path, chats, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>ax</title>")
    monkeypatch.setattr(live_sessions, "listing", lambda config: {"sessions": [], "errors": []})
    server = serve.make_server(env.config, port=0, usage_of=lambda c: [], web=web, poll=0.05)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def post(url, body, headers=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def test_the_app_sends_at_once_from_this_mac_and_through_a_tunnel_with_its_token(env, served):
    body = {"action": "send", "provider": "codex", "id": "t-1", "text": "Ship it", "cwd": "/r"}
    status, said = post(f"{served}/api/chat", body)
    assert status == 200 and said["ok"] and said["via"] == "ax"
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    remote = {"X-Forwarded-For": "1.2.3.4"}
    token = app.token(env.config)
    status, _ = post(f"{served}/api/chat", body, remote)
    assert status == 401
    status, said = post(f"{served}/api/chat", {**body, "text": "And again"},
                        {**remote, "X-Ax-Token": token})  # fmt: skip
    assert status == 200 and said["ok"] and "confirm" not in said  # the token is the only gate


def test_a_refused_message_is_a_clear_error(env, served):
    status, said = post(f"{served}/api/chat", {"action": "send", "provider": "codex", "id": "t"})
    assert status == 400 and "text" in said["error"]


# Images


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63fccf54030f00048501808ca98c210000000049454e44ae426082"
)


def image(data: bytes = PNG, media: str = "image/png") -> dict:
    import base64

    return {"media": media, "data": base64.b64encode(data).decode()}


def test_a_pasted_image_goes_to_claude_beside_the_words(env, chats):
    registry, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "cwd": "/repo",
                          "text": "What's wrong here?", "images": [image()]})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    content = logged(claude_log)[1]["message"]["content"]
    assert content[0] == {"type": "image", "source": {"type": "base64",
                                                      "media_type": "image/png",
                                                      "data": image()["data"]}}  # fmt: skip
    assert content[1] == {"type": "text", "text": "What's wrong here?"}


def test_an_image_alone_is_a_message_too(env, chats):
    registry, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "cwd": "/repo",
                          "text": "", "images": [image()]})  # fmt: skip
    until(lambda: not chat.state(env.config, "claude", "s-1")["busy"])
    assert [b["type"] for b in logged(claude_log)[1]["message"]["content"]] == ["image"]


def test_a_pasted_image_goes_to_codex_as_a_local_file(env, chats):
    registry, codex_log, _ = chats
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "cwd": "/repo",
                          "text": "Check the chart", "images": [image()]})  # fmt: skip
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    turn = next(m for m in logged(codex_log) if m.get("method") == "turn/start")
    picture, words = turn["params"]["input"]
    assert picture["type"] == "localImage" and Path(picture["path"]).read_bytes() == PNG
    assert words == {"type": "text", "text": "Check the chart"}


def test_a_thread_open_in_the_codex_app_gets_the_image_through_its_queue(env, chats, monkeypatch):
    ran = []
    monkeypatch.setattr(chat, "codex_open_in_app", lambda config, tid: True)
    monkeypatch.setattr(chat, "_run", lambda argv, env: ran.append(argv) or (0, ""))
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-2",
                          "text": "This one", "images": [image()]})  # fmt: skip
    [argv] = ran
    picture = argv[argv.index("--image") + 1]
    assert Path(picture).read_bytes() == PNG and argv[argv.index("--message") + 1] == "This one"


@pytest.mark.parametrize(
    ("images", "error"),
    [
        ([{"media": "image/svg+xml", "data": "PHN2Zz4="}], "PNG, JPEG, GIF or WebP"),
        ([{"media": "image/png", "data": "not base64!"}], "isn't an image"),
        ([image()] * 11, "at most 10"),
    ],
)
def test_images_are_checked_before_anything_is_sent(env, chats, images, error):
    with pytest.raises(ValueError, match=error):
        chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                              "text": "hi", "images": images})  # fmt: skip
    assert chat.CHATS.get("claude", "s-1") is None


def test_the_app_takes_a_message_with_a_screenshot_in_it(env, served):
    big = image(PNG + b"\0" * 200_000)  # well over the size other actions accept
    body = {"action": "send", "provider": "codex", "id": "t-1", "text": "See", "cwd": "/r",
            "images": [big]}  # fmt: skip
    status, said = post(f"{served}/api/chat", body)
    assert status == 200 and said["ok"], said


# New sessions


def test_a_new_claude_session_starts_in_a_folder_held_by_ax(env, chats, tmp_path):
    registry, _, claude_log = chats
    said = chat.act(env.config, {"action": "start", "provider": "claude", "cwd": str(tmp_path),
                                 "text": "Plan the release\nwith its tests", "images": [image()]})  # fmt: skip
    assert said["ok"] and said["provider"] == "claude"
    sid = said["id"]
    assert str(uuid.UUID(sid)) == sid
    until(lambda: not chat.state(env.config, "claude", sid)["busy"])
    assert json.loads(claude_log.read_text().splitlines()[0])[:2] == [sid, "new"]
    assert [b["type"] for b in logged(claude_log)[1]["message"]["content"]] == ["image", "text"]
    [held] = chat.held()
    assert (held["id"], held["name"], held["cwd"], held["kind"]) == (
        sid, "Plan the release", str(tmp_path), "ax (background)",
    )  # fmt: skip
    assert chat.state(env.config, "claude", sid)["holder"] == "ax"


def test_a_new_claude_session_gets_its_own_id_not_a_resume():
    command = chat.claude_command("s-9", new=True)
    assert command[command.index("--session-id") + 1] == "s-9" and "--resume" not in command


def test_a_new_codex_thread_starts_in_a_folder_held_by_ax(env, chats, tmp_path):
    registry, codex_log, _ = chats
    said = chat.act(env.config, {"action": "start", "provider": "codex", "cwd": str(tmp_path),
                                 "text": "Review the model card"})  # fmt: skip
    assert said["id"] == "t-new"
    until(lambda: not chat.state(env.config, "codex", "t-new")["busy"])
    sent = logged(codex_log)
    start = next(m for m in sent if m.get("method") == "thread/start")
    assert start["params"] == {"cwd": str(tmp_path)}  # its own settings, as in the app
    assert not any(m.get("method") == "thread/resume" for m in sent)
    turn = next(m for m in sent if m.get("method") == "turn/start")
    assert turn["params"]["threadId"] == "t-new"


def test_a_new_claude_session_starts_on_the_chosen_model_and_effort(env, chats, tmp_path):
    _, _, claude_log = chats
    said = chat.act(env.config, {"action": "start", "provider": "claude", "cwd": str(tmp_path),
                                 "text": "Plan it", "model": "opus", "effort": "max"})  # fmt: skip
    state = settle(env, "claude", said["id"])
    launch = json.loads(claude_log.read_text().splitlines()[0])
    assert launch[1:] == ["new", "max"]  # the effort it starts with, no restart
    assert [c["model"] for c in controls(claude_log, "set_model")] == ["opus"]
    assert state["settings"]["model"] == "opus" and state["settings"]["effort"] == "max"


def test_a_new_codex_thread_starts_on_the_chosen_model_and_effort(env, chats, tmp_path):
    _, codex_log, _ = chats
    said = chat.act(env.config, {"action": "start", "provider": "codex", "cwd": str(tmp_path),
                                 "text": "Review it", "model": "gpt-6-sol", "effort": "high"})  # fmt: skip
    settle(env, "codex", said["id"])
    turn = next(m for m in logged(codex_log) if m.get("method") == "turn/start")
    assert turn["params"]["model"] == "gpt-6-sol" and turn["params"]["effort"] == "high"


def test_a_new_session_starts_in_the_modes_chosen_for_it(env, chats, tmp_path):
    _, _, claude_log = chats
    said = chat.act(env.config, {"action": "start", "provider": "claude", "cwd": str(tmp_path),
                                 "text": "Plan it", "plan": True, "auto": True})  # fmt: skip
    state = settle(env, "claude", said["id"])
    assert [c["mode"] for c in controls(claude_log, "set_permission_mode")] == ["plan"]
    assert state["settings"]["plan"] and state["settings"]["auto"]


def test_a_new_session_can_start_on_a_goal(env, chats, tmp_path):
    _, codex_log, _ = chats
    said = chat.act(env.config, {"action": "start", "provider": "codex", "cwd": str(tmp_path),
                                 "text": "All tests pass", "goal": True})  # fmt: skip
    settle(env, "codex", said["id"])
    goal = next(m for m in logged(codex_log) if m.get("method") == "thread/goal/set")
    assert goal["params"]["objective"] == "All tests pass"


def test_a_new_session_on_a_model_the_tool_lacks_doesnt_start(env, chats, tmp_path):
    with pytest.raises(ValueError, match="no model gpt-9"):
        chat.act(env.config, {"action": "start", "provider": "claude", "cwd": str(tmp_path),
                              "text": "hi", "model": "gpt-9"})  # fmt: skip
    assert chat.held() == []


def test_both_tools_list_their_models_for_a_new_session(env, tmp_path):
    claude = script(tmp_path, "claude.py", FAKE_CLAUDE)
    codex = script(tmp_path, "codex.py", FAKE_CODEX)
    found = chat.available_models(
        env.config,
        claude=[sys.executable, str(claude), str(tmp_path / "c.log"), "-", "new", "-"],
        codex=[sys.executable, str(codex), str(tmp_path / "x.log")],
        fresh=True,
    )
    assert [m["id"] for m in found["claude"]] == ["default", "opus", "haiku"]
    assert [m["id"] for m in found["codex"]] == ["gpt-6-astra", "gpt-6-sol"]  # hidden ones out
    assert [m["default"] for m in found["codex"]] == [True, False]
    assert found["errors"] == []
    missing = chat.available_models(env.config, claude=[str(tmp_path / "no-claude")],
                                    codex=[sys.executable, str(codex), str(tmp_path / "x.log")],
                                    fresh=True)  # fmt: skip
    assert missing["claude"] == [] and missing["errors"][0].startswith("claude:")
    assert [m["id"] for m in missing["codex"]] == ["gpt-6-astra", "gpt-6-sol"]


@pytest.mark.parametrize("cwd", [None, "relative/folder", "/no/such/folder/anywhere"])
def test_a_new_session_needs_a_folder_that_exists(env, chats, cwd):
    with pytest.raises(ValueError, match="folder"):
        chat.act(env.config, {"action": "start", "provider": "claude", "cwd": cwd, "text": "hi"})
    assert chat.held() == []


def test_a_new_session_needs_something_to_say(env, chats, tmp_path):
    with pytest.raises(ValueError, match="nothing to send"):
        chat.act(env.config, {"action": "start", "provider": "codex", "cwd": str(tmp_path)})


def test_a_just_started_session_shows_before_its_transcript_exists(
    env, chats, tmp_path, monkeypatch
):
    monkeypatch.setattr(live_sessions, "listing", lambda config: {"sessions": [], "errors": []})
    said = chat.act(env.config, {"action": "start", "provider": "claude", "cwd": str(tmp_path),
                                 "text": "Start here"})  # fmt: skip
    view = live_sessions.session_view(env.config, "claude", said["id"])
    assert view["events"] == [] and view["next"] == 0
    assert (view["session"]["name"], view["session"]["cwd"]) == ("Start here", str(tmp_path))
    assert view["chat"]["holder"] == "ax"


def test_the_app_starts_a_session_and_answers_with_its_id(env, served, tmp_path):
    status, said = post(f"{served}/api/chat", {"action": "start", "provider": "codex",
                                               "cwd": str(tmp_path), "text": "Go"})  # fmt: skip
    assert status == 200 and said["ok"] and said["id"] == "t-new"


def test_the_app_lists_both_tools_models(env, served, monkeypatch):
    offered = {"claude": [{"id": "opus"}], "codex": [{"id": "gpt-6-sol"}], "errors": []}
    monkeypatch.setattr(chat, "available_models", lambda config: offered)
    with urllib.request.urlopen(f"{served}/api/models", timeout=5) as response:
        assert response.status == 200 and json.loads(response.read()) == offered


def test_a_session_ax_started_keeps_the_name_of_its_first_message(env, chats, tmp_path):
    said = chat.act(env.config, {"action": "start", "provider": "claude", "cwd": str(tmp_path),
                                 "text": "Fix the flaky test\nin the fetch helper"})  # fmt: skip
    row = {"pid": 9, "cwd": str(tmp_path), "kind": "interactive", "sessionId": said["id"],
           "name": "new-live-b4", "status": "idle"}  # Claude's own placeholder  # fmt: skip
    listed = live_sessions.listing(
        env.config,
        claude_of=lambda c: live_sessions.claude(c, run=lambda argv: json.dumps([row])),
        codex_of=lambda c: [],
    )
    [found] = listed["sessions"]
    assert (found["name"], found["kind"]) == ("Fix the flaky test", "ax (background)")


# Modes, models and goals


def launches(path):
    """Each time the fake Claude started: its session id, new or resume, and effort."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith("[")]


def controls(path, subtype):
    return [m["request"] for m in logged(path)
            if m.get("type") == "control_request" and m["request"]["subtype"] == subtype]  # fmt: skip


def settle(env, provider, sid):
    return until(lambda: (s := chat.state(env.config, provider, sid)) and not s["busy"] and s)


def test_a_claude_session_ax_opens_reports_its_models_and_modes(env, chats):
    said = chat.act(env.config, {"action": "open", "provider": "claude", "id": "s-1"})
    assert said["ok"]
    state = chat.state(env.config, "claude", "s-1")
    assert state["settings"] == {"plan": False, "auto": False, "model": None, "effort": None}
    assert state["models"][:2] == [
        {"id": "default", "label": "Default (recommended)", "default_effort": None,
         "description": "", "default": True, "efforts": ["low", "medium", "high", "xhigh", "max"]},
        {"id": "opus", "label": "Opus 5.5", "default_effort": None,
         "description": "", "default": False, "efforts": ["low", "medium", "high", "xhigh", "max"]},
    ]  # fmt: skip
    assert state["goal"] is None


def test_plan_mode_and_approve_for_me_set_claudes_permission_mode(env, chats):
    _, _, claude_log = chats
    chat.act(env.config, {"action": "settings", "provider": "claude", "id": "s-1", "plan": True})
    until(lambda: chat.state(env.config, "claude", "s-1")["settings"]["plan"])
    chat.act(env.config, {"action": "settings", "provider": "claude", "id": "s-1",
                          "plan": False, "auto": True})  # fmt: skip
    until(lambda: chat.state(env.config, "claude", "s-1")["settings"]["auto"])
    chat.act(env.config, {"action": "settings", "provider": "claude", "id": "s-1", "auto": False})
    until(lambda: len(controls(claude_log, "set_permission_mode")) == 3)
    assert [c["mode"] for c in controls(claude_log, "set_permission_mode")] == [
        "plan", "auto", "default"]  # fmt: skip
    assert chat.state(env.config, "claude", "s-1")["settings"]["auto"] is False


def test_claude_switches_model_at_once_and_effort_by_restarting_between_turns(env, chats):
    _, _, claude_log = chats
    chat.act(env.config, {"action": "settings", "provider": "claude", "id": "s-1",
                          "model": "opus"})  # fmt: skip
    until(lambda: controls(claude_log, "set_model"))
    assert controls(claude_log, "set_model") == [{"subtype": "set_model", "model": "opus"}]
    chat.act(env.config, {"action": "settings", "provider": "claude", "id": "s-1",
                          "effort": "low"})  # fmt: skip
    until(lambda: len(launches(claude_log)) == 2)
    assert launches(claude_log) == [["s-1", "resume", "-"], ["s-1", "resume", "low"]]
    # The restarted process keeps the model chosen before it.
    until(lambda: len(controls(claude_log, "set_model")) == 2)
    state = chat.state(env.config, "claude", "s-1")
    assert state["settings"]["model"] == "opus" and state["settings"]["effort"] == "low"
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "hi"})
    assert settle(env, "claude", "s-1")["holder"] == "ax"


def test_claude_asks_to_leave_plan_mode_with_its_plan(env, chats):
    chat.act(env.config, {"action": "settings", "provider": "claude", "id": "s-1", "plan": True})
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "plan please"})  # fmt: skip
    asked = until(lambda: chat.state(env.config, "claude", "s-1")["approval"])
    assert asked["summary"] == "start on its plan" and asked["plan"] == "# Plan\n1. Do it"
    assert asked["detail"] is None
    chat.act(env.config, {"action": "answer", "provider": "claude", "id": "s-1",
                          "request": asked["id"], "allow": True})  # fmt: skip
    assert settle(env, "claude", "s-1")["settings"]["plan"] is False


def test_a_claude_goal_is_its_goal_command(env, chats):
    _, _, claude_log = chats
    said = chat.act(env.config, {"action": "goal", "provider": "claude", "id": "s-1",
                                 "objective": "the tests pass"})  # fmt: skip
    assert said["ok"]
    state = settle(env, "claude", "s-1")
    assert state["goal"] == {"objective": "the tests pass", "status": "set", "tokens_used": None,
                             "token_budget": None, "seconds": None}  # fmt: skip
    chat.act(env.config, {"action": "goal-clear", "provider": "claude", "id": "s-1"})
    settle(env, "claude", "s-1")
    texts = [
        m["message"]["content"][0]["text"] for m in logged(claude_log) if m.get("type") == "user"
    ]
    assert texts == ["/goal the tests pass", "/goal clear"]
    assert chat.state(env.config, "claude", "s-1")["goal"] is None


def test_a_claude_goal_clears_while_it_works_once_its_turn_ends(env, chats):
    _, _, claude_log = chats
    chat.act(env.config, {"action": "goal", "provider": "claude", "id": "s-1",
                          "objective": "the tests pass"})  # fmt: skip
    settle(env, "claude", "s-1")
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1",
                          "text": "approve this"})  # fmt: skip
    until(lambda: chat.state(env.config, "claude", "s-1")["approval"])  # mid-turn
    said = chat.act(env.config, {"action": "goal-clear", "provider": "claude", "id": "s-1"})
    assert said["ok"] and chat.state(env.config, "claude", "s-1")["goal"] is None
    texts = [
        m["message"]["content"][0]["text"] for m in logged(claude_log) if m.get("type") == "user"
    ]
    assert texts[-1] == "/goal clear"  # queued by Claude until the turn ends


def test_a_codex_thread_ax_opens_reports_its_models_and_settings(env, chats):
    _, codex_log, _ = chats
    chat.act(env.config, {"action": "open", "provider": "codex", "id": "t-1"})
    state = chat.state(env.config, "codex", "t-1")
    # Its own settings: the model and effort it runs with, and its auto review.
    assert state["settings"] == {"plan": False, "auto": True, "model": "gpt-6-astra",
                                 "effort": "xhigh"}  # fmt: skip
    assert state["models"] == [
        {"id": "gpt-6-astra", "label": "GPT-6-Astra", "default_effort": "medium",
         "description": "", "default": True, "efforts": ["low", "medium", "high", "xhigh"]},
        {"id": "gpt-6-sol", "label": "GPT-6-Sol", "default_effort": "low",
         "description": "", "default": False, "efforts": ["low", "high"]},
    ]  # fmt: skip
    hello = next(m for m in logged(codex_log) if m.get("method") == "initialize")
    assert hello["params"]["capabilities"] == {"experimentalApi": True}


def test_codex_keeps_its_own_settings_until_one_is_changed_then_the_next_turn_carries_it(
    env, chats
):
    _, codex_log, _ = chats
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "first"})
    settle(env, "codex", "t-1")
    chat.act(env.config, {"action": "settings", "provider": "codex", "id": "t-1", "plan": True,
                          "auto": False, "model": "gpt-6-sol", "effort": "high"})  # fmt: skip
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "second"})
    settle(env, "codex", "t-1")
    first, second = [m["params"] for m in logged(codex_log) if m.get("method") == "turn/start"]
    assert set(first) == {"threadId", "input"}
    assert second["collaborationMode"] == {"mode": "plan", "settings": {
        "model": "gpt-6-sol", "reasoning_effort": "high", "developer_instructions": None}}  # fmt: skip
    assert second["approvalsReviewer"] == "user"
    assert (second["model"], second["effort"]) == ("gpt-6-sol", "high")
    assert chat.state(env.config, "codex", "t-1")["settings"] == {
        "plan": True, "auto": False, "model": "gpt-6-sol", "effort": "high"}  # fmt: skip


def test_a_codex_goal_is_set_then_pursued(env, chats):
    _, codex_log, _ = chats
    chat.act(env.config, {"action": "goal", "provider": "codex", "id": "t-1",
                          "objective": "ship it", "budget": 50000})  # fmt: skip
    state = settle(env, "codex", "t-1")
    assert state["goal"] == {"objective": "ship it", "status": "active", "tokens_used": 1200,
                             "token_budget": 50000, "seconds": 90}  # fmt: skip
    sent = logged(codex_log)
    goal = next(m for m in sent if m.get("method") == "thread/goal/set")
    assert goal["params"] == {"threadId": "t-1", "objective": "ship it", "origin": "user",
                              "tokenBudget": 50000}  # fmt: skip
    turn = next(m for m in sent if m.get("method") == "turn/start")
    assert turn["params"]["input"] == [{"type": "text", "text": "ship it"}]
    chat.act(env.config, {"action": "goal-clear", "provider": "codex", "id": "t-1"})
    until(lambda: chat.state(env.config, "codex", "t-1")["goal"] is None)
    clear = next(m for m in logged(codex_log) if m.get("method") == "thread/goal/clear")
    assert clear["params"] == {"threadId": "t-1", "origin": "user"}


@pytest.mark.parametrize(
    "change,error",
    [
        ({"model": "gpt-9"}, "no model gpt-9"),
        ({"model": "gpt-6-sol", "effort": "xhigh"}, "gpt-6-sol has no effort xhigh"),
        ({"effort": "max"}, "gpt-6-astra has no effort max"),
        ({"plan": "yes"}, "plan is true or false"),
        ({}, "nothing to change"),
    ],
)
def test_settings_are_checked_before_anything_changes(env, chats, change, error):
    with pytest.raises(ValueError, match=error):
        chat.act(env.config, {"action": "settings", "provider": "codex", "id": "t-1", **change})


def test_a_goal_needs_an_objective(env, chats):
    with pytest.raises(ValueError, match="say what the goal is"):
        chat.act(env.config, {"action": "goal", "provider": "codex", "id": "t-1", "objective": " "})


def test_a_thread_open_in_the_codex_app_keeps_its_modes_there(env, chats, monkeypatch):
    monkeypatch.setattr(chat, "codex_open_in_app", lambda config, tid: True)
    with pytest.raises(ValueError, match="open in the Codex app"):
        chat.act(env.config, {"action": "settings", "provider": "codex", "id": "t-2", "plan": True})


def test_a_codex_threads_plan_is_the_turns_task_list(env, chats):
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "plan steps"})
    state = settle(env, "codex", "t-1")
    assert state["tasks"] == {"items": [{"text": "Read", "status": "completed"},
                                        {"text": "Fix", "status": "in_progress"}],
                              "explanation": "Two steps"}  # fmt: skip
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "next"})
    assert settle(env, "codex", "t-1")["tasks"] is None  # a new message starts a new list


# Questions


def test_claudes_question_waits_for_answers_and_takes_them_as_the_sdk_says(env, chats):
    _, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "ask me"})
    asked = until(lambda: chat.state(env.config, "claude", "s-1")["question"])
    assert asked["id"] == "ask-1" and asked["via"] == "claude" and asked["call"] == "tu-1"
    assert [q["question"] for q in asked["questions"]] == ["Which format?", "Which sections?"]
    assert chat.state(env.config, "claude", "s-1")["approval"] is None
    assert next(s for s in chat.held() if s["id"] == "s-1")["waiting_for"] == "question"
    chat.act(env.config, {"action": "answer-question", "provider": "claude", "id": "s-1",
                          "request": "ask-1", "answers": [["Summary"], ["Intro", "End"]]})  # fmt: skip
    settle(env, "claude", "s-1")
    answer = next(m for m in logged(claude_log) if m.get("type") == "control_response")
    given = answer["response"]["response"]
    assert given["behavior"] == "allow"
    assert given["updatedInput"]["answers"] == {"Which format?": "Summary",
                                                "Which sections?": "Intro, End"}  # fmt: skip
    assert len(given["updatedInput"]["questions"]) == 2
    assert chat.state(env.config, "claude", "s-1")["question"] is None


def test_skipping_claudes_question_declines_it(env, chats):
    _, _, claude_log = chats
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "ask me"})
    until(lambda: chat.state(env.config, "claude", "s-1")["question"])
    chat.act(env.config, {"action": "answer", "provider": "claude", "id": "s-1",
                          "request": "ask-1", "allow": False})  # fmt: skip
    assert chat.state(env.config, "claude", "s-1")["question"] is None  # at once, not at the end
    settle(env, "claude", "s-1")
    answer = next(m for m in logged(claude_log) if m.get("type") == "control_response")
    assert answer["response"]["response"]["behavior"] == "deny"


def test_codexs_blocking_question_is_answered_through_the_app_server(env, chats):
    _, codex_log, _ = chats
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "ask me"})
    asked = until(lambda: chat.state(env.config, "codex", "t-1")["question"])
    assert asked == {"id": "codex-901", "via": "codex", "call": "c9", "questions": [{
        "id": "scope", "header": "Scope", "question": "Which?", "multi": False, "other": True,
        "secret": False, "options": [{"label": "A", "description": "a"}]}]}  # fmt: skip
    chat.act(env.config, {"action": "answer-question", "provider": "codex", "id": "t-1",
                          "request": "codex-901", "answers": [["A"]]})  # fmt: skip
    settle(env, "codex", "t-1")
    answer = next(m for m in logged(codex_log) if m.get("id") == 901 and "result" in m)
    assert answer["result"] == {"answers": {"scope": {"answers": ["A"]}}}


def test_codexs_async_question_is_answered_with_a_reply_in_its_own_format(env, chats):
    _, codex_log, _ = chats
    chat.act(env.config, {"action": "answer-question", "provider": "codex", "id": "t-1",
                          "via": "codex-async", "call": "c2", "questions": ["May I grant?"],
                          "answers": [["Approve"]]})  # fmt: skip
    settle(env, "codex", "t-1")
    sent = next(m for m in logged(codex_log) if m.get("method") == "turn/start")
    text = sent["params"]["input"][0]["text"]
    assert text.startswith("<send_user_message_question_reply>\n")
    [item] = json.loads(text.split("\n")[1])
    assert item == {"questionItemId": '["request_user_input_async","c2",0]',
                    "question": "May I grant?", "answer": "Approve"}  # fmt: skip


def test_a_question_ax_cant_reach_says_where_to_answer_it(env, chats):
    import pytest as _pytest

    with _pytest.raises(ValueError, match="answer it where"):
        chat.act(env.config, {"action": "answer-question", "provider": "claude", "id": "s-1",
                              "request": "ask-9", "answers": [["A"]]})  # fmt: skip

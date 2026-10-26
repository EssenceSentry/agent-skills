"""Writing to sessions from the ax app: Codex through its app-server or the app's queue,
Claude through a headless process once nothing else holds the session, streamed replies,
approvals as answers, and a second confirmation for whatever comes through a shared link."""

import json
import sys
import threading
import time
import urllib.request

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
        say({"id": message["id"], "result": {"thread": {"id": message["params"]["threadId"]}}})
    elif method == "turn/start":
        say({"id": message["id"], "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        say({"method": "turn/started", "params": {"turn": {"id": "turn-1"}}})
        say({"method": "item/agentMessage/delta", "params": {"delta": "Running"}})
        say({"method": "item/agentMessage/delta", "params": {"delta": " the tests."}})
        text = message["params"]["input"][0]["text"]
        if "approve" in text:
            say({"id": 900, "method": "item/commandExecution/requestApproval",
                 "params": {"threadId": "t", "turnId": "turn-1", "itemId": "i",
                            "command": "rm -rf build", "reason": "clean the build"}})
        else:
            say({"method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
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
for line in sys.stdin:
    message = json.loads(line)
    log.write(line); log.flush()
    if message.get("type") == "control_request":
        subtype = message["request"]["subtype"]
        say({"type": "control_response", "response": {"subtype": "success",
                                                      "request_id": message["request_id"]}})
        if subtype == "interrupt":
            say({"type": "result", "subtype": "error_during_execution"})
    elif message.get("type") == "user":
        text = message["message"]["content"][0]["text"]
        delta("Looking")
        delta(" at it.")
        if "approve" in text:
            say({"type": "control_request", "request_id": "perm-1", "request": {
                "subtype": "can_use_tool", "tool_name": "Bash",
                "input": {"command": "rm -rf build"}}})
        else:
            say({"type": "result", "subtype": "success"})
    elif message.get("type") == "control_response":
        say({"type": "result", "subtype": "success"})
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
        claude_command=lambda sid: [sys.executable, str(claude), str(claude_log), sid],
    )
    monkeypatch.setattr(chat, "CHATS", registry)
    monkeypatch.setattr(chat, "codex_open_in_app", lambda config, tid: False)
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: False)
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


def test_a_session_still_working_takes_no_second_message(env, chats):
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    until(lambda: chat.state(env.config, "codex", "t-1")["approval"])
    with pytest.raises(ValueError, match="still working"):
        chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1", "text": "more"})


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


def test_a_claude_session_open_elsewhere_must_be_taken_over_first(env, chats, monkeypatch):
    registry, _, claude_log = chats
    open_now = {"s-1": True}
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: open_now.get(sid, False))
    state = chat.state(env.config, "claude", "s-1")
    assert (state["holder"], state["can_send"], state["take_over"]) == ("elsewhere", False, True)
    with pytest.raises(ValueError, match="take it over"):
        chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "hi"})
    said = chat.act(env.config, {"action": "take-over", "provider": "claude", "id": "s-1",
                                 "cwd": "/repo"})  # fmt: skip
    assert said["waiting"] and "Close it in the Claude app" in said["message"]
    assert chat.state(env.config, "claude", "s-1")["pending"]
    open_now["s-1"] = False  # the user closed it in the app
    state = chat.state(env.config, "claude", "s-1")
    assert state["holder"] == "ax" and state["can_send"]
    assert chat.CHATS.get("claude", "s-1") is not None


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


def test_sessions_ax_holds_are_listed_with_their_state(env, chats):
    chat.act(env.config, {"action": "send", "provider": "claude", "id": "s-1", "text": "approve",
                          "cwd": "/Users/me/Repos/demo", "name": "Fix the fetch helper"})  # fmt: skip
    until(lambda: chat.state(env.config, "claude", "s-1")["approval"])
    [held] = chat.held()
    assert (held["provider"], held["id"], held["name"], held["kind"]) == (
        "claude", "s-1", "Fix the fetch helper", "ax (background)",
    )  # fmt: skip
    assert (held["state"], held["waiting_for"]) == ("waiting", "approval")


# A second confirmation through a shared link


def test_a_message_through_a_shared_link_waits_for_a_second_yes(env, chats):
    ask = {"action": "send", "provider": "codex", "id": "t-1", "text": "Ship it", "cwd": "/repo"}
    first = chat.act(env.config, dict(ask), remote=True)
    assert first["ok"] is False and first["confirm"] and "Ship it" in first["question"]
    assert chat.CHATS.get("codex", "t-1") is None  # nothing sent yet
    with pytest.raises(ValueError, match="confirm"):
        chat.act(env.config, {**ask, "text": "Something else", "confirm": first["confirm"]},
                 remote=True)  # fmt: skip
    second = chat.act(env.config, {**ask, "confirm": first["confirm"]}, remote=True)
    assert second["ok"] and second["via"] == "ax"
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    with pytest.raises(ValueError, match="confirm"):  # each confirmation is used once
        chat.act(env.config, {**ask, "confirm": first["confirm"]}, remote=True)


def test_an_approval_through_a_shared_link_waits_for_a_second_yes_too(env, chats):
    chat.act(env.config, {"action": "send", "provider": "codex", "id": "t-1",
                          "text": "approve this", "cwd": "/repo"})  # fmt: skip
    live = until(lambda: chat.state(env.config, "codex", "t-1")["approval"])
    answer = {"action": "answer", "provider": "codex", "id": "t-1", "request": live["id"],
              "allow": True}  # fmt: skip
    first = chat.act(env.config, dict(answer), remote=True)
    assert first["ok"] is False and "run `rm -rf build`" in first["question"]
    assert chat.act(env.config, {**answer, "confirm": first["confirm"]}, remote=True)["ok"]


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


def test_the_app_sends_from_this_mac_at_once_and_asks_twice_through_a_tunnel(env, served):
    body = {"action": "send", "provider": "codex", "id": "t-1", "text": "Ship it", "cwd": "/r"}
    status, said = post(f"{served}/api/chat", body)
    assert status == 200 and said["ok"] and said["via"] == "ax"
    until(lambda: not chat.state(env.config, "codex", "t-1")["busy"])
    remote = {"X-Forwarded-For": "1.2.3.4"}
    token = app.token(env.config)
    status, _ = post(f"{served}/api/chat", body, remote)
    assert status == 401
    status, first = post(f"{served}/api/chat?token={token}", body, {**remote, "X-Ax-Token": token})
    assert status == 200 and first["ok"] is False and first["confirm"]
    status, second = post(f"{served}/api/chat", {**body, "confirm": first["confirm"]},
                          {**remote, "X-Ax-Token": token})  # fmt: skip
    assert status == 200 and second["ok"]


def test_a_refused_message_is_a_clear_error(env, served):
    status, said = post(f"{served}/api/chat", {"action": "send", "provider": "codex", "id": "t"})
    assert status == 400 and "text" in said["error"]

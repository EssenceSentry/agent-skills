"""Audit regressions exercise races and failures without making model calls."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ax import chat, chat_store
from test_chat import chats as chats


def test_concurrent_open_shares_one_startup(monkeypatch):
    started, release = threading.Event(), threading.Event()
    created = []

    def factory(*args):
        created.append(args)
        started.set()
        assert release.wait(3)
        return SimpleNamespace(alive=True, lease=None)

    monkeypatch.setattr(chat, "CodexDriver", factory)
    registry = chat.Chats(codex_command=lambda: [])
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(registry.open, "codex", "same") for _ in range(8)]
        assert started.wait(2)
        release.set()
        results = [future.result() for future in futures]
    assert len(created) == 1
    assert all(result is results[0] for result in results)


def test_unknown_ownership_preserves_input_without_starting(env, chats, monkeypatch):
    registry, _, _ = chats
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda *_: None)
    result = chat.act(
        env.config,
        {
            "action": "send",
            "provider": "claude",
            "id": "s",
            "text": "Do not lose me",
            "client_message_id": "one",
        },
    )
    assert result["waiting"]
    state = chat.state(env.config, "claude", "s")
    assert state["ownership"] == "unknown" and not state["can_send"]
    assert state["outbox"][0]["text"] == "Do not lose me"
    assert not registry.drivers


def test_failed_takeover_is_retryable_and_reads_do_not_consume_it(env, chats, monkeypatch):
    registry, _, _ = chats

    def fail(*args, **kwargs):
        raise ValueError("simulated startup failure")

    monkeypatch.setattr(registry, "open", fail)
    result = chat.act(
        env.config,
        {
            "action": "send",
            "provider": "claude",
            "id": "s",
            "text": "Keep this",
            "client_message_id": "one",
        },
    )
    assert result["status"] == "failed"
    for _ in range(3):
        state = chat.state(env.config, "claude", "s")
        assert state["outbox"][0]["text"] == "Keep this"
    chat_store.change(env.config, "claude", "s", "one", "retry")
    assert chat_store.messages(env.config, "claude", "s")[0]["status"] == "queued"


def test_outbox_id_is_idempotent_but_cannot_change_content(env):
    assert chat_store.enqueue(env.config, "claude", "s", {"text": "a"}, "one") == "one"
    chat_store.enqueue(env.config, "claude", "s", {"text": "a"}, "one")
    assert len(chat_store.messages(env.config, "claude", "s")) == 1
    with pytest.raises(ValueError, match="different content"):
        chat_store.enqueue(env.config, "claude", "s", {"text": "b"}, "one")


def test_dead_process_error_survives_driver_cleanup(env, chats):
    registry, _, _ = chats
    registry.drivers[("codex", "dead")] = SimpleNamespace(
        alive=False, busy=False, error="Authentication expired"
    )
    assert chat.state(env.config, "codex", "dead")["error"] == "Authentication expired"
    registry.drivers.clear()
    registry.failures.clear()
    assert chat.state(env.config, "codex", "dead")["error"] == "Authentication expired"


def test_permissions_respond_with_a_bounded_profile(env, chats, monkeypatch):
    registry, _, _ = chats
    driver = registry.open("codex", "t")
    writes = []
    monkeypatch.setattr(driver, "_write", writes.append)
    driver._asked(
        9001, "item/permissions/requestApproval", {"permissions": {"fileSystem": {"read": ["/a"]}}}
    )
    with pytest.raises(ValueError, match="only the permissions"):
        driver.answer(
            "codex-9001", True, response={"permissions": {"fileSystem": {"read": ["/b"]}}}
        )
    driver.answer("codex-9001", True)
    assert writes[-1] == {
        "id": 9001,
        "result": {"permissions": {"fileSystem": {"read": ["/a"]}}, "scope": "turn"},
    }


def test_mcp_form_validation_keeps_the_request_until_answered(env, chats, monkeypatch):
    registry, _, _ = chats
    driver = registry.open("codex", "t")
    writes = []
    monkeypatch.setattr(driver, "_write", writes.append)
    driver._asked(
        9002,
        "mcpServer/elicitation/request",
        {
            "requestedSchema": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            }
        },
    )
    with pytest.raises(ValueError, match="integer"):
        driver.answer(
            "codex-9002", True, response={"action": "accept", "content": {"count": "bad"}}
        )
    assert "codex-9002" in driver.asked
    driver.answer("codex-9002", True, response={"action": "accept", "content": {"count": 2}})
    assert writes[-1]["result"]["content"] == {"count": 2}


def test_parallel_claude_approvals_can_be_answered_out_of_order(env, chats, monkeypatch):
    registry, _, _ = chats
    driver = registry.open("claude", "s")
    monkeypatch.setattr(driver, "_write", lambda _: None)
    for key in ("first", "second"):
        driver._read(
            {
                "type": "control_request",
                "request_id": key,
                "request": {
                    "subtype": "can_use_tool",
                    "tool_name": "Bash",
                    "input": {"command": "pwd"},
                },
            }
        )
    driver.answer("second", True)
    assert driver.approval["id"] == "first"
    driver.answer("first", False)
    assert not driver.requests and driver.approval is None


def test_rejected_model_change_preserves_confirmed_value(env, chats, monkeypatch):
    registry, _, _ = chats
    driver = registry.open("claude", "s")
    monkeypatch.setattr(driver, "_write", lambda _: None)
    driver.settings["model"] = "confirmed"
    driver.configure({"model": "requested"})
    key = next(key for key in driver.controls if key.startswith("set_model"))
    assert driver.settings["model"] == "confirmed"
    driver._read(
        {
            "type": "control_response",
            "response": {"request_id": key, "subtype": "error", "error": "unsupported model"},
        }
    )
    assert driver.settings["model"] == "confirmed" and "unsupported" in driver.error
    assert not driver.pending_settings


def test_switching_model_clears_incompatible_effort(env, chats):
    registry, _, _ = chats
    driver = registry.open("codex", "t")
    driver.models = [{"id": "a", "efforts": ["xhigh"]}, {"id": "b", "efforts": ["low", "medium"]}]
    driver.settings.update(model="a", effort="xhigh")
    confirmed = dict(driver.settings)
    chat._configure(driver, {"model": "b"})
    assert driver.overrides["model"] == "b" and driver.overrides["effort"] is None
    assert driver.settings == confirmed


def test_completed_codex_items_do_not_concatenate_streams(env, chats):
    registry, _, _ = chats
    driver = registry.open("codex", "t")
    driver._read(
        {"method": "item/agentMessage/delta", "params": {"itemId": "one", "delta": "First."}}
    )
    driver._read(
        {"method": "item/completed", "params": {"item": {"id": "one", "type": "agentMessage"}}}
    )
    assert driver.partial == ""
    driver._read(
        {"method": "item/agentMessage/delta", "params": {"itemId": "two", "delta": "Second."}}
    )
    assert driver.partial == "Second."


def test_claude_registration_uses_only_its_confirmed_settings(env):
    from ax import claude_app

    folder = env.config.claude_app_sessions / "account" / "org"
    folder.mkdir(parents=True)
    (folder / "local_other.json").write_text(
        json.dumps({"cliSessionId": "other", "model": "wrong", "permissionMode": "auto"})
    )
    key = claude_app.register(
        env.config,
        "right",
        cwd="/repo",
        title="Right",
        settings={"model": "right-model", "effort": "low"},
    )
    record = json.loads((folder / f"{key}.json").read_text())
    assert (record["model"], record["effort"], record["permissionMode"]) == (
        "right-model",
        "low",
        "default",
    )


def test_inventory_failure_has_unknown_ownership(env, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("inventory unavailable")

    monkeypatch.setattr(chat, "_open", {})
    monkeypatch.setattr(chat.subprocess, "run", fail)
    assert chat.claude_open_elsewhere(env.config, "session") is None


def test_start_id_is_idempotent_and_survives_retry(env, chats):
    registry, _, _ = chats
    payload = {
        "action": "start",
        "provider": "codex",
        "cwd": str(env.root),
        "text": "Keep this exact start",
        "client_message_id": "start-once",
    }
    first = chat.act(env.config, payload)
    second = chat.act(env.config, payload)
    assert first["id"] == second["id"]
    assert len(registry.drivers) == 1
    rows = chat_store.messages(env.config, "codex", first["id"], all_statuses=True)
    assert len(rows) == 1 and rows[0]["text"] == payload["text"]


@pytest.mark.parametrize("key", [[], {}, "", "x" * 201])
def test_client_ids_are_validated_before_dispatch(env, key):
    with pytest.raises(ValueError, match="client_message_id"):
        chat_store.enqueue(env.config, "codex", "s", {"text": "one"}, key)


def test_editing_an_uncertain_message_does_not_silently_retry_it(env):
    chat_store.enqueue(env.config, "claude", "s", {"text": "one"}, "one")
    chat_store.settle(env.config, "claude", "s", "one", "uncertain", "No acknowledgement")
    chat_store.change(env.config, "claude", "s", "one", "edit", "edited")
    message = chat_store.messages(env.config, "claude", "s")[0]
    assert message["text"] == "edited" and message["status"] == "uncertain"


def test_rejected_steer_does_not_implicitly_start_another_turn(env, chats, monkeypatch):
    registry, _, _ = chats
    driver = registry.open("codex", "t")
    driver.busy, driver.turn = True, "current"
    called = []

    def reject(method, params):
        called.append(method)
        raise ValueError("Permission denied")

    monkeypatch.setattr(driver, "call", reject)
    with pytest.raises(ValueError, match="Permission denied"):
        driver.send("Steer")
    assert called == ["turn/steer"]


def test_unsupported_claude_controls_fail_visibly_instead_of_hanging(env, chats, monkeypatch):
    registry, _, _ = chats
    driver = registry.open("claude", "s", cwd=str(env.root))
    writes = []
    monkeypatch.setattr(driver, "_write", writes.append)
    driver._read(
        {
            "type": "control_request",
            "request_id": "unsupported",
            "request": {"subtype": "future-auth"},
        }
    )
    assert writes[-1]["response"]["subtype"] == "error"
    assert writes[-1]["response"]["request_id"] == "unsupported"
    assert "Claude Code" in driver.error


def test_approval_ids_become_stale_at_turn_completion(env, chats):
    registry, _, _ = chats
    driver = registry.open("codex", "t")
    driver._asked(999, "item/commandExecution/requestApproval", {"command": "echo smoke"})
    driver._read(
        {"method": "turn/completed", "params": {"turn": {"id": "one", "status": "completed"}}}
    )
    assert not driver.requests and not driver.asked
    with pytest.raises(ValueError, match="no longer waiting"):
        driver.answer("codex-999", True)


def test_outbox_cancellation_and_dispatch_claim_cannot_both_succeed(env):
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index in range(20):
            key = str(index)
            chat_store.enqueue(env.config, "codex", "s", {"text": key}, key)
            gate = threading.Barrier(2)

            def take(gate=gate, key=key):
                gate.wait()
                return chat_store.claim(env.config, "codex", "s", key)

            def cancel(gate=gate, key=key):
                gate.wait()
                try:
                    chat_store.change(env.config, "codex", "s", key, "cancel")
                    return True
                except ValueError:
                    return False

            claimed = pool.submit(take)
            cancelled = pool.submit(cancel)
            assert claimed.result() != cancelled.result()


def test_terminal_diagnostics_survive_runtime_object_cleanup(env, chats):
    registry, _, _ = chats
    registry.drivers[("codex", "dead-log")] = SimpleNamespace(
        alive=False,
        busy=False,
        error="Authentication expired",
        diagnostics="bounded diagnostic detail",
    )
    state = chat.state(env.config, "codex", "dead-log")
    assert (
        state["error"] == "Authentication expired" and "diagnostic detail" in state["diagnostics"]
    )
    registry.drivers.clear()
    registry.failures.clear()
    assert "diagnostic detail" in chat.state(env.config, "codex", "dead-log")["diagnostics"]

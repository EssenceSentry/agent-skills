"""Handing a Claude session to the desktop app: a record in the app's own folder, which the
app reads when it starts and then continues the session from its transcript."""

import json
import os
import stat

from ax import claude_app

LIKE = {
    "sessionId": "local_app", "cliSessionId": "app-made", "cwd": "/repo", "originCwd": "/repo",
    "createdAt": 1, "lastActivityAt": 2, "lastFocusedAt": 2, "model": "claude-opus-5-5",
    "effort": "xhigh", "isArchived": False, "title": "Made in the app", "titleSource": "auto",
    "permissionMode": "auto", "remoteMcpServersConfig": [{"name": "drive"}], "completedTurns": 9,
}  # fmt: skip


def account(env, name="acct/org", records=(LIKE,), age=0):
    folder = env.config.claude_app_sessions / name
    folder.mkdir(parents=True, exist_ok=True)
    for record in records:
        path = folder / f"{record['sessionId']}.json"
        path.write_text(json.dumps(record))
        os.utime(path, (1_000_000 + age, 1_000_000 + age))
    return folder


def test_a_session_is_added_as_the_app_would_continue_it(env):
    folder = account(env)
    local = claude_app.register(env.config, "s-1", cwd="/work", title="Fix the axis", now=5_000)
    assert local and local.startswith("local_")
    path = folder / f"{local}.json"
    record = json.loads(path.read_text())
    assert record["cliSessionId"] == "s-1" and record["sessionId"] == local
    assert record["cwd"] == record["originCwd"] == "/work"
    assert record["title"] == "Fix the axis" and record["isArchived"] is False
    assert record["lastActivityAt"] == 5_000  # first in the app's list
    # Unrelated sessions must never supply this session's model, mode or connectors.
    assert (record["model"], record["effort"], record["permissionMode"]) == (
        None, None, "default")  # fmt: skip
    assert record["remoteMcpServersConfig"] == []
    assert stat.S_IMODE(path.stat().st_mode) == 0o600  # as private as the app's own
    assert not list(folder.glob(".ax-*"))  # written whole, nothing left half-way


def test_a_session_the_app_already_has_is_not_added_twice(env):
    folder = account(env)
    first = claude_app.register(env.config, "s-1", cwd="/work", title="Fix")
    assert claude_app.register(env.config, "s-1", cwd="/work", title="Fix") == first
    assert claude_app.register(env.config, "app-made", cwd="/repo", title="x") == "local_app"
    assert len(list(folder.glob("local_*.json"))) == 2


def test_a_session_is_found_by_its_claude_code_id(env):
    account(env)
    assert claude_app.find(env.config, "app-made") == "local_app"
    assert claude_app.find(env.config, "s-1") is None
    local = claude_app.register(env.config, "s-1", cwd="/work", title="Fix")
    assert claude_app.find(env.config, "s-1") == local


def test_the_account_in_use_is_the_one_with_the_newest_session(env):
    account(env, "old/org", [{**LIKE, "sessionId": "local_old"}], age=0)
    current = account(env, "new/org", [{**LIKE, "sessionId": "local_new"}], age=100)
    local = claude_app.register(env.config, "s-1", cwd="/work", title="Fix")
    assert (current / f"{local}.json").exists()


def test_nothing_is_written_without_the_app_or_its_sessions(env):
    assert claude_app.register(env.config, "s-1", cwd="/work", title="Fix") is None
    env.config.claude_app_sessions.mkdir(parents=True)
    assert claude_app.register(env.config, "s-1", cwd="/work", title="Fix") is None
    assert not list(env.config.claude_app_sessions.rglob("*.json"))

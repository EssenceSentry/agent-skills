import io
import json

from ax import find, glue, mcp_server
from ax import sync as sync_module


def exchange(config, *messages):
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    mcp_server.serve(config, stdin=stdin, stdout=stdout, env={})
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def call(i, name, **arguments):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}  # fmt: skip


def test_the_server_lists_its_tools_and_answers_calls(env, monkeypatch):
    sync_module.sync(env.config)
    monkeypatch.setattr(find, "ready", lambda config: True)
    monkeypatch.setattr(
        find,
        "find",
        lambda config, query, **kw: [
            {"source": "code", "title": "demo/a.py:1-2", "path": "/r/demo/a.py", "snippet": query}
        ],
    )
    replies = exchange(
        env.config,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        call(3, "find", query="retry helper", sources=["code"]),
        call(4, "recall", ref="ax:11111111"),
        call(5, "recall", ref="ax:0badcafe"),
        {"jsonrpc": "2.0", "id": 6, "method": "nope"},
        {"jsonrpc": "2.0", "id": 7, "method": "ping"},
    )  # fmt: skip
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 5, 6, 7]  # no reply to a notification
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[0]["result"]["serverInfo"]["name"] == "ax"
    tools = {t["name"]: t for t in replies[1]["result"]["tools"]}
    assert set(tools) == {"find", "recall", "here"}
    assert tools["find"]["inputSchema"]["required"] == ["query"]
    assert "retry helper" in replies[2]["result"]["content"][0]["text"]
    assert "Add a retry to the fetch helper" in replies[3]["result"]["content"][0]["text"]
    assert replies[4]["result"]["isError"] is True
    assert replies[5]["error"]["code"] == -32601 and replies[6]["result"] == {}


def test_find_says_when_there_is_no_index_and_here_needs_a_conversation(env):
    replies = exchange(env.config, call(1, "find", query="x"), call(2, "here"))
    assert (
        replies[0]["result"]["isError"]
        and "ax index setup" in replies[0]["result"]["content"][0]["text"]
    )
    assert replies[1]["result"]["isError"]


def test_the_install_plan_registers_the_server_with_both_tools(env):
    changes, commands = glue.plan_mcp(env.config, ax="/bin/ax")
    [codex] = changes
    assert codex.path == env.codex_home / "config.toml"
    assert '[mcp_servers.ax]\ncommand = "/bin/ax"\nargs = ["mcp"]' in codex.after
    assert commands == [["claude", "mcp", "add", "--scope", "user", "ax", "--", "/bin/ax", "mcp"]]
    codex.path.write_text(codex.after)
    again, _ = glue.plan_mcp(env.config, ax="/bin/ax")
    assert again[0].before == again[0].after


def test_here_over_mcp_trusts_only_a_conversation_written_to_lately(env):
    import os
    import time

    from conftest import CLAUDE_SESSION

    stale = {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION}
    os.utime(env.claude_main, (1, 1))
    stdin = io.StringIO(json.dumps(call(1, "here")) + "\n")
    stdout = io.StringIO()
    mcp_server.serve(env.config, stdin=stdin, stdout=stdout, env=stale)
    assert json.loads(stdout.getvalue())["result"]["isError"] is True
    os.utime(env.claude_main, (time.time(), time.time()))
    stdin, stdout = io.StringIO(json.dumps(call(1, "here")) + "\n"), io.StringIO()
    mcp_server.serve(env.config, stdin=stdin, stdout=stdout, env=stale)
    assert json.loads(stdout.getvalue())["result"]["content"][0]["text"] == "ax:11111111"

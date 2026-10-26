"""Every live session of both tools, what each is doing, and its transcript as it grows."""

import json
import os
import sys
import threading
import time
import urllib.request
from datetime import UTC, datetime

import pytest

from ax import app, jobs, live_sessions, serve
from ax.sources import claude as claude_source
from conftest import CLAUDE_SESSION, CODEX_SESSION

NOW = datetime.now(UTC)


def claude_agents(*rows):
    """A stand-in for `claude agents --json`."""

    def run(argv):
        assert argv[:3] == ["claude", "agents", "--json"]
        return json.dumps(list(rows))

    return run


INTERACTIVE = {"pid": 11, "cwd": "/Users/me/Repos/demo", "kind": "interactive",
               "startedAt": 1793031317587, "sessionId": CLAUDE_SESSION, "name": "fetch",
               "status": "busy"}  # fmt: skip


def test_claude_sessions_come_with_their_state_and_last_words(env):
    rows = [
        INTERACTIVE,
        {**INTERACTIVE, "pid": 12, "sessionId": "aaaa", "name": "idle one", "status": "idle"},
        {"id": "bbbb", "cwd": "/Users/me/Repos/demo", "kind": "background", "startedAt": 1,
         "sessionId": "bbbb-1", "name": "asks", "status": "waiting",
         "waitingFor": "input needed", "state": "blocked"},
        {"id": "cccc", "cwd": "/Users/me/Repos/demo", "kind": "background", "startedAt": 1,
         "sessionId": "cccc-1", "name": "done for now", "state": "blocked"},
    ]  # fmt: skip
    found = {s["id"]: s for s in live_sessions.claude(env.config, run=claude_agents(*rows))}
    fetch = found[CLAUDE_SESSION]
    assert (fetch["provider"], fetch["name"], fetch["state"], fetch["project"]) == (
        "claude", "fetch", "working", "demo",
    )  # fmt: skip
    assert fetch["last"] == "Done. Here is the snippet:"
    assert found["aaaa"]["state"] == "idle" and found["aaaa"]["last"] is None
    assert (found["bbbb-1"]["state"], found["bbbb-1"]["waiting_for"]) == ("waiting", "input needed")
    assert found["cccc-1"]["state"] == "idle"


def test_claude_being_unavailable_is_an_error_not_a_crash(env):
    def run(argv):
        raise FileNotFoundError("claude")

    listed = live_sessions.listing(env.config, claude_of=lambda c: live_sessions.claude(c, run=run),
                                   codex_of=lambda c: [])  # fmt: skip
    assert listed["sessions"] == [] and "claude" in listed["errors"][0]


FAKE_SERVER = """
import json, sys
threads = json.load(open(sys.argv[1]))
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    if message["method"] == "initialize":
        result = {"userAgent": "fake"}
    elif message["method"] == "thread/list":
        result = {"data": threads, "nextCursor": None, "backwardsCursor": None}
    else:
        print(json.dumps({"id": message["id"], "error": {"message": "unknown"}}), flush=True)
        continue
    print(json.dumps({"id": message["id"], "result": result}), flush=True)
"""


def thread(tid, status, *, updated=None, path=None, name=None):
    return {"id": tid, "sessionId": tid, "name": name, "preview": f"preview {tid}",
            "cwd": "/Users/me/Repos/demo", "status": status, "path": path,
            "updatedAt": int(updated if updated is not None else NOW.timestamp()),
            "createdAt": 1, "source": "vscode"}  # fmt: skip


def rollout(tmp_path, name, *events):
    path = tmp_path / f"rollout-{name}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return str(path)


def started():
    return {"type": "event_msg", "payload": {"type": "task_started"}}


def said(text):
    return {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                 "content": [{"type": "output_text", "text": text}]}}  # fmt: skip


def completed():
    return {"type": "event_msg", "payload": {"type": "task_complete"}}


def test_codex_threads_come_from_its_app_server_with_their_state(env, tmp_path):
    working = rollout(tmp_path, "w", started(), said("Running the suite.\nMore."))
    finished = rollout(tmp_path, "f", started(), said("All green."), completed())
    old = NOW.timestamp() - 3 * 86400
    threads = [
        thread("t-approve", {"type": "active", "activeFlags": ["waitingOnApproval"]}, name="Fix"),
        thread("t-busy", {"type": "active", "activeFlags": []}),
        thread("t-open-turn", {"type": "notLoaded"}, path=working),
        thread("t-done", {"type": "notLoaded"}, path=finished),
        thread("t-old", {"type": "notLoaded"}, updated=old, path=finished),
    ]
    data = tmp_path / "threads.json"
    data.write_text(json.dumps(threads))
    script = tmp_path / "server.py"
    script.write_text(FAKE_SERVER)
    found = {s["id"]: s for s in live_sessions.codex(
        env.config, command=[sys.executable, str(script), str(data)], held=lambda tid: False)}  # fmt: skip
    assert "t-old" not in found  # untouched for days, and not open anywhere
    assert (found["t-approve"]["state"], found["t-approve"]["waiting_for"]) == (
        "waiting",
        "approval",
    )
    assert found["t-approve"]["name"] == "Fix" and found["t-busy"]["name"] == "preview t-busy"
    assert found["t-busy"]["state"] == "working"
    assert (found["t-open-turn"]["state"], found["t-open-turn"]["last"]) == (
        "working",
        "Running the suite.",
    )
    assert (found["t-done"]["state"], found["t-done"]["last"]) == ("idle", "All green.")


def test_a_codex_turn_left_open_by_a_dead_process_reads_as_idle(env, tmp_path):
    stale = rollout(tmp_path, "s", started(), said("Halfway."))
    os.utime(stale, (time.time() - 3600, time.time() - 3600))
    data = tmp_path / "threads.json"
    data.write_text(json.dumps([thread("t-stale", {"type": "notLoaded"}, path=stale)]))
    script = tmp_path / "server.py"
    script.write_text(FAKE_SERVER)
    [found] = live_sessions.codex(env.config, command=[sys.executable, str(script), str(data)],
                                  held=lambda tid: False)  # fmt: skip
    assert found["state"] == "idle"


def test_the_listing_counts_each_sessions_running_jobs(env):
    jobs.new(env.config, "score", label="Score", env={"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION})
    listed = live_sessions.listing(env.config, claude_of=lambda c: live_sessions.claude(
        c, run=claude_agents(INTERACTIVE)), codex_of=lambda c: [])  # fmt: skip
    [session] = listed["sessions"]
    assert session["jobs"] == 1 and listed["errors"] == []


# Transcripts


def test_a_transcript_is_your_messages_and_its_answers_redacted(env):
    found = live_sessions.transcript(env.config, "claude", CLAUDE_SESSION)
    assert [(e["i"], e["kind"]) for e in found["events"]] == [
        (0, "user"), (1, "assistant"), (7, "assistant"), (9, "user"),
    ]  # fmt: skip
    assert found["next"] == 10 and found["running"] == [] and found["earlier"] == 0
    assert all("AKIAABCDEFGHIJKLMNOP" not in e["text"] for e in found["events"])


def test_a_transcript_continues_from_where_the_page_left_off(env):
    whole = live_sessions.transcript(env.config, "claude", CLAUDE_SESSION)
    rest = live_sessions.transcript(env.config, "claude", CLAUDE_SESSION, after=8)
    assert [e["i"] for e in rest["events"]] == [9] and rest["first"] == 8
    none = live_sessions.transcript(env.config, "claude", CLAUDE_SESSION, after=whole["next"])
    assert none["events"] == [] and none["first"] == whole["next"]
    tail = live_sessions.transcript(env.config, "claude", CLAUDE_SESSION, limit=3)
    assert [e["i"] for e in tail["events"]] == [1, 7, 9]
    assert (tail["first"], tail["earlier"]) == (1, 1)


def tool_use(command, call="t9"):
    return {"type": "assistant", "timestamp": "2026-10-20T12:00:00Z", "message": {
        "role": "assistant", "content": [{"type": "tool_use", "id": call, "name": "Bash",
                                          "input": {"command": command}}]}}  # fmt: skip


def tool_result(call="t9"):
    return {"type": "user", "timestamp": "2026-10-20T12:01:00Z", "message": {
        "role": "user", "content": [{"type": "tool_result", "tool_use_id": call,
                                     "content": "done"}]}}  # fmt: skip


def test_only_the_command_running_now_shows_and_only_until_it_finishes(env):
    with open(env.claude_main, "a") as f:
        f.write(json.dumps(tool_use("uv run pytest -q", "t8")) + "\n")
        f.write(json.dumps(tool_result("t8")) + "\n")
        f.write(json.dumps(tool_use("make lint")) + "\n")
    found = live_sessions.transcript(env.config, "claude", CLAUDE_SESSION)
    assert [e["text"] for e in found["running"]] == ["ran `make lint`"]
    assert all(e["kind"] in ("user", "assistant") for e in found["events"])
    with open(env.claude_main, "a") as f:
        f.write(json.dumps(tool_result()) + "\n")
    assert live_sessions.transcript(env.config, "claude", CLAUDE_SESSION)["running"] == []


def test_a_transcript_is_parsed_again_only_when_its_file_grows(env, monkeypatch):
    live_sessions.clear_cache()
    calls = []
    real = claude_source.parse
    monkeypatch.setattr(claude_source, "parse", lambda path: calls.append(path) or real(path))
    live_sessions.transcript(env.config, "claude", CLAUDE_SESSION)
    live_sessions.transcript(env.config, "claude", CLAUDE_SESSION)
    assert len(calls) == 1
    with open(env.claude_main, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "more"},
                            "timestamp": "2026-10-20T12:00:00Z"}) + "\n")  # fmt: skip
    live_sessions.transcript(env.config, "claude", CLAUDE_SESSION)
    assert len(calls) == 2


def test_codex_transcripts_are_read_too(env):
    found = live_sessions.transcript(env.config, "codex", CODEX_SESSION)
    assert [e["kind"] for e in found["events"]] == ["user", "assistant", "assistant"]


def test_an_unknown_session_is_not_found(env):
    with pytest.raises(live_sessions.NotFound):
        live_sessions.transcript(env.config, "claude", "nope")
    with pytest.raises(ValueError):
        live_sessions.transcript(env.config, "gemini", CLAUDE_SESSION)


# Through the app


@pytest.fixture
def served(env, tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>ax</title>")
    monkeypatch.setattr(live_sessions, "listing", lambda config: {
        "sessions": [{"provider": "claude", "id": CLAUDE_SESSION, "name": "fetch",
                      "state": "idle", "jobs": 1}], "errors": []})  # fmt: skip
    server = serve.make_server(env.config, port=0, usage_of=lambda c: [], web=web, poll=0.05)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def test_the_app_lists_sessions_and_opens_one_with_its_job_cards(env, served):
    jobs.new(env.config, "score", label="Score", env={"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION})
    status, listed = get(f"{served}/api/sessions")
    assert status == 200 and listed["sessions"][0]["name"] == "fetch"
    status, opened = get(f"{served}/api/session?provider=claude&id={CLAUDE_SESSION}")
    assert status == 200
    assert opened["session"]["state"] == "idle" and opened["events"][0]["kind"] == "user"
    assert {e["kind"] for e in opened["events"]} == {"user", "assistant"}
    assert [c["key"] for c in opened["cards"]] == ["score"]
    status, rest = get(
        f"{served}/api/session?provider=claude&id={CLAUDE_SESSION}&after={opened['next']}"
    )
    assert status == 200 and rest["events"] == []
    assert get(f"{served}/api/session?provider=claude&id=nope")[0] == 404


def test_session_pages_need_the_token_through_a_tunnel(env, served):
    request = urllib.request.Request(f"{served}/api/sessions",
                                     headers={"X-Forwarded-For": "1.2.3.4"})  # fmt: skip
    try:
        urllib.request.urlopen(request, timeout=5)
        code = 200
    except urllib.error.HTTPError as error:
        code = error.code
    assert code == 401
    request = urllib.request.Request(f"{served}/api/sessions?token={app.token(env.config)}",
                                     headers={"X-Forwarded-For": "1.2.3.4"})  # fmt: skip
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200

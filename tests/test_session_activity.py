"""What a session is doing now, in one line, and the task list of its current turn, read
from its transcript as it grows."""

import json

import pytest

from ax import session_activity

AT = "2026-10-27T12:00:{:02d}.000Z".format


def append(path, *records):
    with path.open("a") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def prompt(n, text="Do it"):
    return {"type": "user", "timestamp": AT(n), "message": {"role": "user", "content": text}}


def tool(n, name, given, tid=None):
    return {"type": "assistant", "timestamp": AT(n), "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid or f"t{n}", "name": name, "input": given}]}}  # fmt: skip


def result(n, tid):
    return {"type": "user", "timestamp": AT(n), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}  # fmt: skip


PLAN = "mcp__ccd_turn__update_plan"
STEPS = [
    {"content": "Look at the records", "status": "in_progress"},
    {"content": "Write the tests", "status": "pending"},
    {"content": "Build it", "status": "pending"},
]


@pytest.fixture
def claude(tmp_path):
    session_activity.clear_cache()
    return tmp_path / "session.jsonl"


def read(path, provider="claude"):
    return session_activity.read(path, provider)


def statuses(found):
    return [item["status"] for item in found["tasks"]["items"]]


def test_a_running_command_is_its_description_as_the_desktop_app_says_it(claude):
    append(claude, prompt(1), tool(2, PLAN, {"items": STEPS, "scope": "continuation"}),
           tool(3, "Bash", {"command": "git status", "description": "List the uncommitted work"}))  # fmt: skip
    found = read(claude)
    assert found["activity"] == {"text": "Listing the uncommitted work", "since": AT(3)}
    assert found["tasks"] == {"items": [
        {"text": "Look at the records", "status": "in_progress"},
        {"text": "Write the tests", "status": "pending"},
        {"text": "Build it", "status": "pending"}], "explanation": None}  # fmt: skip


def test_the_list_moves_on_as_the_agent_advances_it(claude):
    append(claude, prompt(1), tool(2, PLAN, {"items": STEPS}))
    append(claude, tool(4, PLAN, {"advance": True}))
    assert statuses(read(claude)) == ["completed", "in_progress", "pending"]
    append(claude, tool(5, PLAN, {"done": [2], "start": 3}))
    assert statuses(read(claude)) == ["completed", "completed", "in_progress"]
    append(claude, tool(6, "mcp__ccd_turn__wrap_up", {"recap": "Done."}))
    assert statuses(read(claude)) == ["completed", "completed", "completed"]


def test_a_finished_command_leaves_nothing_running_and_a_new_turn_starts_without_a_list(claude):
    append(claude, prompt(1), tool(2, PLAN, {"items": STEPS}),
           tool(3, "Bash", {"command": "ls", "description": "List files"}, tid="b1"))  # fmt: skip
    append(claude, result(4, "b1"))
    found = read(claude)
    assert found["activity"] is None and found["tasks"] is not None
    append(claude, prompt(5, "Next thing"))
    assert read(claude) == {"activity": None, "tasks": None}


def test_claude_codes_own_todo_list_counts_too(claude):
    todos = [{"content": "Read the code", "status": "completed", "activeForm": "Reading"},
             {"content": "Fix it", "status": "in_progress", "activeForm": "Fixing"}]  # fmt: skip
    append(claude, prompt(1), tool(2, "TodoWrite", {"todos": todos}))
    assert read(claude)["tasks"]["items"] == [
        {"text": "Read the code", "status": "completed"},
        {"text": "Fix it", "status": "in_progress"},
    ]


@pytest.mark.parametrize(
    "name,given,said",
    [
        ("Read", {"file_path": "/repo/ui/src/lib/plus.ts"}, "Reading plus.ts"),
        ("Edit", {"file_path": "/repo/a.py", "old_string": "x", "new_string": "y"}, "Editing a.py"),
        ("Write", {"file_path": "/repo/new.md", "content": "hi"}, "Writing new.md"),
        ("Grep", {"pattern": "def act"}, "Searching for def act"),
        ("WebSearch", {"query": "codex app-server"}, "Searching the web for codex app-server"),
        ("WebFetch", {"url": "https://docs.example.com/page"}, "Fetching docs.example.com"),
        ("Agent", {"description": "Review the diff", "prompt": "…"}, "Reviewing the diff"),
        ("Bash", {"command": "npm run verify -- --reporter=dot"}, "Running `npm run verify -- --reporter=dot`"),
        ("mcp__Claude_Browser__computer", {"action": "left_click", "action_summary": "Opens the + menu"},
         "Opens the + menu"),
        ("mcp__auto-classifier-tools__snowflake_get_rows", {"job": "j"}, "Using snowflake_get_rows"),
    ],
)  # fmt: skip
def test_other_tools_say_what_they_do(claude, name, given, said):
    append(claude, prompt(1), tool(2, name, given))
    assert read(claude)["activity"] == {"text": said, "since": AT(2)}


def test_the_task_tools_themselves_are_not_what_it_is_doing(claude):
    append(claude, prompt(1), tool(2, PLAN, {"items": STEPS}),
           tool(3, "mcp__ccd_turn__wrap_up", {"recap": "x"}))  # fmt: skip
    assert read(claude)["activity"] is None


def test_reading_picks_up_where_it_left_off_and_starts_over_on_a_new_file(claude):
    append(claude, prompt(1), tool(2, "Read", {"file_path": "/a.py"}, tid="r1"))
    assert read(claude)["activity"]["text"] == "Reading a.py"
    with claude.open("a") as f:
        f.write(
            json.dumps(result(3, "r1")) + "\n" + '{"type": "assistant", "timest'
        )  # half-written
    assert read(claude)["activity"] is None
    claude.write_text(
        json.dumps(prompt(1)) + "\n" + json.dumps(tool(2, "Read", {"file_path": "/b.py"})) + "\n"
    )
    assert read(claude)["activity"]["text"] == "Reading b.py"


@pytest.mark.parametrize(
    "verb,ing",
    [
        ("List", "Listing"), ("Run", "Running"), ("Write", "Writing"), ("Check", "Checking"),
        ("Stop", "Stopping"), ("Commit", "Committing"), ("See", "Seeing"), ("Set", "Setting"),
        ("Fix", "Fixing"), ("Show", "Showing"), ("Copy", "Copying"), ("Open", "Opening"),
        ("Edit", "Editing"), ("Begin", "Beginning"), ("Read", "Reading"), ("Make", "Making"),
        ("Review", "Reviewing"), ("Map", "Mapping"), ("Format", "Formatting"),
    ],
)  # fmt: skip
def test_an_imperative_turns_into_what_it_is_doing(verb, ing):
    assert session_activity.doing(f"{verb} the thing") == f"{ing} the thing"


def test_a_description_that_doesnt_start_with_a_verb_stays_as_it_is():
    for text in ("Git status of the repo", "npm install", "Already running", "The full suite"):
        assert session_activity.doing(text) == text


# Codex


def codex_record(n, kind, payload):
    return {"timestamp": AT(n), "type": kind, "payload": payload}


def said(n, text):
    return codex_record(n, "response_item", {"type": "message", "role": "assistant",
                                             "content": [{"type": "output_text", "text": text}]})  # fmt: skip


def run(n, script, call="c1"):
    return codex_record(n, "response_item", {"type": "custom_tool_call", "name": "exec",
                                             "call_id": call, "input": script})  # fmt: skip


def ran(n, call="c1"):
    return codex_record(n, "response_item", {"type": "custom_tool_call_output", "call_id": call,
                                             "output": "ok"})  # fmt: skip


def started(n):
    return codex_record(n, "event_msg", {"type": "task_started"})


def asked(n, text="Do it"):
    return codex_record(n, "response_item", {"type": "message", "role": "user",
                                             "content": [{"type": "input_text", "text": text}]})  # fmt: skip


@pytest.fixture
def codex(tmp_path):
    session_activity.clear_cache()
    return tmp_path / "rollout.jsonl"


def test_a_codex_turn_is_doing_what_it_last_said_it_would(codex):
    append(codex, started(1), asked(1), said(2, "I'll read the notes first.\nThen the code."),
           run(3, 'text(await tools.exec_command({cmd:"cat notes.md"}));'))  # fmt: skip
    found = read(codex, "codex")
    assert found == {
        "activity": {"text": "I'll read the notes first.", "since": AT(2)},
        "tasks": None,
    }


def test_a_codex_command_without_words_before_it_says_its_command(codex):
    append(codex, started(1), asked(1),
           run(3, 'const r = await tools.exec_command({cmd:"rg -n retry src","workdir":"/repo"});'))  # fmt: skip
    assert read(codex, "codex")["activity"] == {"text": "Running `rg -n retry src`", "since": AT(3)}


def test_a_finished_codex_turn_is_doing_nothing(codex):
    append(codex, started(1), asked(1), said(2, "Checking."), run(3, "x"), ran(4),
           said(5, "Done: all checks pass."), codex_record(6, "event_msg", {"type": "task_complete"}))  # fmt: skip
    assert read(codex, "codex")["activity"] is None


def test_the_session_view_carries_the_line_and_the_list(env, monkeypatch):
    from ax import chat, live_sessions

    sid = "12121212-1212-4121-8121-121212121212"
    path = env.claude_home / "projects" / "-repo" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True)
    append(path, {**prompt(1), "cwd": "/repo", "sessionId": sid}, tool(2, PLAN, {"items": STEPS}),
           tool(3, "Bash", {"command": "pytest", "description": "Run the tests"}))  # fmt: skip
    monkeypatch.setattr(live_sessions, "cached_listing", lambda config: {"sessions": []})
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: False)
    session_activity.clear_cache()
    view = live_sessions.session_view(env.config, "claude", sid)
    assert view["activity"] == {"text": "Running the tests", "since": AT(3)}
    assert [i["text"] for i in view["tasks"]["items"]] == [s["content"] for s in STEPS]

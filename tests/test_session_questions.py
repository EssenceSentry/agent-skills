"""Questions the agents ask the user, with options: Claude's AskUserQuestion and Codex's
request_user_input (answered as its result) and request_user_input_async (answered later
by a reply message). The parsers keep each question and its answers on its event."""

import json

from ax.sources import claude, codex

AT = "2026-10-27T12:00:{:02d}.000Z".format

FORMAT = {"question": "Which format?", "header": "Format", "multiSelect": False,
          "options": [{"label": "Summary", "description": "Brief"},
                      {"label": "Detailed", "description": "Full"}]}  # fmt: skip
SECTIONS = {"question": "Which sections?", "header": "Sections", "multiSelect": True,
            "options": [{"label": "Intro", "description": ""},
                        {"label": "End", "description": ""}]}  # fmt: skip


def write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def claude_session(tmp_path, result=None, extra=None):
    records = [
        {"type": "user", "timestamp": AT(1), "cwd": "/repo", "sessionId": "s",
         "message": {"role": "user", "content": "Write the report"}},
        {"type": "assistant", "timestamp": AT(2), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
             "input": {"questions": [FORMAT, SECTIONS]}}]}},
    ]  # fmt: skip
    if result is not None:
        records.append({"type": "user", "timestamp": AT(3), "toolUseResult": extra,
                        "message": {"role": "user", "content": [result]}})  # fmt: skip
    return claude.parse(write(tmp_path / "s.jsonl", records))


def asked(session):
    return next(e for e in session.events if e.ask and e.ask.get("questions"))


def test_claudes_question_keeps_its_questions_and_the_answers_given(tmp_path):
    answered = claude_session(
        tmp_path,
        {"type": "tool_result", "tool_use_id": "q1", "content": "The user answered: ..."},
        {"questions": [FORMAT, SECTIONS],
         "answers": {"Which format?": "Summary", "Which sections?": "Intro,End"}},
    )  # fmt: skip
    ask = asked(answered).ask
    assert ask["via"] == "claude" and ask["call"] == "q1" and ask["status"] == "answered"
    assert ask["questions"][0] == {
        "id": None, "header": "Format", "question": "Which format?", "multi": False,
        "other": True, "secret": False,
        "options": [{"label": "Summary", "description": "Brief"},
                    {"label": "Detailed", "description": "Full"}],
    }  # fmt: skip
    assert ask["questions"][1]["multi"] is True
    assert ask["answers"] == [["Summary"], ["Intro", "End"]]


def test_an_older_claude_answer_is_read_from_its_words(tmp_path):
    words = ('Your questions have been answered: "Which format?"="Something else, really". '
             "You can now continue with the user's answers in mind.")  # fmt: skip
    ask = asked(claude_session(tmp_path, {"type": "tool_result", "tool_use_id": "q1",
                                          "content": words})).ask  # fmt: skip
    assert ask["status"] == "answered"
    assert ask["answers"] == [["Something else, really"], None]


def test_a_claude_question_still_waiting_or_declined_says_so(tmp_path):
    assert asked(claude_session(tmp_path)).ask | {"questions": None} == {
        "via": "claude",
        "call": "q1",
        "status": "open",
        "answers": None,
        "questions": None,
    }
    declined = claude_session(tmp_path, {"type": "tool_result", "tool_use_id": "q1",
                                         "is_error": True, "content": "The user declined"})  # fmt: skip
    assert asked(declined).ask["status"] == "declined"


def rollout(tmp_path, *items):
    meta = {"timestamp": AT(0), "type": "session_meta", "payload": {
        "id": "t", "timestamp": AT(0), "cwd": "/repo", "originator": "codex_vscode",
        "cli_version": "0.163.0", "source": "vscode"}}  # fmt: skip
    records = [meta] + [{"timestamp": AT(n + 1), "type": "response_item", "payload": item}
                        for n, item in enumerate(items)]  # fmt: skip
    return codex.parse(write(tmp_path / "rollout-2026-10-27T12-00-00-t.jsonl", records))


def call(name, call_id, arguments):
    return {"type": "function_call", "name": name, "call_id": call_id,
            "arguments": json.dumps(arguments)}  # fmt: skip


def output(call_id, value):
    return {"type": "function_call_output", "call_id": call_id, "output": json.dumps(value)}


def test_codexs_blocking_question_is_answered_by_its_result(tmp_path):
    scope = {"id": "scope", "header": "Scope", "question": "Which models?",
             "options": [{"label": "Fused (Recommended)", "description": "Fused only"},
                         {"label": "Any", "description": "Any module"}]}  # fmt: skip
    ask = asked(rollout(tmp_path, call("request_user_input", "c1", {"questions": [scope]}),
                        output("c1", {"answers": {"scope": {"answers": ["Fused (Recommended)"]}}}))).ask  # fmt: skip
    assert ask["via"] == "codex" and ask["call"] == "c1" and ask["status"] == "answered"
    assert ask["questions"] == [{
        "id": "scope", "header": "Scope", "question": "Which models?", "multi": False,
        "other": True, "secret": False,
        "options": [{"label": "Fused (Recommended)", "description": "Fused only"},
                    {"label": "Any", "description": "Any module"}],
    }]  # fmt: skip
    assert ask["answers"] == [["Fused (Recommended)"]]


def reply(call_id, index, question, answer):
    item = {"questionItemId": json.dumps(["request_user_input_async", call_id, index],
                                         separators=(",", ":")),
            "question": question, "answer": answer}  # fmt: skip
    text = f"<send_user_message_question_reply>\n{json.dumps([item])}\n</send_user_message_question_reply>\n"
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def test_codexs_async_question_is_answered_by_a_later_reply(tmp_path):
    question = {"title": "May I grant the role?", "options": ["Approve", "Keep it paused"]}
    session = rollout(tmp_path, call("request_user_input_async", "c2", {"questions": [question]}),
                      output("c2", {"accepted": True}),
                      reply("c2", 0, "May I grant the role?", "Approve"))  # fmt: skip
    ask = asked(session).ask
    assert ask["via"] == "codex-async" and ask["status"] == "answered"
    assert ask["questions"] == [{
        "id": None, "header": None, "question": "May I grant the role?", "multi": False,
        "other": True, "secret": False,
        "options": [{"label": "Approve", "description": ""},
                    {"label": "Keep it paused", "description": ""}],
    }]  # fmt: skip
    assert ask["answers"] == [["Approve"]]
    answer = session.events[-1]
    assert answer.kind == "user" and answer.text == "Approve" and answer.ask == {"reply": "c2"}


def test_codexs_async_question_waits_until_its_reply(tmp_path):
    question = {"title": "Which index?"}
    session = rollout(tmp_path, call("request_user_input_async", "c3", {"questions": [question]}),
                      output("c3", {"accepted": True}))  # fmt: skip
    ask = asked(session).ask
    assert ask["status"] == "open" and ask["answers"] is None
    assert ask["questions"][0]["options"] == []


def test_the_conversation_shows_questions_and_not_the_replies_that_answer_them(env, tmp_path):
    from ax import live_sessions

    question = {"title": "May I grant the role?", "options": ["Approve", "Keep it paused"]}
    path = (
        env.codex_home / "sessions" / "2026" / "10" / "27" / "rollout-2026-10-27T12-00-00-t-q.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"timestamp": AT(0), "type": "session_meta", "payload": {
        "id": "t-q", "timestamp": AT(0), "cwd": "/repo", "originator": "codex_vscode",
        "cli_version": "0.163.0", "source": "vscode"}}  # fmt: skip
    items = [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Go"}]},
        call("request_user_input_async", "c2", {"questions": [question]}),
        output("c2", {"accepted": True}),
        reply("c2", 0, "May I grant the role?", "Approve"),
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Granted."}],
        },
    ]
    write(path, [meta] + [{"timestamp": AT(n + 1), "type": "response_item", "payload": i}
                          for n, i in enumerate(items)])  # fmt: skip
    found = live_sessions.transcript(env.config, "codex", "t-q")
    assert [e["kind"] for e in found["events"]] == ["user", "question", "assistant"]
    assert found["events"][1]["ask"]["answers"] == [["Approve"]]


def test_a_later_reading_sends_again_the_questions_the_page_holds_open(env):
    from ax import live_sessions

    sid = "34343434-3434-4343-8343-343434343434"
    path = env.claude_home / "projects" / "-repo" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True)
    asked_records = [
        {"type": "user", "timestamp": AT(1), "cwd": "/repo", "sessionId": sid,
         "message": {"role": "user", "content": "Write the report"}},
        {"type": "assistant", "timestamp": AT(2), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
             "input": {"questions": [FORMAT]}}]}},
    ]  # fmt: skip
    write(path, asked_records)
    first = live_sessions.transcript(env.config, "claude", sid)
    held = next(e for e in first["events"] if e["kind"] == "question")
    assert held["ask"]["status"] == "open"
    answered = [
        {"type": "user", "timestamp": AT(3), "toolUseResult": {
            "questions": [FORMAT], "answers": {"Which format?": "Summary"}},
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "q1", "content": "answered"}]}},
        {"type": "assistant", "timestamp": AT(4), "message": {"role": "assistant", "content": [
            {"type": "text", "text": "A summary, then."}]}},
    ]  # fmt: skip
    write(path, asked_records + answered)
    later = live_sessions.transcript(env.config, "claude", sid, after=first["next"],
                                     again=[held["i"], 0])  # fmt: skip
    again = [e for e in later["events"] if e["i"] == held["i"]]
    assert again and again[0]["ask"]["status"] == "answered"
    assert again[0]["ask"]["answers"] == [["Summary"]]
    assert [e["kind"] for e in later["events"]] == ["question", "assistant"]  # not the prompt

"""Images in conversations: those the user pasted show in their message, and the
screenshots an agent's tools took show under the answer that followed them."""

import base64
import json
import threading
import urllib.request

import pytest

from ax import live_sessions, serve

# A 1x1 PNG and a 1x1 JPEG: real images, tiny.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)
SID = "66666666-6666-4666-8666-666666666666"
TID = "77777777-7777-4777-8777-777777777777"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def claude_image(data: bytes, media: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64(data)}}


def write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


@pytest.fixture
def claude_session(env):
    at = "2026-10-26T12:00:{:02d}Z".format
    write(env.claude_home / "projects" / "-Users-me-Repos-demo" / f"{SID}.jsonl", [
        {"type": "user", "timestamp": at(1), "cwd": "/Users/me/Repos/demo", "sessionId": SID,
         "message": {"role": "user", "content": [claude_image(PNG, "image/png"),
                                                 {"type": "text", "text": "What's wrong here?"}]}},
        {"type": "assistant", "timestamp": at(2), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "mcp__browser__screenshot", "input": {}}]}},
        {"type": "user", "timestamp": at(3), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": [{"type": "text", "text": "Took a screenshot"},
                         claude_image(JPEG, "image/jpeg")]}]}},
        {"type": "assistant", "timestamp": at(4), "message": {"role": "assistant", "content": [
            {"type": "text", "text": "The button overlaps the header."}]}},
        {"type": "user", "timestamp": at(5), "message": {"role": "user", "content": [
            claude_image(PNG, "image/png")]}},
    ])  # fmt: skip


def test_pasted_images_show_in_the_users_message_and_screenshots_under_the_answer(
    env, claude_session
):
    found = live_sessions.transcript(env.config, "claude", SID)
    user, answer, image_only = found["events"]
    assert user["text"] == "What's wrong here?" and len(user["images"]) == 1
    assert user["images"][0]["url"] == (f"/api/session/image?provider=claude&id={SID}&line=0&n=0")
    assert answer["text"] == "The button overlaps the header."
    assert [s["media"] for s in answer["shots"]] == ["image/jpeg"]
    assert image_only["kind"] == "user" and image_only["text"] == "" and image_only["images"]


def test_an_image_is_read_back_from_the_transcript(env, claude_session):
    found = live_sessions.transcript(env.config, "claude", SID)
    shot = found["events"][1]["shots"][0]
    data, media = live_sessions.image(env.config, "claude", SID, shot["line"], shot["n"])
    assert (data, media) == (JPEG, "image/jpeg")
    with pytest.raises(live_sessions.NotFound):
        live_sessions.image(env.config, "claude", SID, 0, 5)
    with pytest.raises(live_sessions.NotFound):
        live_sessions.image(env.config, "claude", SID, 99, 0)


def test_screenshots_still_waiting_for_an_answer_are_not_lost(env, claude_session):
    path = env.claude_home / "projects" / "-Users-me-Repos-demo" / f"{SID}.jsonl"
    with path.open("a") as f:
        for record in (
            {"type": "assistant", "timestamp": "2026-10-26T12:00:06Z", "message": {
                "role": "assistant", "content": [
                    {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "a.png"}}]}},
            {"type": "user", "timestamp": "2026-10-26T12:00:07Z", "message": {
                "role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2",
                                             "content": [claude_image(PNG, "image/png")]}]}},
        ):  # fmt: skip
            f.write(json.dumps(record) + "\n")
    found = live_sessions.transcript(env.config, "claude", SID)
    assert [s["media"] for s in found["shots"]] == ["image/png"]  # until an answer follows


def data_url(data: bytes, media: str) -> str:
    return f"data:{media};base64,{b64(data)}"


@pytest.fixture
def codex_thread(env):
    at = "2026-10-26T13:00:{:02d}.000Z".format
    meta = {"id": TID, "session_id": TID, "timestamp": at(0), "cwd": "/Users/me/Repos/demo",
            "originator": "codex_vscode", "cli_version": "0.163.0", "source": "vscode"}  # fmt: skip
    write(env.codex_home / "sessions" / "2026" / "10" / "26" /
          f"rollout-2026-10-26T13-00-00-{TID}.jsonl", [
        {"timestamp": at(0), "type": "session_meta", "payload": meta},
        {"timestamp": at(1), "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "Check the chart"},
                {"type": "input_image", "image_url": data_url(PNG, "image/png")}]}},
        {"timestamp": at(2), "type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "c1", "input": "shot()"}},
        {"timestamp": at(3), "type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "c1", "output": [
                {"type": "input_text", "text": "Script completed"},
                {"type": "input_image", "image_url": data_url(JPEG, "image/jpeg")}]}},
        {"timestamp": at(4), "type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "The axis is cut off."}]}},
    ])  # fmt: skip


def test_codex_images_are_found_too(env, codex_thread):
    found = live_sessions.transcript(env.config, "codex", TID)
    user, answer = found["events"]
    assert user["text"] == "Check the chart" and [i["media"] for i in user["images"]] == [
        "image/png"
    ]
    assert [s["media"] for s in answer["shots"]] == ["image/jpeg"]
    shot = answer["shots"][0]
    assert live_sessions.image(env.config, "codex", TID, shot["line"], shot["n"]) == (
        JPEG,
        "image/jpeg",
    )


@pytest.fixture
def served(env, tmp_path, claude_session, monkeypatch):
    from ax import chat

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>ax</title>")
    monkeypatch.setattr(chat, "claude_open_elsewhere", lambda config, sid: False)
    monkeypatch.setattr(live_sessions, "listing", lambda config: {"sessions": [], "errors": []})
    server = serve.make_server(env.config, port=0, usage_of=lambda c: [], web=web, poll=0.05)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_app_serves_an_image_for_the_page_and_keeps_it_cached(env, served):
    url = f"{served}/api/session/image?provider=claude&id={SID}&line=2&n=0"
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.read() == JPEG
        assert response.headers["Content-Type"] == "image/jpeg"
        assert "max-age" in response.headers["Cache-Control"]
    with pytest.raises(urllib.error.HTTPError) as missing:
        urllib.request.urlopen(f"{served}/api/session/image?provider=claude&id={SID}&line=2&n=4")
    assert missing.value.code == 404

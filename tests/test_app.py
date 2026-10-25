import json
import os
import stat
import threading
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ax import app, jobs, learn, profile, serve, todos, usage
from ax.sync import sync

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
UI = Path(__file__).parent.parent / "ui"


def fake_usage(config):
    return [
        usage.Window("claude", "weekly", 86.0, NOW + timedelta(days=2), NOW, "fresh", 10080),
        usage.Window("codex", "session", 20.0, NOW + timedelta(hours=3), NOW, "fresh", 300),
    ]


def waiting(state):
    return {(w["kind"], w["id"]): w for w in state["waiting"]}


@pytest.fixture
def queue(env):
    profile.add(env.config, "unrelated-files", rule="Leave unrelated files alone.",
                status="proposed", why="You asked for this three times.")  # fmt: skip
    profile.add(env.config, "bootstrap", rule="Use the bootstrap script.",
                review="Restated twice since you adopted it: guard it or rewrite it.")  # fmt: skip
    todos.add(env.config, "Approve the start hook", scope="global", origin="ax:48402546")
    jobs.new(env.config, "score-1", label="Score <b>rows</b>")
    jobs.new(env.config, "embed-1", total=10, unit="files", label="Embed thumbnails")
    with jobs.connect(env.config) as db:
        db.execute("UPDATE jobs SET status = 'failed', finished = updated WHERE key = 'score-1'")
        db.execute("UPDATE jobs SET check_error = 'no progress in 40 min' WHERE key = 'embed-1'")
    return env


# The Now state


def test_now_lists_what_waits_for_the_user_with_its_actions(queue):
    state = app.now_state(queue.config, usage_of=fake_usage)
    found = waiting(state)
    proposal = found[("proposal", "unrelated-files")]
    assert proposal["title"] == "Leave unrelated files alone."
    assert "three times" in proposal["detail"]
    assert proposal["note"] == "Profile/rules/unrelated-files.md"
    assert proposal["actions"] == ["accept", "reject"]
    review = found[("review", "bootstrap")]
    assert review["detail"].startswith("Restated twice")
    assert review["actions"] == ["keep", "retire", "guard"]
    todo = found[("todo", "T1")]
    assert todo["title"] == "Approve the start hook" and todo["origin"] == "ax:48402546"
    assert todo["actions"] == ["done", "drop"] and todo["note"].startswith("Todos/T1 ")
    assert found[("job", "score-1")]["detail"] == "failed"
    assert found[("job", "embed-1")]["detail"] == "no progress in 40 min"
    assert found[("usage", "claude-weekly")]["title"] == "Claude weekly: 86% used"
    assert ("usage", "codex-session") not in found
    assert state["errors"] == []


def test_now_shows_running_jobs_and_recent_conversations_by_handle(queue):
    sync(queue.config)
    state = app.now_state(queue.config, usage_of=fake_usage)
    assert [j["key"] for j in state["jobs"]] == ["embed-1"]
    assert state["conversations"]
    for c in state["conversations"]:
        assert c["handle"].startswith("ax:") and len(c["handle"]) == 11
        assert c["title"] and c["note"].endswith(".md") and not c["note"].startswith("/")
    assert {u["window"] for u in state["usage"]} == {"weekly", "session"}
    assert state["last_sync"]


def test_usage_shows_every_window_of_both_tools_even_when_one_is_unknown(env):
    def windows(config):
        return [
            usage.Window("claude", "session", 40.0, NOW + timedelta(hours=2), NOW, "fresh", 300),
            usage.Window("claude", "weekly", 86.0, NOW + timedelta(days=2), NOW, "fresh", 10080),
            usage.Window("codex", "weekly", None, None, None, "unavailable"),
        ]

    rows = app.now_state(env.config, usage_of=windows)["usage"]
    assert [(u["provider"], u["window"], u["used"]) for u in rows] == [
        ("claude", "session", 40.0),
        ("claude", "weekly", 86.0),
        ("codex", "weekly", None),
    ]
    assert rows[2]["status"] == "unavailable"
    assert rows[1]["resets_at"].startswith("2026-10-27")
    assert {"lasts", "projected_high", "runs_out_at"} <= set(rows[0])


def test_usage_includes_codex_credits_when_codex_reports_them(env):
    from test_usage import with_credits

    assert app.now_state(env.config, usage_of=fake_usage)["credits"] == []
    with_credits(env.codex_home)
    [credits] = app.now_state(env.config, usage_of=fake_usage)["credits"]
    assert credits["provider"] == "codex" and round(credits["balance"]) == 62431
    assert credits["unlimited"] is False and credits["has_credits"] is True
    assert credits["observed_at"].startswith("2026-10-21T13:06")


def test_a_window_waits_when_nearly_used_or_running_out_within_a_day(env):
    def windows(config):
        week = 10080
        return [
            # 5% in the first 8 hours of a week: at that pace it runs out in 6 days.
            usage.Window("codex", "weekly", 5.0, NOW + timedelta(days=6, hours=16), NOW, "fresh",
                         week),
            # 70% three hours into a 5-hour window: it runs out in about an hour.
            usage.Window("claude", "session", 70.0, NOW + timedelta(hours=2), NOW, "fresh", 300),
            usage.Window("claude", "weekly", 81.0, NOW + timedelta(days=3), NOW, "fresh", week),
        ]  # fmt: skip

    state = app.now_state(env.config, usage_of=windows)
    rows = {u["window"]: u for u in state["usage"] if u["provider"] == "codex"}
    assert rows["weekly"]["lasts"] is False  # the band still shows the pace warning
    assert rows["weekly"]["observed_at"].startswith("2026-10-25T12:00")
    assert {w["id"] for w in state["waiting"] if w["kind"] == "usage"} == {
        "claude-session",
        "claude-weekly",
    }


def test_a_failing_source_is_reported_not_fatal(queue):
    def broken(config):
        raise RuntimeError("no usage today")

    state = app.now_state(queue.config, usage_of=broken)
    assert any("no usage today" in e for e in state["errors"])
    assert ("proposal", "unrelated-files") in waiting(state)


# Actions


def test_actions_do_what_their_commands_do(queue):
    config = queue.config
    profile.add(config, "second", rule="Say less.", status="proposed")
    profile.add(config, "old", rule="Use the old flag.")

    said = app.act(config, "accept", {"id": "unrelated-files"})
    assert "ax profile compile --apply" in said
    rules = {r.id: r for r in profile.load_rules(config)}
    assert rules["unrelated-files"].status == "active"
    assert rules["unrelated-files"].added == date.today().isoformat()

    app.act(config, "reject", {"id": "second"})
    assert "second" in learn._ledger(config, "rejected.json")
    assert not (profile.rules_dir(config) / "second.md").exists()

    app.act(config, "keep", {"id": "bootstrap"})
    kept = next(r for r in profile.load_rules(config) if r.id == "bootstrap")
    assert not kept.review and kept.reviewed == date.today().isoformat()

    assert "ax profile compile --apply" in app.act(config, "retire", {"id": "old"})
    assert next(r for r in profile.load_rules(config) if r.id == "old").status == "retired"

    app.act(config, "todo-add", {"text": "Write eval questions", "scope": "project:agent-skills",
                                 "detail": "Twenty or so."})  # fmt: skip
    added = todos.get(config, "T2")
    assert added.scope == "project:agent-skills" and added.origin is None
    app.act(config, "todo-done", {"id": "T1"})
    app.act(config, "todo-drop", {"id": "T2"})
    assert todos.get(config, "T1").status == "done"
    assert todos.get(config, "T2").status == "dropped"


def test_guarding_reports_why_without_calling_a_model_when_there_is_nothing_to_test(queue):
    said = app.act(queue.config, "guard", {"id": "bootstrap"})
    assert "ran no commands" in said


@pytest.mark.parametrize(
    ("action", "payload", "message"),
    [
        ("accept", {"id": "nope"}, "no proposal"),
        ("keep", {"id": "unrelated-files"}, "no active rule"),
        ("todo-done", {"id": "T9"}, "no to-do T9"),
        ("todo-add", {"text": "  "}, "needs its text"),
        ("todo-add", {"text": "x", "scope": "project:../etc"}, "must be 'global'"),
        ("explode", {}, "unknown action"),
        ("accept", {}, "needs an id"),
    ],
)
def test_actions_on_missing_or_bad_input_say_why(queue, action, payload, message):
    with pytest.raises(ValueError, match=message):
        app.act(queue.config, action, payload)


# The reader


@pytest.fixture
def vault(env):
    v = env.vault
    (v / "Sessions" / "2026" / "10").mkdir(parents=True)
    (v / "Sessions" / "2026" / "10" / "Other note.md").write_text("# Other\n")
    (v / "Archive" / "2025" / "deep" / "more").mkdir(parents=True)
    (v / "Archive" / "2025" / "deep" / "more" / "other note.md").write_text("an older copy\n")
    (v / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (v / ".obsidian").mkdir()
    (v / ".obsidian" / "app.json").write_text("{}")
    (v / "Notes" / "drafts").mkdir(parents=True)
    (v / "Notes" / "drafts" / "r.md").write_text(
        "---\n"
        "title: A rule\n"
        "builds_on:\n- '[[Other note]]'\n"
        "tags: [ax]\n"
        "---\n"
        "See [[Other note]], [[Other note|the other one]] and [[Other note#Heading]].\n"
        "Not yet: [[Missing]]. Code stays: `[[in code]]`.\n\n"
        "```\n[[fenced]]\n```\n\n"
        "![[pic.png]]\n\n"
        "> [!note] Title\n> Body.\n"
    )
    return env


def test_a_note_comes_with_its_properties_and_wiki_links_resolved(vault):
    note = app.note(vault.config, "Notes/drafts/r.md")
    other = "#/read/Sessions/2026/10/Other%20note.md"
    md = note["markdown"]
    assert note["title"] == "A rule" and note["path"] == "Notes/drafts/r.md"
    assert f"See [Other note]({other}), [the other one]({other}) and [Other note]({other})" in md
    assert "[Missing](#/missing/Missing)" in md
    assert "`[[in code]]`" in md and "```\n[[fenced]]\n```" in md
    assert "![pic.png](/api/file?path=pic.png)" in md
    assert "> [!note] Title\n> Body." in md
    props = dict((p["key"], p["value"]) for p in note["properties"])
    assert props["builds_on"] == f"[Other note]({other})"
    assert props["tags"] == "ax"
    assert "title" not in props


def test_a_name_resolves_anywhere_ignoring_case_and_prefers_the_shortest_path(vault):
    (vault.vault / "Top.md").write_text("[[other NOTE]] and [[Archive/2025/deep/more/other note]]")
    md = app.note(vault.config, "Top.md")["markdown"]
    assert "[other NOTE](#/read/Sessions/2026/10/Other%20note.md)" in md
    old = "#/read/Archive/2025/deep/more/other%20note.md"
    assert f"[Archive/2025/deep/more/other note]({old})" in md


@pytest.mark.parametrize(
    "path",
    ["../config.toml", "/etc/hosts", ".obsidian/app.json", "Notes/../../config.toml",
     "pic.png", "Nope.md", "Notes", "escape.md"],
)  # fmt: skip
def test_the_reader_serves_only_notes_inside_the_vault(vault, path):
    (vault.root / "outside.md").write_text("secret")
    (vault.vault / "escape.md").symlink_to(vault.root / "outside.md")
    with pytest.raises(app.NotFound):
        app.note(vault.config, path)


def test_folders_list_their_subfolders_and_notes_and_hide_tool_folders(vault):
    top = app.folder(vault.config, "")
    assert top["path"] == "" and top["parent"] is None
    assert [f["name"] for f in top["folders"]] == ["Archive", "Notes", "Sessions"]
    assert top["notes"] == []
    drafts = app.folder(vault.config, "Notes/drafts")
    assert drafts["parent"] == "Notes"
    assert [(n["path"], n["title"]) for n in drafts["notes"]] == [("Notes/drafts/r.md", "r")]
    assert app.folder(vault.config, "Notes")["parent"] == ""
    with pytest.raises(app.NotFound):
        app.folder(vault.config, "../")
    with pytest.raises(app.NotFound):
        app.folder(vault.config, ".obsidian")


def test_only_images_inside_the_vault_are_served_as_files(vault):
    body, kind = app.file(vault.config, "pic.png")
    assert kind == "image/png" and body.startswith(b"\x89PNG")
    for path in ("Notes/drafts/r.md", "../config.toml", ".obsidian/app.json"):
        with pytest.raises(app.NotFound):
            app.file(vault.config, path)


# The server


def test_the_token_is_private_and_kept_between_runs(env):
    first = app.token(env.config)
    assert first == app.token(env.config) and len(first) >= 32
    assert stat.S_IMODE(os.stat(env.config.data / "serve-token").st_mode) == 0o600


@pytest.fixture
def served(vault, tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><html><head><title>ax</title></head>"
                                    "<body><div id=root></div></body></html>")  # fmt: skip
    (web / "assets" / "index.js").write_text("console.log(1)")
    (web / "favicon.svg").write_text("<svg/>")
    server = serve.make_server(vault.config, port=0, usage_of=fake_usage, web=web, poll=0.05)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield vault, f"http://127.0.0.1:{port}", app.token(vault.config)
    server.shutdown()
    server.server_close()


def call(url, *, token=None, cookie=None, data=None, headers=None):
    headers = dict(headers or {})
    if cookie:
        headers["Cookie"] = f"{app.COOKIE}={cookie}"
    if token:
        url += ("&" if "?" in url else "?") + f"token={token}"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_the_page_needs_the_token_and_sets_a_strict_cookie(served):
    _, base, token = served
    assert call(f"{base}/")[0] == 401
    assert call(f"{base}/", token="wrong")[0] == 401
    status, headers, body = call(f"{base}/", token=token)
    assert status == 200 and b'<meta name="ax-live" content="1">' in body
    cookie = headers["Set-Cookie"]
    assert cookie.startswith(f"{app.COOKIE}={token}") and "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert call(f"{base}/", cookie=token)[0] == 200


def test_assets_are_public_and_the_data_is_not(served, monkeypatch):
    _, base, token = served
    # The classic page's runs come from live processes; this test is about access only.
    real = serve.collect_state
    monkeypatch.setattr(
        serve, "collect_state", lambda config, **kw: real(config, usage_of=fake_usage, runs_of=list)
    )
    assert call(f"{base}/assets/index.js")[0] == 200
    assert call(f"{base}/favicon.svg")[0] == 200
    assert call(f"{base}/assets/../index.html")[0] in (400, 404)
    for path in ("/api/now", "/api/notes", "/api/state", "/classic", "/scorecard", "/events"):
        assert call(f"{base}{path}")[0] == 401, path
    status, _, body = call(f"{base}/api/now", cookie=token)
    assert status == 200 and "waiting" in json.loads(body)
    status, _, body = call(f"{base}/classic", cookie=token)
    assert status == 200 and b"<html" in body


def test_other_host_names_are_refused(served):
    _, base, token = served
    assert call(f"{base}/api/now", cookie=token, headers={"Host": "evil.example"})[0] == 403


def test_actions_need_the_token_json_and_the_apps_own_origin(served):
    env, base, token = served
    data = json.dumps({"action": "todo-add", "text": "From the app"}).encode()
    json_type = {"Content-Type": "application/json"}
    same = {**json_type, "Origin": base}
    assert call(f"{base}/api/act", data=data, headers=same)[0] == 401
    assert call(f"{base}/api/act", cookie=token, data=data,
                headers={**json_type, "Origin": "http://evil.example"})[0] == 403  # fmt: skip
    assert call(f"{base}/api/act", cookie=token, data=data,
                headers={"Content-Type": "text/plain", "Origin": base})[0] == 415  # fmt: skip
    status, _, body = call(f"{base}/api/act", cookie=token, data=data, headers=same)
    assert status == 200 and json.loads(body)["ok"] is True
    assert [t.text for t in todos.listing(env.config)] == ["From the app"]
    bad = json.dumps({"action": "accept", "id": "nope"}).encode()
    status, _, body = call(f"{base}/api/act", cookie=token, data=bad, headers=same)
    assert status == 400 and "no proposal" in json.loads(body)["error"]


def test_the_reader_endpoints(served):
    _, base, token = served
    status, _, body = call(f"{base}/api/notes?dir=Notes/drafts", cookie=token)
    assert status == 200 and json.loads(body)["notes"][0]["path"] == "Notes/drafts/r.md"
    status, _, body = call(f"{base}/api/note?path=Notes/drafts/r.md", cookie=token)
    assert status == 200 and json.loads(body)["title"] == "A rule"
    assert call(f"{base}/api/note?path=../config.toml", cookie=token)[0] == 404
    status, headers, body = call(f"{base}/api/file?path=pic.png", cookie=token)
    assert status == 200 and headers["Content-Type"] == "image/png"


def test_events_stream_the_now_state_and_each_change(served):
    env, base, token = served
    request = urllib.request.Request(f"{base}/events", headers={"Cookie": f"{app.COOKIE}={token}"})
    with urllib.request.urlopen(request, timeout=5) as stream:
        assert stream.headers["Content-Type"].startswith("text/event-stream")

        def next_state():
            for raw in stream:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    return json.loads(line[6:])
            raise AssertionError("the stream ended")

        first = next_state()
        assert ("proposal", "unrelated-files") not in waiting(first)
        todos.add(env.config, "Seen live", scope="global")
        assert ("todo", "T1") in waiting(next_state())


# The build


def test_the_shipped_app_is_built_from_the_current_ui_sources():
    if not UI.exists():
        pytest.skip("no ui/ sources in this checkout")
    stamp = app.WEB / "BUILD"
    assert stamp.exists(), "build the app: cd ui && npm run build"
    assert stamp.read_text().strip() == app.ui_digest(UI), "rebuild the app: cd ui && npm run build"
    assert (app.WEB / "index.html").exists()


def test_ax_serve_prints_the_link_with_its_token(env, monkeypatch):
    from typer.testing import CliRunner

    from ax.cli import app as cli

    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setattr(serve.ThreadingHTTPServer, "serve_forever", lambda self: None)
    result = CliRunner().invoke(cli, ["serve", "--port", "0"])
    assert result.exit_code == 0, result.output
    assert f"/?token={app.token(env.config)}" in result.output
    assert "/classic" in result.output


# Sharing through a Cloudflare quick tunnel


def test_a_shared_run_answers_its_tunnel_host_with_its_own_token(vault, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html><head></head><body></body></html>")
    server = serve.make_server(vault.config, port=0, usage_of=fake_usage, web=web,
                               share_token="run-token")  # fmt: skip
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base, tunnel = f"http://127.0.0.1:{port}", "abc.trycloudflare.com"
    through = {"Host": tunnel, "X-Forwarded-Proto": "https"}
    try:
        assert call(f"{base}/api/now", cookie="run-token", headers=through)[0] == 403
        server.allow_url(f"https://{tunnel}")
        status, headers, _ = call(f"{base}/", token="run-token", headers=through)
        assert status == 200 and "Secure" in headers["Set-Cookie"]
        assert "ax_token=run-token" in headers["Set-Cookie"]
        data = json.dumps({"action": "todo-add", "text": "From the phone"}).encode()
        json_type = {**through, "Content-Type": "application/json"}
        wrong = {**json_type, "Origin": f"http://{tunnel}"}
        assert call(f"{base}/api/act", cookie="run-token", data=data, headers=wrong)[0] == 403
        right = {**json_type, "Origin": f"https://{tunnel}"}
        assert call(f"{base}/api/act", cookie="run-token", data=data, headers=right)[0] == 200
        assert call(f"{base}/api/now", cookie="other", headers=through)[0] == 401
    finally:
        server.shutdown()
        server.server_close()


def test_a_replaced_tunnel_is_announced_until_sharing_stops():
    stop = threading.Event()
    links = iter(["https://new.trycloudflare.com", None])

    class Tunnel:
        def tick(self):
            url = next(links, None)
            if url is None:
                stop.set()
            return url

    seen = []
    serve.keep_shared(Tunnel(), seen.append, stop=stop, every=0)
    assert seen == ["https://new.trycloudflare.com"]


class FakeShare:
    def __init__(self, local_url, *, on_url=None, **kw):
        self.local_url, self.on_url, self.closed = local_url, on_url, False
        FakeShare.made = self

    def start(self):
        self.on_url("https://abc.trycloudflare.com")
        return "https://abc.trycloudflare.com"

    def tick(self):
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def cli_serve(env, monkeypatch):
    from typer.testing import CliRunner

    from ax import job_notify, job_tunnel
    from ax.cli import app as cli

    sent = []
    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setenv("AX_NTFY_TOPIC", "my-topic")
    monkeypatch.setattr(serve.ThreadingHTTPServer, "serve_forever", lambda self: None)
    monkeypatch.setattr(job_tunnel, "Share", FakeShare)
    monkeypatch.setattr(job_notify, "send", lambda ntfy, title, message, **kw: sent.append(
        (ntfy.topic, title, message, kw)))  # fmt: skip
    return lambda *args: (CliRunner().invoke(cli, ["serve", "--port", "0", *args]), sent)


def test_ax_serve_shares_through_cloudflare_and_sends_the_link_with_ntfy(env, cli_serve):
    result, sent = cli_serve("--share", "cloudflare", "--notify")
    assert result.exit_code == 0, result.output
    [(topic, title, message, options)] = sent
    link = options["click"]
    assert topic == "my-topic" and link.startswith("https://abc.trycloudflare.com/?token=")
    run_token = link.split("token=")[1]
    assert run_token != app.token(env.config) and len(run_token) >= 32
    assert link in result.output and "while" in message
    assert FakeShare.made.local_url.startswith("http://127.0.0.1:") and FakeShare.made.closed


def test_ax_serve_notify_without_sharing_sends_the_local_link_and_says_so(env, cli_serve):
    result, sent = cli_serve("--notify")
    assert result.exit_code == 0, result.output
    [(_, _, _, options)] = sent
    assert options["click"].startswith("http://127.0.0.1:")
    assert "only on this Mac" in result.output


def test_ax_serve_refuses_an_unknown_share_or_a_missing_topic(env, cli_serve, monkeypatch):
    result, _ = cli_serve("--share", "lan")
    assert result.exit_code == 2 and "cloudflare" in result.output
    monkeypatch.delenv("AX_NTFY_TOPIC")
    result, sent = cli_serve("--notify")
    assert result.exit_code == 2 and "topic" in result.output and not sent

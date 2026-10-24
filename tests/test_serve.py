import json
import threading
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from ax import exp, serve, usage
from ax.runs import Run
from ax.sync import sync

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def fake_usage(config):
    return [
        usage.Window("claude", "weekly", 82.0, NOW + timedelta(days=2), NOW, "fresh", 10080),
        usage.Window("codex", "weekly", None, None, None, "unavailable"),
    ]


def fake_runs(config):
    return [
        Run("wabc1234", "codex-worker", "codex", "Review <script>alert(1)</script>", "running",
            "demo", "gpt-5.5", NOW, NOW),
    ]  # fmt: skip


@pytest.fixture
def state(env):
    sync(env.config)
    folder = exp.init(env.vault, "demo", "pricing-study", "Find what moves rates", [], 10)
    exp.propose(
        folder,
        question="Is the CPV probe worth it?",
        decision="Use bids or not",
        outcomes=["moves → bids", "flat → budget"],
        cheaper="none",
        stop="4 h",
        est_hours=4,
        value=5,
        p_change=0.5,
    )
    return serve.collect_state(env.config, usage_of=fake_usage, runs_of=fake_runs)


def test_state_gathers_every_section(state):
    assert {w["provider"] for w in state["usage"]} == {"claude", "codex"}
    assert state["runs"][0]["state"] == "running"
    assert any("Retry for fetch helper" in s["title"] for s in state["sessions"])
    [campaign] = state["campaigns"]
    assert campaign["name"] == "pricing-study"
    assert campaign["top"][0]["question"] == "Is the CPV probe worth it?"
    assert state["errors"] == []


def test_a_failing_section_is_reported_not_fatal(env):
    def broken(config):
        raise RuntimeError("no usage today")

    state = serve.collect_state(env.config, usage_of=broken, runs_of=fake_runs)
    assert state["usage"] == []
    assert any("no usage today" in e for e in state["errors"])


def test_the_page_escapes_titles_and_flags_high_usage(state):
    html = serve.render_page(state)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "82%" in html and 'class="meter high"' in html
    assert "obsidian://open?vault=" in html


def test_the_server_answers_only_on_loopback(env, state, monkeypatch):
    monkeypatch.setattr(serve, "collect_state", lambda config, **kw: state)
    server = serve.make_server(env.config, port=0)
    host, port = server.server_address[:2]
    assert host == "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        fragment = urllib.request.urlopen(f"http://127.0.0.1:{port}/fragment").read().decode()
        data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state").read())
    finally:
        server.shutdown()
    assert "<html" in page and "pricing-study" in page
    assert "<html" not in fragment and "pricing-study" in fragment
    assert data["campaigns"][0]["name"] == "pricing-study"


def test_obsidian_links_name_the_vault_and_the_note():
    config = replace(serve.load_config("/nonexistent.toml"), vault=serve.Path("/x/My Vault"))
    link = serve.obsidian_link(config, "Sessions/2026/10/a b.md")
    assert link == "obsidian://open?vault=My%20Vault&file=Sessions%2F2026%2F10%2Fa%20b"


def test_recent_sessions_leave_out_headless_workers_and_empty_threads(env):
    from ax.model import Event, Session
    from ax.store import Store

    sync(env.config)
    with Store(env.config.db_path) as store:
        worker = Session(
            "claude", "worker-1", title="You are one of three agents", entrypoint="sdk-cli"
        )
        worker.events = [Event("user", "brief")]
        empty = Session("codex", "empty-1", title=None)
        for s in (worker, empty):
            store.save_session(
                s,
                note_path=f"{s.session_id}.md",
                raw_path=None,
                excluded=False,
                index_messages=True,
            )
    titles = [
        s["title"]
        for s in serve.collect_state(env.config, usage_of=fake_usage, runs_of=fake_runs)["sessions"]
    ]
    assert "You are one of three agents" not in titles
    assert all(titles)


def test_requests_for_other_host_names_are_refused(env, state, monkeypatch):
    # A web page can rebind its own domain to 127.0.0.1; only localhost names are served.
    import urllib.error

    monkeypatch.setattr(serve, "collect_state", lambda config, **kw: state)
    server = serve.make_server(env.config, port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/state", headers={"Host": "evil.example"}
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request)
        ok = urllib.request.Request(
            f"http://127.0.0.1:{port}/", headers={"Host": f"localhost:{port}"}
        )
        assert urllib.request.urlopen(ok).status == 200
    finally:
        server.shutdown()
    assert refused.value.code == 403

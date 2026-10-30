"""The demo: a Claude session and a Codex thread, in a home of their own, that show every
part of a session page at once. These tests keep each part in the demo as the readers
change."""

from pathlib import Path

import pytest

from ax import chat, demo, job_card, live_sessions, session_activity, session_changes, usage


@pytest.fixture
def made(tmp_path, monkeypatch):
    found = demo.build(tmp_path / "demo")
    live_sessions._paths.clear()
    session_activity.clear_cache()
    job_card.clear_cache()
    yield found
    for provider, sid in list(chat.CHATS.drivers):
        chat.CHATS.release(provider, sid)


def kinds(page):
    return [e["kind"] for e in page["events"]]


def test_the_claude_session_holds_every_kind_of_message(made):
    page = live_sessions.transcript(made.config, "claude", made.claude)
    texts = "\n".join(e["text"] for e in page["events"])
    for shown in ("\\[", "\\(", "$$", "| ---", "```python", "https://", "src/demo/app.py:",
                  "#L", "docs/report.pdf", "data/archive.zip", "docs/", "notebook.ipynb",
                  f"{demo._home(str(made.project))}/data/results.csv"):  # fmt: skip
        assert shown in texts, shown
    assert any(e["images"] for e in page["events"] if e["kind"] == "user")  # pasted
    assert any(e["shots"] for e in page["events"] if e["kind"] == "assistant")  # taken by tools
    asked = [e["ask"] for e in page["events"] if e["kind"] == "question"]
    assert {a["status"] for a in asked} == {"answered", "declined", "open"}
    assert any(len(a["questions"]) > 1 and any(q["multi"] for q in a["questions"]) for a in asked)
    assert any(a["answers"] and ["Something else entirely"] in a["answers"] for a in asked)


def test_a_claude_session_is_working_with_a_task_list(made):
    found = session_activity.read(
        live_sessions.transcript_path(made.config, "claude", made.tests), "claude"
    )
    assert found["activity"]["text"]
    assert {t["status"] for t in found["tasks"]["items"]} == {"completed", "in_progress", "pending"}


def test_the_codex_thread_holds_its_three_kinds_of_question(made):
    page = live_sessions.transcript(made.config, "codex", made.codex)
    asked = [
        (e["ask"]["via"], e["ask"]["status"]) for e in page["events"] if e["kind"] == "question"
    ]
    assert ("codex", "answered") in asked
    assert ("codex-async", "answered") in asked
    assert ("codex-async", "open") in asked
    assert any(e["images"] for e in page["events"])


def test_jobs_report_to_the_sessions_one_a_runwatch_notebook(made):
    cards = job_card.session_cards(made.config, "claude", made.claude)
    assert len(cards) == 2
    progress = next(c for c in cards if c["kind"] == "events")
    assert progress["progress"]["percent"] and progress["look"]["summary"]
    notebook = next(c for c in cards if c["kind"] == "runwatch")["notebook"]
    assert notebook["cell"]["label"] and notebook["cells"]["total"] > notebook["cells"]["done"]
    assert notebook["resources"]
    assert job_card.session_cards(made.config, "codex", made.codex)


def test_both_sessions_changed_files_this_turn(made):
    for provider, sid in (("claude", made.claude), ("codex", made.codex)):
        changed = session_changes.changes(made.config, provider, sid)
        assert changed["turn"], provider
        path = changed["turn"][0]
        before = session_changes.before(made.config, provider, sid, path, base="turn")
        assert before is not None and before != Path(path).read_text(), provider
        assert session_changes.before(made.config, provider, sid, path, base="commit") == before


def test_ax_holds_both_with_what_only_shows_live(made):
    demo.hold(made)
    claude = chat.state(made.config, "claude", made.claude)
    assert claude["question"]["questions"] and claude["approval"] is None
    assert chat.state(made.config, "claude", made.rebuild)["approval"]["detail"]
    assert chat.state(made.config, "claude", made.tests)["busy"]
    assert claude["models"] and claude["goal"]["objective"]
    planning = chat.state(made.config, "claude", made.plan)
    assert planning["approval"]["plan"] and planning["settings"]["plan"]
    codex = chat.state(made.config, "codex", made.codex)
    assert codex["busy"] and codex["partial"] and codex["tasks"]["items"]
    chat.act(made.config, {"action": "answer-question", "provider": "claude", "id": made.claude,
                           "request": claude["question"]["id"], "answers": [["Bars"], ["Q3"]]})  # fmt: skip
    assert chat.state(made.config, "claude", made.claude)["question"] is None


def test_the_listing_shows_only_the_demo(made):
    demo.hold(made)
    listed = demo.listing(made)
    assert {(s["provider"], s["id"]) for s in listed["sessions"]} == {
        ("claude", made.claude),
        ("claude", made.plan),
        ("claude", made.rebuild),
        ("claude", made.tests),
        ("codex", made.codex),
    }


def test_usage_is_the_accounts_not_the_demo_homes(made, monkeypatch):
    """The demo's Codex home holds only its own thread, which reports no usage; usage is
    the account's, as Claude's already is."""
    own = Path(__file__).parent / "fixtures" / "codex"
    monkeypatch.setattr(usage, "codex_windows", usage.codex_windows)  # put back afterwards
    monkeypatch.setattr(usage, "codex_credits", usage.codex_credits)
    monkeypatch.setattr(usage, "codex_ask", usage.codex_ask)
    monkeypatch.setattr(usage, "_asked", {})
    assert usage.codex_windows(made.config.codex_home)[0].status == "unavailable"
    demo.read_own_usage(own)
    windows = usage.codex_windows(made.config.codex_home)
    assert windows == usage.codex_windows(own) != []
    assert all(w.used is not None for w in windows)
    # Codex's answer when asked counts as your own home's too.
    asked = {"rateLimits": {"primary": {"usedPercent": 7, "windowDurationMins": 10080}}}
    server = type("Codex", (), {"request": lambda *a, **k: asked, "close": lambda self: None})()
    assert usage.codex_ask(made.config, server=server)
    assert usage.codex_windows(made.config.codex_home)[0].used == 7.0

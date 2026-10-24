from datetime import UTC, datetime

from ax.sources import claude
from conftest import CLAUDE_AGENT, CLAUDE_MAIN, CLAUDE_SESSION, CLAUDE_SUB, FIXTURES


def kinds_and_text(session):
    return [(e.kind, e.text) for e in session.events]


def test_discover_finds_main_sessions_and_nested_subagents():
    found = claude.discover(FIXTURES / "claude")
    assert sorted(found) == sorted([CLAUDE_MAIN, CLAUDE_SUB])


def test_main_session_metadata():
    s = claude.parse(CLAUDE_MAIN)
    assert (s.provider, s.session_id, s.kind, s.parent_id) == (
        "claude",
        CLAUDE_SESSION,
        "main",
        None,
    )
    assert s.title == "Retry for fetch helper"  # custom title wins over the AI title
    assert s.cwd == "/Users/me/Repos/demo"
    assert s.project == "demo"
    assert (s.branch, s.model, s.effort) == ("main", "claude-opus-5-5", "xhigh")
    assert (s.version, s.entrypoint) == ("2.1.283", "claude-desktop")
    assert s.started == datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    assert s.ended == datetime(2026, 10, 20, 12, 11, tzinfo=UTC)
    assert s.cost_usd == 0.42


def test_tokens_are_counted_once_per_api_message():
    s = claude.parse(CLAUDE_MAIN)
    assert s.tokens_in == (100 + 1000 + 5000) + (20 + 0 + 6000)
    assert s.tokens_out == 50 + 30


def test_conversation_keeps_human_text_and_drops_injected_context():
    events = kinds_and_text(claude.parse(CLAUDE_MAIN))
    assert events[0] == ("user", "Add a retry to the fetch helper")
    assert events[1] == ("assistant", "I'll read the helper first.")
    assert ("notice", "Background build finished") in events
    assert events[-1] == ("user", "Store this key: AKIAABCDEFGHIJKLMNOP for later")
    texts = " ".join(text for _, text in events)
    assert "Injected context" not in texts
    assert "injected meta message" not in texts
    assert "Private reasoning" not in texts


def test_tool_calls_become_one_line_summaries():
    tools = [e for e in claude.parse(CLAUDE_MAIN).events if e.kind == "tool"]
    assert [(t.tool, t.text, t.ok) for t in tools] == [
        ("Read", "read `src/fetch.py`", True),
        ("Edit", "edited `src/fetch.py` +3 −1", True),  # from the recorded patch
        ("Bash", "ran `uv run pytest -q`", True),
        ("Bash", "ran `make lint`", False),
        ("Agent", "started subagent “Review the retry change” (general-purpose)", True),
    ]
    assert "lint: 1 error" in tools[3].output
    assert tools[4].child == CLAUDE_AGENT


def test_unknown_and_invalid_records_are_counted():
    s = claude.parse(CLAUDE_MAIN)
    assert s.unknown == {"future-thing": 1, "invalid-json": 1}


def test_subagent_links_to_its_parent():
    s = claude.parse(CLAUDE_SUB)
    assert (s.session_id, s.kind, s.parent_id) == (CLAUDE_AGENT, "subagent", CLAUDE_SESSION)
    assert s.title == "Review the retry change"
    assert kinds_and_text(s) == [("user", "Review src/fetch.py."), ("assistant", "Looks good.")]


def test_null_usage_counts_are_treated_as_zero(tmp_path):
    path = tmp_path / CLAUDE_MAIN.name
    path.write_text(
        CLAUDE_MAIN.read_text().replace(
            '"cache_creation_input_tokens": 1000', '"cache_creation_input_tokens": null'
        )
    )
    assert claude.parse(path).tokens_in == (100 + 5000) + (20 + 6000)

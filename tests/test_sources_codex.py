import os
import shutil
from datetime import UTC, datetime

import zstandard

from ax.sources import codex
from conftest import (
    CODEX_FORK,
    CODEX_FORKED,
    CODEX_GUARD,
    CODEX_MAIN,
    CODEX_SESSION,
    CODEX_SUB,
    CODEX_SUBAGENT,
    FIXTURES,
)

TITLES = {CODEX_SESSION: "Fix flaky fetch tests"}


def test_discover_finds_rollouts():
    assert sorted(codex.discover(FIXTURES / "codex")) == sorted(
        [CODEX_MAIN, CODEX_SUB, CODEX_GUARD, CODEX_FORKED]
    )


def test_thread_titles_come_from_the_session_index():
    assert codex.read_titles(FIXTURES / "codex") == TITLES


def test_main_session_metadata():
    s = codex.parse(CODEX_MAIN, TITLES)
    assert (s.provider, s.session_id, s.kind, s.parent_id) == ("codex", CODEX_SESSION, "main", None)
    assert s.title == "Fix flaky fetch tests"
    assert (s.cwd, s.project, s.branch) == ("/Users/me/Repos/demo", "demo", "main")
    assert (s.model, s.effort, s.version, s.entrypoint) == (
        "gpt-5.5",
        "high",
        "0.163.0",
        "codex_vscode",
    )
    assert s.started == datetime(2026, 10, 20, 13, 0, tzinfo=UTC)
    assert s.ended == datetime(2026, 10, 20, 13, 9, tzinfo=UTC)
    assert (s.tokens_in, s.tokens_out) == (1000, 300)


def test_conversation_strips_ide_wrapper_and_injected_context():
    events = [(e.kind, e.text) for e in codex.parse(CODEX_MAIN, TITLES).events]
    assert events[0] == ("user", "Make the tests pass")
    assert ("assistant", "Running the tests first.") in events
    assert ("assistant", "Fixed the retry; tests pass.") in events
    assert ("notice", "turn interrupted") in events
    assert ("notice", "context compacted") in events
    texts = " ".join(text for _, text in events)
    assert "environment_context" not in texts
    assert "AGENTS.md" not in texts
    assert "Developer instructions" not in texts


def test_tool_calls_become_one_line_summaries():
    tools = [e for e in codex.parse(CODEX_MAIN, TITLES).events if e.kind == "tool"]
    assert [(t.tool, t.text, t.ok) for t in tools] == [
        ("exec_command", "ran `uv run pytest -q`", False),
        ("apply_patch", "patched `src/fetch.py` +2 −1", True),
    ]
    assert "1 failed" in tools[0].output


def test_unknown_records_are_counted():
    s = codex.parse(CODEX_MAIN, TITLES)
    assert s.unknown == {"future_record": 1, "response_item:future_item": 1}


def test_subagent_links_to_its_parent_and_titles_from_first_prompt():
    s = codex.parse(CODEX_SUB, TITLES)
    assert (s.session_id, s.kind, s.parent_id) == (CODEX_SUBAGENT, "subagent", CODEX_SESSION)
    assert s.title == "Check the retry loop."


def test_subagent_skips_the_parent_history_it_inherits():
    s = codex.parse(CODEX_SUB, TITLES)
    assert s.started == datetime(2026, 10, 20, 13, 5, 30, tzinfo=UTC)
    assert [(e.kind, e.text, e.tool) for e in s.events] == [
        ("user", "Check the retry loop.", None),
        ("message", "Please review the retry loop.", "/root → /root/reviewer"),
        ("assistant", "The loop returns early.", None),
    ]


def test_forked_threads_take_their_id_from_the_file_name():
    s = codex.parse(CODEX_FORKED, TITLES)
    assert (s.session_id, s.kind, s.parent_id) == (CODEX_FORK, "main", None)
    assert s.title == "Try a different retry strategy"


def test_guardian_reviews_are_marked():
    assert codex.parse(CODEX_GUARD, TITLES).kind == "guardian"


def test_compressed_rollouts_parse_like_plain_ones(tmp_path):
    compressed = tmp_path / (CODEX_MAIN.name + ".zst")
    compressed.write_bytes(zstandard.ZstdCompressor().compress(CODEX_MAIN.read_bytes()))
    plain = tmp_path / CODEX_MAIN.name
    shutil.copy(CODEX_MAIN, plain)
    a, b = codex.parse(plain, TITLES), codex.parse(compressed, TITLES)
    assert [(e.kind, e.text) for e in a.events] == [(e.kind, e.text) for e in b.events]
    assert a.session_id == b.session_id


def test_fields_of_an_unexpected_type_are_dropped(tmp_path):
    path = tmp_path / CODEX_MAIN.name
    path.write_text(
        CODEX_MAIN.read_text().replace('"effort": "high"', '"effort": {"level": "high"}')
    )
    assert codex.parse(path, TITLES).effort is None


def test_a_rollout_in_both_live_and_archived_folders_is_read_once(tmp_path):
    home = tmp_path / "codex"
    shutil.copytree(FIXTURES / "codex", home)
    archived = home / "archived_sessions" / CODEX_MAIN.name
    archived.parent.mkdir()
    shutil.copy(CODEX_MAIN, archived)
    live = home / CODEX_MAIN.relative_to(FIXTURES / "codex")
    os.utime(archived, (1, 1))
    found = codex.discover(home)
    assert archived not in found
    assert live in found

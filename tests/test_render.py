from pathlib import Path

import yaml

from ax.render import note_relpath, render, safe_title
from ax.sources import claude, codex
from conftest import CLAUDE_AGENT, CLAUDE_MAIN, CLAUDE_SUB, CODEX_MAIN, CODEX_SESSION, CODEX_SUB


def split_note(text):
    assert text.startswith("---\n")
    front, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(front), body


def test_main_notes_are_filed_by_month_with_the_title_in_the_name():
    assert note_relpath(claude.parse(CLAUDE_MAIN)) == Path(
        "Sessions/2026/10/2026-10-20 claude demo - Retry for fetch helper (11111111).md"
    )
    titles = {CODEX_SESSION: "Fix flaky fetch tests"}
    assert note_relpath(codex.parse(CODEX_MAIN, titles)) == Path(
        "Sessions/2026/10/2026-10-20 codex demo - Fix flaky fetch tests (22222222).md"
    )


def test_subagent_notes_have_stable_id_names():
    assert note_relpath(claude.parse(CLAUDE_SUB)) == Path(
        f"Sessions/2026/10/_subagents/claude {CLAUDE_AGENT}.md"
    )


def test_titles_are_made_safe_for_file_names():
    assert safe_title('Fix: a/b *now*? "x" <y> | #z ^[w]') == "Fix a b now x y z w"
    assert len(safe_title("word " * 40)) <= 80
    assert safe_title("   ") == "Untitled"


def test_frontmatter_carries_the_session_metadata():
    front, _ = split_note(render(claude.parse(CLAUDE_MAIN), raw_path="~/raw/x.jsonl.zst"))
    assert front["type"] == "session"
    assert front["provider"] == "claude"
    assert front["kind"] == "main"
    assert front["session_id"] == "11111111-1111-4111-8111-111111111111"
    assert front["title"] == "Retry for fetch helper"
    assert front["project"] == "demo"
    assert front["model"] == "claude-opus-5-5"
    assert front["user_turns"] == 2
    assert front["tool_calls"] == 5
    assert front["tokens_in"] == 12120
    assert front["tokens_out"] == 80
    assert front["cost_usd"] == 0.42
    assert front["raw"] == "~/raw/x.jsonl.zst"
    assert front["tags"] == ["session", "claude", "demo"]
    assert "parent" not in front


def test_body_is_a_readable_transcript():
    _, body = split_note(render(claude.parse(CLAUDE_MAIN)))
    assert "# Retry for fetch helper" in body
    assert "Add a retry to the fetch helper" in body
    assert "- read `src/fetch.py`" in body
    assert "- edited `src/fetch.py` +3 −1" in body
    assert "- ran `make lint` · failed: lint: 1 error" in body
    assert f"[[claude {CLAUDE_AGENT}|" in body
    assert "Background build finished" in body
    assert "Private reasoning" not in body


def test_secrets_are_redacted_in_the_note():
    text = render(claude.parse(CLAUDE_MAIN))
    assert "AKIAABCDEFGHIJKLMNOP" not in text
    assert "[REDACTED:aws-access-key]" in text


def test_unbalanced_code_fences_are_closed():
    _, body = split_note(render(claude.parse(CLAUDE_MAIN)))
    fences = [line for line in body.splitlines() if line.lstrip().startswith("```")]
    assert len(fences) % 2 == 0


def test_subagent_notes_link_back_to_the_parent():
    front, body = split_note(render(claude.parse(CLAUDE_SUB), parent_note="Parent note"))
    assert front["kind"] == "subagent"
    assert front["parent"] == "[[Parent note]]"
    assert "[[Parent note]]" in body


def test_messages_between_agents_are_quoted_with_sender_and_recipient():
    _, body = split_note(render(codex.parse(CODEX_SUB, {})))
    assert "> [!quote] /root → /root/reviewer\n> Please review the retry loop." in body


def test_ids_that_share_a_time_prefix_get_different_note_names():
    a = codex.parse(CODEX_MAIN, {})
    b = codex.parse(CODEX_MAIN, {})
    a.session_id = "01a0fe73-a26f-7c23-8c30-000000000001"
    b.session_id = "01a0fe73-a26f-7c23-8c30-000000000002"
    assert note_relpath(a) != note_relpath(b)


def test_working_directory_fields_are_redacted():
    session = claude.parse(CLAUDE_MAIN)
    session.cwd = "/tmp/AKIAABCDEFGHIJKLMNOP"
    session.branch = "AKIAABCDEFGHIJKLMNOP"
    assert "AKIAABCDEFGHIJKLMNOP" not in render(session)

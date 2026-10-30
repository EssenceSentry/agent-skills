import json

import pytest
import yaml
from typer.testing import CliRunner

from ax import find
from ax import sync as sync_module
from ax.cli import app
from ax.config import load
from ax.store import Store
from conftest import CLAUDE_SESSION, CODEX_SESSION


@pytest.fixture
def indexed(env):
    sync_module.sync(env.config)
    with Store(env.config.db_path) as store:
        notes = {r["session_id"]: r["note_path"] for r in store.all_sessions() if r["note_path"]}
    env.notes = notes
    return env


def qmd_hit(collection, rel, title="T", snippet="@@ -1,2 @@ (0 before, 1 after)\nthe passage"):
    return {"docid": "#abc", "score": 0.9, "file": f"qmd://{collection}/{rel}?index=ax",
            "line": 3, "title": title, "snippet": snippet}  # fmt: skip


class Runner:
    def __init__(self, qmd=()):
        self.qmd, self.calls = list(qmd), []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return json.dumps(self.qmd)


def note_rel(env, session_id):
    return env.notes[session_id].removeprefix("Sessions/")


def test_setup_writes_a_qmd_collection_for_each_tool_s_conversations_and_memories(indexed):
    path = find.write_qmd_config(indexed.config)
    assert path == indexed.root / "qmd" / "ax.yml"
    found = yaml.safe_load(path.read_text())["collections"]
    assert set(found) == {"claude", "codex", "subagents", "claude-memory", "codex-memory"}
    assert found["claude"]["path"] == str(indexed.vault / "Sessions")
    assert (
        "claude" in found["claude"]["pattern"] and "**/_subagents/**" in found["claude"]["ignore"]
    )
    assert found["subagents"]["includeByDefault"] is False
    assert found["claude-memory"]["path"] == str(indexed.claude_home / "projects")
    assert all(c["context"]["/"] for c in found.values())


def test_hits_are_merged_labelled_and_carry_handles(indexed, monkeypatch):
    runner = Runner(
        qmd=[qmd_hit("claude", note_rel(indexed, CLAUDE_SESSION), "Add retries"),
             qmd_hit("claude-memory", "-Users-me-Repos-demo/memory/retries.md", "Retries")],
    )  # fmt: skip
    monkeypatch.setattr(find, "_run", runner)
    hits = find.find(indexed.config, "where is the fetch retry helper", limit=5)
    assert [h["source"] for h in hits] == ["conversation", "memory"]
    talk, memory = hits
    assert talk["handle"] == "ax:11111111" and talk["project"] == "demo"
    assert talk["session"] == "11111111-1111-4111-8111-111111111111"  # to open it by
    assert talk["started"].startswith(talk["date"])  # when it began, to tell it from its twins
    assert talk["path"] == str(indexed.vault / indexed.notes[CLAUDE_SESSION])
    assert talk["snippet"] == "You: Add a retry to the fetch helper"  # what was said, from the note
    assert memory["path"].endswith("memory/retries.md")
    [qmd_call] = runner.calls  # qmd alone answers
    assert qmd_call[1:5] == ["--index", "ax", "query", "lex: where is the fetch retry helper\n"
                             "vec: where is the fetch retry helper"]  # fmt: skip
    assert "--no-rerank" in qmd_call
    assert {"claude", "codex", "claude-memory", "codex-memory"} == {
        qmd_call[i + 1] for i, a in enumerate(qmd_call) if a == "-c"}  # fmt: skip


def test_only_conversations_and_memories_are_searched(indexed, monkeypatch):
    runner = Runner(qmd=[qmd_hit("notes", "Profile/rules/tabs.md")])  # an older index's note
    monkeypatch.setattr(find, "_run", runner)
    assert find.find(indexed.config, "tabs", sources=["notes", "docs", "code"]) == []
    assert runner.calls == []  # nothing left to ask
    assert find.find(indexed.config, "tabs") == []  # nor shown when qmd still has it


def test_filters_apply_through_the_archive(indexed, monkeypatch):
    runner = Runner(
        qmd=[qmd_hit("claude", note_rel(indexed, CLAUDE_SESSION)),
             qmd_hit("codex", note_rel(indexed, CODEX_SESSION))],
    )  # fmt: skip
    monkeypatch.setattr(find, "_run", runner)
    only_claude = find.find(indexed.config, "q", sources=["conversations"], provider="claude")
    assert [h["handle"] for h in only_claude] == ["ax:11111111"]
    assert find.find(indexed.config, "q", sources=["conversations"], since="2030-01-01") == []


def test_a_fast_search_skips_the_models(indexed, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(find, "_run", runner)
    find.find(indexed.config, "q", sources=["conversations"], fast=True)
    assert runner.calls[0][3] == "search"


def test_qmd_snippets_leave_out_hunk_headers_and_line_numbers():
    passage = (
        "81: @@ -80,4 @@ (79 before, 177 after)\n82: \n83: Do not build it.\n84: Keep it small."
    )
    assert find._snippet(passage) == "Do not build it. Keep it small."
    assert find._snippet("@@ -1,2 @@ (0 before, 1 after)\nthe passage") == "the passage"
    mentioned = "12: the diff starts with @@ -1,2 @@ in the patch"  # not a header: words before it
    assert find._snippet(mentioned) == "the diff starts with @@ -1,2 @@ in the patch"


def test_snippets_read_markdown_escapes_as_the_characters_they_stand_for(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("Keep the cache\\_id, and \\*never\\* the key.\n")
    assert find._passage(note, "cache id", "memory") == "Keep the cache_id, and *never* the key."
    hunk = "@@ -1,2 @@ (0 before, 1 after)\n1: the cache\\_id"
    assert find._snippet(hunk) == "the cache_id"


CONVERSATION = """---
session_id: "s-1"
title: "ax"
project: "demo"
---
# ax

Claude · demo · 2026-10-24 13:28–17:36 · claude-opus-5-5

Builds on: [[2026-10-20 claude demo - other (abc)|other]]

## 13:28 · You

Why is the **status bar** usage stale?

### Claude

- ran `grep usage src`
- read `/repo/src/usage.py`

The `codex` reading comes from its logs, so the usage goes stale between turns.
"""


def test_a_conversation_shows_what_was_said_that_matched_not_its_note_header(tmp_path):
    note = tmp_path / "note.md"
    note.write_text(CONVERSATION)
    assert find._passage(note, "codex usage", "conversation") == (
        "Claude: The codex reading comes from its logs, so the usage goes stale between turns."
    )
    assert (
        find._passage(note, "status bar", "conversation")
        == "You: Why is the status bar usage stale?"
    )
    # Found by meaning, not by these words: what was asked first.
    assert (
        find._passage(note, "freshness", "conversation")
        == "You: Why is the status bar usage stale?"
    )


def test_a_memory_shows_what_it_is_about(tmp_path):
    memory = tmp_path / "agent-tooling.md"
    memory.write_text('---\nname: agent-tooling\ndescription: "The agent layer: what is built"\n'
                      "metadata:\n  type: project\n---\n\nax is built.\n")  # fmt: skip
    assert find._passage(memory, "ax", "memory") == "The agent layer: what is built"


def test_a_passage_shows_its_matching_line_as_plain_words(tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("# Agent skills\n\n| Skill | What |\n| --- | --- |\n"
                   "| [ax](skills/ax/SKILL.md) | The map of every `ax` command |\n")  # fmt: skip
    assert find._passage(doc, "ax command", "memory") == "ax · The map of every ax command"
    assert find._passage(doc, "nothing here", "memory") is None  # qmd's own passage, then
    rules = tmp_path / "CLAUDE.md"
    rules.write_text("<!-- ax:profile:start · generated by ax -->\n## Working rules\n\n"
                     "- Search with ax find\n<!--\nax notes\n-->\n")  # fmt: skip
    assert find._passage(rules, "ax", "memory") == "Search with ax find"  # never a comment


def test_a_long_passage_is_cut_around_what_matched(tmp_path):
    doc = tmp_path / "long.md"
    doc.write_text("word " * 80 + "the retry helper waits " + "word " * 80 + "\n")
    found = find._passage(doc, "retry helper", "memory")
    assert found.startswith("…") and found.endswith("…") and "retry helper" in found
    assert len(found) <= find.PASSAGE + 2


def test_a_memory_copied_for_the_other_tool_is_left_out_beside_the_memory(indexed, monkeypatch):
    runner = Runner(qmd=[
        qmd_hit("claude-memory", "-Users-me-Repos-demo/memory/retries.md", "retries"),
        qmd_hit("codex-memory", "notes/claude-Repos-demo-retries.md", "From Claude Code's memory: retries"),
    ])  # fmt: skip
    monkeypatch.setattr(find, "_run", runner)
    hits = find.find(indexed.config, "retries", sources=["memories"])
    assert [h["title"] for h in hits] == ["retries"]
    assert hits[0]["project"] == "demo"  # the project whose memory it is


def test_the_search_daemon_is_started_when_down_and_not_again_at_once(indexed, monkeypatch):
    find.write_qmd_config(indexed.config)
    monkeypatch.setattr(find, "_tried", {})
    state = {"up": False, "starts": 0}

    def start(config):
        state["starts"] += 1
        state["up"] = True

    def up(config):
        return state["up"]

    assert find.keep_daemon(indexed.config, start=start, up=up, now=1000.0)
    assert find.keep_daemon(indexed.config, start=start, up=up, now=1001.0)  # still up
    state["up"] = False  # it went away
    assert not find.keep_daemon(indexed.config, start=start, up=up, now=1100.0)  # tried lately
    assert find.keep_daemon(indexed.config, start=start, up=up, now=1400.0)
    assert state["starts"] == 2


def test_no_search_daemon_is_started_before_the_index_is_set_up(indexed, monkeypatch):
    monkeypatch.setattr(find, "_tried", {})

    def start(config):
        raise AssertionError("started without an index")

    assert not find.keep_daemon(indexed.config, start=start, up=lambda c: False, now=1.0)


def test_the_command_prints_hits_and_says_when_setup_is_missing(indexed, monkeypatch):
    runner = Runner(qmd=[qmd_hit("claude", note_rel(indexed, CLAUDE_SESSION), "Add retries")])
    monkeypatch.setattr(find, "_run", runner)
    env = {"AX_CONFIG": str(indexed.config_path)}
    missing = CliRunner().invoke(app, ["find", "retries", "--in", "conversations"], env=env)
    assert missing.exit_code == 2 and "ax index setup" in missing.output
    find.write_qmd_config(indexed.config)
    shown = CliRunner().invoke(app, ["find", "retries", "--in", "conversations"], env=env)
    assert shown.exit_code == 0, shown.output
    assert "[conversation]" in shown.output and "ax:11111111" in shown.output
    as_json = CliRunner().invoke(
        app, ["find", "retries", "--in", "conversations", "--json"], env=env
    )
    assert json.loads(as_json.output)[0]["handle"] == "ax:11111111"


def test_evaluation_counts_questions_answered_in_the_top_k(indexed, monkeypatch, tmp_path):
    runner = Runner(qmd=[qmd_hit("claude", note_rel(indexed, CLAUDE_SESSION))])
    monkeypatch.setattr(find, "_run", runner)
    cases = tmp_path / "questions.yml"
    cases.write_text(yaml.safe_dump([
        {"query": "retries", "expect": "ax:11111111"},
        {"query": "nothing", "expect": "ax:deadbeef"}]))  # fmt: skip
    report = find.evaluate(indexed.config, find.load_cases(cases), k=5)
    assert report["found"] == 1 and report["total"] == 2
    assert report["misses"] == [{"query": "nothing", "expect": "ax:deadbeef"}]


def test_sync_refreshes_the_index_when_it_wrote_notes(env, tmp_path, monkeypatch):
    refreshed = []

    def refresh(config):  # records its run as the real refresh does
        refreshed.append(config)
        find._stamp(config).touch()

    monkeypatch.setattr(find, "refresh", refresh)
    run = {"AX_CONFIG": str(env.config_path)}
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert refreshed == []  # no index yet
    find.write_qmd_config(load(env.config_path))
    (env.vault / "Sessions").mkdir(exist_ok=True)
    for note in (env.vault / "Sessions").rglob("*.md"):
        note.unlink()  # so the next sync writes them again
    with Store(env.config.db_path) as store:
        store.db.execute("DELETE FROM files")
        store.commit()
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert len(refreshed) == 1
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert len(refreshed) == 1  # nothing written, nothing to refresh


def test_setup_indexes_and_embeds_everything(indexed, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(find, "_run", runner)
    find.setup(indexed.config, say=lambda text: None)
    assert [c[0] for c in runner.calls] == ["qmd", "qmd"]
    assert [c[3:] for c in runner.calls] == [["update"], ["embed", "--timeout", "0"]]


def test_a_refresh_drops_the_collections_an_older_setup_wrote(indexed, monkeypatch):
    monkeypatch.setattr(find, "_run", Runner())
    path = find.qmd_config(indexed.config)
    path.parent.mkdir(parents=True, exist_ok=True)
    older = {"path": str(indexed.vault), "pattern": "**/*.md"}
    path.write_text(yaml.safe_dump({"collections": {"notes": older, "docs-demo": older}}))
    find.refresh(indexed.config)
    found = yaml.safe_load(path.read_text())["collections"]
    assert "notes" not in found and "docs-demo" not in found and "claude" in found


def test_a_running_qmd_daemon_answers_without_loading_models_again(indexed, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(find, "_run", runner)
    posted = []

    def post(url, body, timeout):
        posted.append((url, body))
        return {"results": [qmd_hit("claude", note_rel(indexed, CLAUDE_SESSION))]}

    monkeypatch.setattr(find, "_post", post)
    monkeypatch.setattr(find, "_daemon_up", lambda config: True)
    [hit] = find.find(indexed.config, "retries", sources=["conversations"])
    assert hit["handle"] == "ax:11111111" and runner.calls == []
    url, body = posted[0]
    assert url.endswith(":8181/query") and body["collections"] == ["claude", "codex"]
    # By words and by meaning, not reranked: the reranker took five of a search's seven seconds.
    assert [s["type"] for s in body["searches"]] == ["lex", "vec"] and body["rerank"] is False


def test_sync_refreshes_a_stale_index_even_without_new_notes(env, monkeypatch):
    refreshed = []

    def refresh(config):  # records its run as the real refresh does
        refreshed.append(config)
        find._stamp(config).touch()

    monkeypatch.setattr(find, "refresh", refresh)
    run = {"AX_CONFIG": str(env.config_path)}
    find.write_qmd_config(load(env.config_path))
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert len(refreshed) == 1  # first sync wrote notes
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert len(refreshed) == 1  # nothing new, refreshed moments ago
    monkeypatch.setattr(find, "stale", lambda config: True)
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert len(refreshed) == 2  # an hour on: edited memories get picked up

import json
from dataclasses import replace

import yaml
import zstandard

from ax.store import Store
from ax.sync import sync
from conftest import CLAUDE_AGENT, CLAUDE_SESSION, CODEX_GUARDIAN

CLAUDE_NOTE = "Sessions/2026/10/2026-10-20 claude demo - Retry for fetch helper (11111111).md"
CLAUDE_SUB_NOTE = f"Sessions/2026/10/_subagents/claude {CLAUDE_AGENT}.md"
CODEX_NOTE = "Sessions/2026/10/2026-10-20 codex demo - Fix flaky fetch tests (22222222).md"
CODEX_SUB_NOTE = "Sessions/2026/10/_subagents/codex 33333333-3333-4333-8333-333333333333.md"
CODEX_FORK_NOTE = (
    "Sessions/2026/10/2026-10-20 codex demo - Try a different retry strategy (55555555).md"
)
ALL_NOTES = sorted([CLAUDE_NOTE, CLAUDE_SUB_NOTE, CODEX_NOTE, CODEX_SUB_NOTE, CODEX_FORK_NOTE])


def notes(vault):
    return sorted(str(p.relative_to(vault)) for p in vault.rglob("*.md"))


def frontmatter(path):
    return yaml.safe_load(path.read_text().split("\n---\n", 1)[0][4:])


def test_first_sync_renders_every_conversation_but_not_guardian_reviews(env):
    report = sync(env.config)
    assert report.discovered == 6
    assert report.parsed == 6
    assert report.written == 5
    assert (report.renamed, report.removed) == (0, 0)
    assert report.errors == []
    assert notes(env.vault) == ALL_NOTES
    with Store(env.config.db_path) as store:
        assert store.session(f"codex:{CODEX_GUARDIAN}")["kind"] == "guardian"
        assert sum(row["n"] for row in store.counts()) == 6  # one session per file


def test_subagent_notes_do_not_repeat_the_parent_conversation(env):
    sync(env.config)
    text = (env.vault / CODEX_SUB_NOTE).read_text()
    assert "Check the retry loop." in text
    assert "Make the tests pass" not in text
    assert "Make the tests pass" in (env.vault / CODEX_NOTE).read_text()


def test_a_parser_upgrade_resyncs_everything(env):
    sync(env.config)
    with Store(env.config.db_path) as store:
        store.set_meta("parser_version", "0")
    assert sync(env.config).parsed == 6
    assert sync(env.config).parsed == 0


def test_parent_and_child_notes_link_to_each_other(env):
    sync(env.config)
    sub = frontmatter(env.vault / CLAUDE_SUB_NOTE)
    assert sub["parent"] == f"[[{CLAUDE_NOTE.rsplit('/', 1)[1][:-3]}]]"
    assert f"[[claude {CLAUDE_AGENT}|" in (env.vault / CLAUDE_NOTE).read_text()
    codex_sub = frontmatter(env.vault / CODEX_SUB_NOTE)
    assert codex_sub["parent"] == f"[[{CODEX_NOTE.rsplit('/', 1)[1][:-3]}]]"


def test_raw_transcripts_are_backed_up_compressed(env):
    sync(env.config)
    backup = env.config.raw_dir / "claude" / env.claude_main.relative_to(env.claude_home)
    backup = backup.with_name(backup.name + ".zst")
    restored = zstandard.ZstdDecompressor().decompress(backup.read_bytes())
    assert restored == env.claude_main.read_bytes()
    assert frontmatter(env.vault / CLAUDE_NOTE)["raw"] == str(backup)


def test_second_sync_is_a_no_op(env):
    sync(env.config)
    before = {p: p.stat().st_mtime_ns for p in env.vault.rglob("*.md")}
    report = sync(env.config)
    assert (report.parsed, report.written) == (0, 0)
    assert {p: p.stat().st_mtime_ns for p in env.vault.rglob("*.md")} == before


def test_a_new_title_renames_the_note_and_updates_child_links(env):
    sync(env.config)
    record = {"type": "custom-title", "customTitle": "Retitled work", "sessionId": CLAUDE_SESSION}
    with env.claude_main.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    report = sync(env.config)
    new_note = "Sessions/2026/10/2026-10-20 claude demo - Retitled work (11111111).md"
    assert report.renamed == 1
    assert not (env.vault / CLAUDE_NOTE).exists()
    assert (env.vault / new_note).exists()
    assert (
        frontmatter(env.vault / CLAUDE_SUB_NOTE)["parent"]
        == f"[[{new_note.rsplit('/', 1)[1][:-3]}]]"
    )


def test_notes_survive_when_the_source_transcript_is_deleted(env):
    sync(env.config)
    env.claude_main.unlink()
    sync(env.config)
    assert (env.vault / CLAUDE_NOTE).exists()


def test_excluded_working_directories_are_never_rendered(env):
    config = replace(env.config, exclude=("/Users/me/Repos/demo*",))
    report = sync(config)
    assert report.excluded == 6
    assert notes(env.vault) == []


def test_search_finds_redacted_text_only(env):
    sync(env.config)
    with Store(env.config.db_path) as store:
        keys = {row["session_key"] for row in store.search("retry")}
        assert f"claude:{CLAUDE_SESSION}" in keys
        assert store.search("AKIAABCDEFGHIJKLMNOP") == []


def test_unknown_record_types_are_tallied(env):
    sync(env.config)
    with Store(env.config.db_path) as store:
        totals = {(r["provider"], r["record_type"]): r["count"] for r in store.unknown_totals()}
    assert totals[("claude", "future-thing")] == 1
    assert totals[("codex", "future_record")] == 1


def test_a_note_that_fails_to_render_is_retried_on_the_next_sync(env, monkeypatch):
    import ax.sync as sync_module

    real = sync_module.render

    def flaky(session, **kwargs):
        if session.session_id == CLAUDE_SESSION:
            raise RuntimeError("boom")
        return real(session, **kwargs)

    monkeypatch.setattr(sync_module, "render", flaky)
    report = sync(env.config)
    assert any("boom" in error for error in report.errors)
    assert CLAUDE_NOTE not in notes(env.vault)
    assert CODEX_NOTE in notes(env.vault)

    monkeypatch.setattr(sync_module, "render", real)
    assert sync(env.config).errors == []
    assert notes(env.vault) == ALL_NOTES


def test_a_rename_that_fails_to_write_keeps_the_old_note_until_it_succeeds(env, monkeypatch):
    import ax.sync as sync_module

    sync(env.config)
    record = {"type": "custom-title", "customTitle": "Retitled work", "sessionId": CLAUDE_SESSION}
    with env.claude_main.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    real = sync_module.render

    def flaky(session, **kwargs):
        if session.session_id == CLAUDE_SESSION:
            raise RuntimeError("boom")
        return real(session, **kwargs)

    monkeypatch.setattr(sync_module, "render", flaky)
    sync(env.config)
    assert (env.vault / CLAUDE_NOTE).exists()

    monkeypatch.setattr(sync_module, "render", real)
    sync(env.config)
    new_note = "Sessions/2026/10/2026-10-20 claude demo - Retitled work (11111111).md"
    assert (env.vault / new_note).exists()
    assert not (env.vault / CLAUDE_NOTE).exists()


def test_raw_files_are_backed_up_even_when_parsing_fails(env, monkeypatch):
    import ax.sources.claude as claude_source

    def broken(path):
        raise ValueError("unparseable")

    monkeypatch.setattr(claude_source, "parse", broken)
    report = sync(env.config)
    assert any("unparseable" in error for error in report.errors)
    backup = env.config.raw_dir / "claude" / env.claude_main.relative_to(env.claude_home)
    assert backup.with_name(backup.name + ".zst").exists()


def test_a_file_that_vanishes_mid_run_is_reported_not_fatal(env, monkeypatch):
    import ax.sources.claude as claude_source

    real = claude_source.discover
    gone = env.claude_home / "projects" / "-Users-me-Repos-demo" / "gone.jsonl"
    monkeypatch.setattr(claude_source, "discover", lambda home: [*real(home), gone])
    report = sync(env.config)
    assert any("gone.jsonl" in error for error in report.errors)
    assert notes(env.vault) == ALL_NOTES


def test_adding_an_exclusion_later_removes_notes_and_search_rows(env):
    sync(env.config)
    report = sync(replace(env.config, exclude=("/Users/me/Repos/demo*",)))
    assert report.removed == 5
    assert notes(env.vault) == []
    with Store(env.config.db_path) as store:
        assert store.search("retry") == []


def test_a_parser_upgrade_rebuilds_notes_whose_source_is_gone(env):
    sync(env.config)
    env.claude_main.unlink()
    (env.vault / CLAUDE_NOTE).write_text("stale")
    with Store(env.config.db_path) as store:
        store.set_meta("parser_version", "0")
    assert sync(env.config).errors == []
    assert "# Retry for fetch helper" in (env.vault / CLAUDE_NOTE).read_text()


def test_codex_parents_list_their_subagents(env):
    sync(env.config)
    text = (env.vault / CODEX_NOTE).read_text()
    assert "## Subagents" in text
    assert "[[codex 33333333-3333-4333-8333-333333333333|" in text


def test_a_secret_in_a_codex_thread_name_does_not_force_a_reparse(env):
    index = env.codex_home / "session_index.jsonl"
    row = {
        "id": "22222222-2222-4222-8222-222222222222",
        "thread_name": "Rotate AKIAABCDEFGHIJKLMNOP",
    }
    index.write_text(json.dumps(row) + "\n")
    sync(env.config)
    assert sync(env.config).parsed == 0


def test_sessions_whose_names_would_collide_get_distinct_notes(env):
    day = env.codex_home / "sessions" / "2026" / "10" / "20"
    source = next(day.glob("*_55555555-*.jsonl")).read_text()
    for prefix in ("aaaaaaaa", "bbbbbbbb"):
        twin = f"{prefix}-0000-4000-8000-000011112222"
        (day / f"rollout-2026-10-20T12-00-00-{twin}.jsonl").write_text(source)
    sync(env.config)
    twins = [n for n in notes(env.vault) if "Try a different retry strategy" in n]
    assert len(twins) == 3


def test_a_second_sync_while_one_runs_is_refused(env):
    import pytest

    from ax.sync import SyncBusy, lock

    with lock(env.config), pytest.raises(SyncBusy):
        sync(env.config)

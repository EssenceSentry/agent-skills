import json
from pathlib import Path

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
def indexed(env, tmp_path):
    repos = tmp_path / "Repos"
    for name in ("demo", "other"):
        (repos / name / ".git").mkdir(parents=True)
    (repos / "notes-only").mkdir()
    env.config_path.write_text(
        env.config_path.read_text() + f'\n[profile]\nrepos_root = "{repos}"\n'
    )
    env.config = load(env.config_path)
    sync_module.sync(env.config)
    with Store(env.config.db_path) as store:
        notes = {r["session_id"]: r["note_path"] for r in store.all_sessions() if r["note_path"]}
    env.notes = notes
    env.repos = repos
    return env


def qmd_hit(collection, rel, title="T", snippet="@@ -1,2 @@ (0 before, 1 after)\nthe passage"):
    return {"docid": "#abc", "score": 0.9, "file": f"qmd://{collection}/{rel}?index=ax",
            "line": 3, "title": title, "snippet": snippet}  # fmt: skip


class Runner:
    def __init__(self, qmd=(), semble=()):
        self.qmd, self.semble, self.calls = list(qmd), list(semble), []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == "qmd":
            return json.dumps(self.qmd)
        repos = {Path(p).name: p for p in argv if p.startswith("/") and Path(p).is_dir()}
        return json.dumps({"results": self.semble, "repos": repos})


def note_rel(env, session_id):
    return env.notes[session_id].removeprefix("Sessions/")


def test_setup_writes_one_qmd_collection_per_source(indexed):
    path = find.write_qmd_config(indexed.config)
    assert path == indexed.root / "qmd" / "ax.yml"
    found = yaml.safe_load(path.read_text())["collections"]
    assert found["claude"]["path"] == str(indexed.vault / "Sessions")
    assert (
        "claude" in found["claude"]["pattern"] and "**/_subagents/**" in found["claude"]["ignore"]
    )
    assert found["subagents"]["includeByDefault"] is False
    assert found["claude-memory"]["path"] == str(indexed.claude_home / "projects")
    assert "Sessions/**" in found["notes"]["ignore"]
    assert all(c["context"]["/"] for c in found.values())


def test_repositories_are_the_git_checkouts_under_repos_root(indexed):
    assert [p.name for p in find.repos(indexed.config)] == ["demo", "other"]


def test_hits_are_merged_labelled_and_carry_handles(indexed, monkeypatch):
    runner = Runner(
        qmd=[qmd_hit("claude", note_rel(indexed, CLAUDE_SESSION), "Add retries"),
             qmd_hit("claude-memory", "-Users-me-Repos-demo/memory/retries.md", "Retries")],
        semble=[{"file_path": "demo/src/fetch.py", "start_line": 4, "end_line": 9,
                 "score": 0.02, "content": "def fetch(url):\n    retry()"}],
    )  # fmt: skip
    monkeypatch.setattr(find, "_run", runner)
    hits = find.find(indexed.config, "retry the fetch helper", limit=5)
    assert [h["source"] for h in hits] == ["conversation", "code", "memory"]
    talk, code, memory = hits
    assert talk["handle"] == "ax:11111111" and talk["project"] == "demo"
    assert talk["path"] == str(indexed.vault / indexed.notes[CLAUDE_SESSION])
    assert talk["snippet"] == "the passage"
    assert code["path"] == str(indexed.repos / "demo" / "src" / "fetch.py") and code["line"] == 4
    assert memory["path"].endswith("memory/retries.md")
    [qmd_call] = [c for c in runner.calls if c[0] == "qmd"]
    assert qmd_call[1:4] == ["--index", "ax", "query"]
    assert {"claude", "codex", "claude-memory", "codex-memory", "notes"} == {
        qmd_call[i + 1] for i, a in enumerate(qmd_call) if a == "-c"
    }


def test_filters_apply_through_the_archive_and_the_repo_names(indexed, monkeypatch):
    runner = Runner(
        qmd=[qmd_hit("claude", note_rel(indexed, CLAUDE_SESSION)),
             qmd_hit("codex", note_rel(indexed, CODEX_SESSION))],
    )  # fmt: skip
    monkeypatch.setattr(find, "_run", runner)
    only_claude = find.find(indexed.config, "q", sources=["conversations"], provider="claude")
    assert [h["handle"] for h in only_claude] == ["ax:11111111"]
    assert find.find(indexed.config, "q", sources=["conversations"], since="2030-01-01") == []
    find.find(indexed.config, "q", sources=["code"], project="other")
    [semble] = [c for c in runner.calls if c[0] == "semble"]
    assert str(indexed.repos / "other") in semble and str(indexed.repos / "demo") not in semble


def test_fast_search_skips_the_models_and_code_only_skips_qmd(indexed, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(find, "_run", runner)
    find.find(indexed.config, "q", sources=["conversations"], fast=True)
    find.find(indexed.config, "q", sources=["code"])
    assert runner.calls[0][3] == "search" and [c[0] for c in runner.calls] == ["qmd", "semble"]


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
    monkeypatch.setattr(find, "refresh", lambda config: refreshed.append(config))
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

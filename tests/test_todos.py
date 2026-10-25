import json

import pytest
import yaml
from typer.testing import CliRunner

from ax import todos
from ax.cli import app

HERE = {"CLAUDE_CODE_SESSION_ID": "6942b4a0-7d35-4d5e-91a2-460a9fe6d7e6", "CODEX_THREAD_ID": ""}


def front(path):
    return yaml.safe_load(path.read_text().split("---\n")[1])


def test_a_todo_is_a_vault_note_with_an_id_scope_and_origin(env):
    item = todos.add(env.config, "Write one ax skill", scope="project:agent-skills",
                     origin="ax:9fe6d7e6", detail="Map every command.")  # fmt: skip
    assert item.id == "T1" and item.path.parent == env.vault / "Todos"
    assert item.path.name == "T1 Write one ax skill.md"
    meta = front(item.path)
    assert meta["status"] == "open" and meta["scope"] == "project:agent-skills"
    assert meta["from"] == "ax:9fe6d7e6" and meta["text"] == "Write one ax skill"
    assert "Map every command." in item.path.read_text()
    assert todos.add(env.config, "Turn on the job service", scope="global").id == "T2"


def test_listing_shows_a_projects_and_the_global_open_todos(env):
    todos.add(env.config, "Mine", scope="project:demo")
    todos.add(env.config, "Theirs", scope="project:other")
    todos.add(env.config, "Everyone's", scope="global")
    closed = todos.add(env.config, "Finished", scope="project:demo")
    todos.close(env.config, closed.id, "done", closed_in="ax:11111111")
    assert [t.text for t in todos.listing(env.config, project="demo")] == ["Mine", "Everyone's"]
    assert len(todos.listing(env.config)) == 3
    assert len(todos.listing(env.config, include_closed=True)) == 4
    meta = front(todos.get(env.config, closed.id).path)
    assert meta["status"] == "done" and meta["closed_in"] == "ax:11111111" and meta["closed"]


def test_closing_an_unknown_or_closed_todo_says_so(env):
    item = todos.add(env.config, "Once", scope="global")
    todos.close(env.config, item.id, "dropped")
    with pytest.raises(ValueError, match="already dropped"):
        todos.close(env.config, item.id, "done")
    with pytest.raises(ValueError, match="no to-do T9"):
        todos.close(env.config, "T9", "done")


def test_ids_keep_counting_after_notes_are_edited_or_removed(env):
    first = todos.add(env.config, "First", scope="global")
    todos.add(env.config, "Second", scope="global")
    first.path.unlink()
    assert todos.add(env.config, "Third", scope="global").id == "T3"


def test_the_command_takes_the_project_and_conversation_from_where_it_runs(
    env, tmp_path, monkeypatch
):
    repo = tmp_path / "agent-skills"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    run = {"AX_CONFIG": str(env.config_path), **HERE}
    added = CliRunner().invoke(app, ["todo", "add", "Write one ax skill", "--json"], env=run)
    assert added.exit_code == 0, added.output
    item = json.loads(added.output)
    assert item["scope"] == "project:agent-skills" and item["from"] == "ax:9fe6d7e6"
    glob = CliRunner().invoke(app, ["todo", "add", "Job service", "--global"], env=run)
    assert glob.exit_code == 0 and "T2" in glob.output
    listed = CliRunner().invoke(app, ["todo", "list", "--project", "agent-skills"], env=run)
    assert "T1" in listed.output and "T2" in listed.output
    done = CliRunner().invoke(app, ["todo", "done", "T1"], env=run)
    assert done.exit_code == 0
    assert front(todos.get(env.config, "T1").path)["closed_in"] == "ax:9fe6d7e6"
    missing = CliRunner().invoke(app, ["todo", "drop", "T7"], env=run)
    assert missing.exit_code == 2

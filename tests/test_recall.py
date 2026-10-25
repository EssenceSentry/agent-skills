import json

import pytest
from typer.testing import CliRunner

from ax import learn, recall
from ax import sync as sync_module
from ax.cli import app
from ax.handles import resolve
from ax.store import Store
from chats import claude_chat
from conftest import CLAUDE_SESSION

EARLIER = "88888888-8888-4888-8888-0000feedf00d"
OUTSIDE = {"CLAUDE_CODE_SESSION_ID": "", "CODEX_THREAD_ID": ""}


@pytest.fixture
def earlier(env):
    claude_chat(env, EARLIER,
                ("user", "Add retries to the fetch helper with exponential backoff."),
                ("assistant", "Looking at the helper."),
                ("edit", "/Users/me/Repos/demo/src/fetch.py"),
                ("user", "Cap the retries at five, never more."),
                ("assistant", "Done: five retries with backoff; tests pass. Open: jitter."))  # fmt: skip
    sync_module.sync(env.config)
    return resolve(env.config, "ax:feedf00d")


def test_the_outline_shows_the_users_turns_where_it_ended_and_what_changed(env, earlier):
    text = recall.outline(env.config, earlier)
    assert "ax:feedf00d" in text and str(env.vault) in text
    assert "Add retries to the fetch helper" in text and "Cap the retries at five" in text
    assert "Done: five retries with backoff; tests pass. Open: jitter." in text
    assert "src/fetch.py" in text


def test_a_long_conversation_keeps_its_first_and_last_turns(env):
    turns = [t for i in range(70) for t in (("user", f"step {i:02d} please"), ("assistant", "ok"))]
    claude_chat(env, EARLIER, *turns)
    sync_module.sync(env.config)
    text = recall.outline(env.config, resolve(env.config, "feedf00d"))
    assert "step 00" in text and "step 69" in text and "10 more turns" in text
    assert "step 20 please" not in text


def card_model(answer):
    def model(prompt):
        model.prompts.append(prompt)
        return json.dumps(answer)

    model.prompts = []
    return model


def test_the_card_is_written_once_until_the_conversation_changes(env, earlier):
    model = card_model({"goal": "Retries for the fetch helper", "outcome": "Five retries",
                        "decisions": ["Cap at five"], "open": ["Jitter"], "facts": [], "files": []})  # fmt: skip
    text = recall.card(env.config, earlier, model=model)
    assert "Retries for the fetch helper" in text and "- Cap at five" in text and "- Jitter" in text
    assert "Cap the retries at five" in model.prompts[0] and "edited" not in model.prompts[0]
    assert recall.card(env.config, earlier, model=card_model({})) == text
    claude_chat(env, EARLIER, ("user", "Something new."), ("assistant", "New answer."))
    sync_module.sync(env.config)
    again = card_model({"goal": "Something new"})
    assert "Something new" in recall.card(env.config, resolve(env.config, EARLIER), model=again)


def test_a_focused_import_answers_for_the_task_and_is_cached_per_task(env, earlier):
    model = card_model("unused")
    model_answer = "- 12:03 Retries are capped at five."

    def focused(prompt):
        model.prompts.append(prompt)
        return model_answer

    text = recall.focus(env.config, earlier, "add jitter to retries", model=focused)
    assert model_answer in text and "add jitter to retries" in model.prompts[0]
    assert "Cap the retries at five" in model.prompts[0]
    assert recall.focus(env.config, earlier, "add jitter to retries", model=card_model("x")) == text
    recall.focus(env.config, earlier, "something else", model=focused)
    assert len(model.prompts) == 2


def test_recalling_from_inside_a_conversation_links_the_two(env, earlier, monkeypatch):
    sync_module.sync(env.config)
    run = {**OUTSIDE, "AX_CONFIG": str(env.config_path), "CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION}
    result = CliRunner().invoke(app, ["recall", "ax:feedf00d"], env=run)
    assert result.exit_code == 0, result.output
    assert "Cap the retries at five" in result.output
    with Store(env.config.db_path) as store:
        [link] = store.links_from(f"claude:{CLAUDE_SESSION}")
    assert (link["target_key"], link["kind"]) == (earlier["key"], "recall")
    monkeypatch.setattr(learn, "claude_model", lambda m="haiku": lambda p: "- 12:03 Five retries.")
    focused = CliRunner().invoke(app, ["recall", "feedf00d", "--for", "jitter"], env=run)
    assert focused.exit_code == 0 and "Five retries." in focused.output


def test_recalling_from_outside_links_nothing_and_unknown_handles_fail(env, earlier):
    run = {**OUTSIDE, "AX_CONFIG": str(env.config_path)}
    assert CliRunner().invoke(app, ["recall", "ax:feedf00d"], env=run).exit_code == 0
    with Store(env.config.db_path) as store:
        assert (
            store.db.execute("SELECT COUNT(*) FROM links WHERE kind = 'recall'").fetchone()[0] == 0
        )
    missing = CliRunner().invoke(app, ["recall", "ax:0badcafe"], env=run)
    assert missing.exit_code == 2 and "no archived conversation" in missing.output


def test_recall_lists_the_todos_raised_in_the_conversation(env, earlier):
    from ax import todos

    todos.add(env.config, "Add jitter to the retries", scope="project:demo", origin="ax:feedf00d")
    todos.add(env.config, "Unrelated", scope="global", origin="ax:11111111")
    text = recall.outline(env.config, earlier)
    assert "To-dos raised here" in text and "Add jitter to the retries" in text
    assert "Unrelated" not in text

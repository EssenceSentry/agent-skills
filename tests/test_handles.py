import json
import os

import pytest
from typer.testing import CliRunner

from ax import handles
from ax import sync as sync_module
from ax.cli import app
from ax.store import Store
from conftest import CLAUDE_SESSION, CODEX_SESSION

OUTSIDE = {"CLAUDE_CODE_SESSION_ID": "", "CODEX_THREAD_ID": ""}


def test_a_handle_is_the_last_eight_characters_of_the_id():
    assert handles.handle("6942b4a0-7d35-4d5e-91a2-460a9fe6d7e6") == "9fe6d7e6"


@pytest.fixture
def synced(env):
    sync_module.sync(env.config)
    return env


@pytest.mark.parametrize("ref", ["ax:11111111", "11111111", CLAUDE_SESSION, "1111111"])
def test_a_conversation_is_found_by_handle_full_id_or_prefix(synced, ref):
    assert handles.resolve(synced.config, ref)["session_id"] == CLAUDE_SESSION


def test_a_conversation_is_found_by_its_note(synced):
    row = handles.resolve(synced.config, f"claude:{CLAUDE_SESSION}")
    assert handles.resolve(synced.config, row["note_path"])["key"] == row["key"]
    stem = row["note_path"].rsplit("/", 1)[-1].removesuffix(".md")
    assert handles.resolve(synced.config, stem)["key"] == row["key"]


def test_an_unknown_or_ambiguous_reference_says_so(synced):
    with pytest.raises(handles.NotFound):
        handles.resolve(synced.config, "ax:deadbeef")
    with Store(synced.config.db_path) as store:
        for sid in ("aaaaaaaa-0000-4000-8000-00000abcdef1", "bbbbbbbb-0000-4000-8000-00000abcdef1"):
            store.db.execute(
                "INSERT INTO sessions (key, provider, session_id, kind, updated_at) "
                "VALUES (?, 'codex', ?, 'main', 'now')", (f"codex:{sid}", sid))  # fmt: skip
        store.commit()
    with pytest.raises(handles.Ambiguous) as found:
        handles.resolve(synced.config, "0abcdef1")
    assert len(found.value.rows) == 2


def test_the_current_conversation_comes_from_the_tools_environment(env):
    claude = {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION}
    assert handles.current(env.config, claude) == ("claude", CLAUDE_SESSION)
    assert handles.current(env.config, OUTSIDE) is None
    both = {"CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION, "CODEX_THREAD_ID": CODEX_SESSION}
    os.utime(env.claude_main, (1, 1))  # Codex's transcript is the live one
    assert handles.current(env.config, both) == ("codex", CODEX_SESSION)


def test_ax_here_prints_the_handle_and_note_of_this_conversation(env):
    run = {**OUTSIDE, "AX_CONFIG": str(env.config_path), "CLAUDE_CODE_SESSION_ID": CLAUDE_SESSION}
    result = CliRunner().invoke(app, ["here", "--json"], env=run)
    assert result.exit_code == 0, result.output
    found = json.loads(result.output)
    assert found["handle"] == "ax:11111111" and found["note"].endswith("(11111111).md")
    assert (env.vault / found["note"]).exists()
    outside = CliRunner().invoke(app, ["here"], env={**OUTSIDE, "AX_CONFIG": str(env.config_path)})
    assert outside.exit_code == 2 and "not inside" in outside.output

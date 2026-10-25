from ax import handles
from ax import sync as sync_module
from ax.store import Store
from chats import claude_chat
from conftest import CLAUDE_SESSION, CODEX_SESSION

LATER = "77777777-7777-4777-8777-777777777777"


def test_mentions_are_handles_recall_commands_and_full_ids():
    text = (f"Build on ax:11111111 and run `ax recall 2222222` then read {CODEX_SESSION}; "
            "commit 4dcae70 and colour #deadbeef are not mentions.")  # fmt: skip
    assert handles.mentions(text) == {"11111111", "2222222", CODEX_SESSION}


def note(env, session_id):
    with Store(env.config.db_path) as store:
        path = store.db.execute(
            "SELECT note_path FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
    return env.vault / path


def test_a_conversation_that_mentions_another_links_to_it(env):
    claude_chat(env, LATER,
                ("user", f"Continue from ax:11111111, and see {CODEX_SESSION} too."),
                ("assistant", f"Done; this is ax:{LATER[-8:]} if you need it."))  # fmt: skip
    sync_module.sync(env.config)
    text = note(env, LATER).read_text()
    first, codex = note(env, CLAUDE_SESSION).stem, note(env, CODEX_SESSION).stem
    assert f'  - "[[{first}]]"' in text and f'  - "[[{codex}]]"' in text
    assert "builds_on:" in text and "Builds on: [[" in text
    assert f"[[{note(env, LATER).stem}]]" not in text  # never itself


def test_a_recall_link_is_kept_and_mentions_are_recomputed(env):
    claude_chat(env, LATER, ("user", "Start fresh."), ("assistant", "OK."))
    sync_module.sync(env.config)
    with Store(env.config.db_path) as store:
        store.add_link(f"claude:{LATER}", f"claude:{CLAUDE_SESSION}", "recall")
        store.commit()
    claude_chat(env, LATER, ("user", "Start fresh."), ("assistant", "OK, carrying on."))
    sync_module.sync(env.config)
    assert f"[[{note(env, CLAUDE_SESSION).stem}]]" in note(env, LATER).read_text()
    with Store(env.config.db_path) as store:
        assert [dict(r)["kind"] for r in store.links_from(f"claude:{LATER}")] == ["recall"]

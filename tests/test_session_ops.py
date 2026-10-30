import json

from ax import chat_store, session_ops
from conftest import CLAUDE_SESSION


def test_claude_disk_helpers_use_the_configured_home_and_preserve_the_source_on_fork(env):
    original = env.claude_main.read_bytes()
    result = session_ops._claude(env.config, "fork_session", session_id=CLAUDE_SESSION)
    assert result["session_id"] != CLAUDE_SESSION
    assert env.claude_main.read_bytes() == original
    copies = list((env.claude_home / "projects").glob(f"*/{result['session_id']}.jsonl"))
    assert len(copies) == 1
    session_ops._claude(
        env.config, "rename_session", session_id=result["session_id"], title="Forked review"
    )
    assert "Forked review" in copies[0].read_text()


def test_session_organization_survives_reopening_the_store(env):
    first = session_ops.act(
        env.config, {"action": "group", "provider": "claude", "id": "s", "group": "Review"}
    )
    assert first["metadata"]["group"] == "Review"
    session_ops.act(env.config, {"action": "pin", "provider": "claude", "id": "s", "pinned": True})
    assert chat_store.metadata(env.config, "claude", "s") == {"group": "Review", "pinned": True}


def test_migrations_preserve_existing_outbox_rows(env):
    import sqlite3

    env.config.data.mkdir(parents=True)
    db = sqlite3.connect(env.config.data / "chat.db")
    db.execute(
        "CREATE TABLE outbox(provider TEXT,sid TEXT,id TEXT,body TEXT,status TEXT,error TEXT,created REAL,PRIMARY KEY(provider,sid,id))"
    )
    db.execute(
        "INSERT INTO outbox VALUES('claude','s','one',?,'queued',NULL,0)",
        (json.dumps({"text": "keep"}),),
    )
    db.commit()
    db.close()
    assert chat_store.messages(env.config, "claude", "s")[0]["text"] == "keep"
    assert chat_store.claim(env.config, "claude", "s", "one")
    assert not chat_store.claim(env.config, "claude", "s", "one")

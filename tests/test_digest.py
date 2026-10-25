import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from ax import digest, glue, jobs
from ax import sync as sync_module
from ax.cli import app
from ax.store import Store
from chats import claude_chat
from conftest import CLAUDE_SESSION, CODEX_SESSION

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
OTHER = "99999999-9999-4999-8999-0000c0ffee00"


def synced(env):
    claude_chat(env, OTHER, ("user", "Tune the ranked audit threshold."), ("assistant", "Done."),
                day="2026-10-24", cwd="/Users/me/Repos/audit")  # fmt: skip
    sync_module.sync(env.config)
    with Store(env.config.db_path) as store:
        store.db.execute("UPDATE sessions SET project = 'audit' WHERE session_id = ?", (OTHER,))
        store.db.execute(
            "INSERT INTO sessions (key, provider, session_id, kind, title, project, entrypoint, "
            "started, ended, note_path, updated_at) VALUES ('claude:w1', 'claude', 'w1', 'main', "
            "'A worker', 'demo', 'sdk-cli', '2026-10-24T10:00:00Z', '2026-10-24T11:00:00Z', "
            "'Sessions/w.md', 'now')"
        )
        store.db.execute(
            "INSERT INTO sessions (key, provider, session_id, kind, title, project, entrypoint, "
            "started, ended, note_path, updated_at) VALUES ('codex:old', 'codex', 'old-1234abcd', "
            "'main', 'Old work', 'demo', 'codex_vscode', '2026-10-01T10:00:00Z', "
            "'2026-10-01T11:00:00Z', 'Sessions/o.md', 'now')"
        )
        store.commit()
    return env


def test_the_digest_lists_last_weeks_own_conversations_with_handles(env):
    text = digest.build(synced(env).config, cwd="/Users/me/Repos/demo", now=NOW)
    assert "ax recall" in text and "ax find" in text
    assert "ax:11111111" in text and "ax:22222222" in text and "ax:c0ffee00" in text
    assert "A worker" not in text and "Old work" not in text
    lines = [line for line in text.splitlines() if "ax:" in line and line.startswith("- ")]
    assert "audit" in lines[-1]  # this project's conversations come first


def test_the_conversation_that_is_starting_is_left_out(env):
    text = digest.build(synced(env).config, exclude=CLAUDE_SESSION, now=NOW)
    assert "ax:11111111" not in text and "ax:22222222" in text


def test_running_jobs_are_listed_with_their_description(env):
    jobs.new(env.config, "mine-videos", label="Extract candidate videos", env={})
    jobs.new(env.config, "finished", label="Done already", env={})
    with open(jobs.events_path(env.config, "finished"), "a") as f:
        f.write(json.dumps({"status": "done"}) + "\n")
    jobs.refresh(env.config, "finished")
    text = digest.build(env.config, now=NOW)
    assert "mine-videos" in text and "Extract candidate videos" in text
    assert "Done already" not in text


def test_a_long_week_is_cut_with_a_count(env):
    synced(env)
    text = digest.build(env.config, now=NOW, limit=2)
    assert "and 2 more" in text  # four recent conversations, two shown


def test_the_start_hook_prints_context_for_the_tool_and_never_fails(env):
    synced(env)
    run = {"AX_CONFIG": str(env.config_path)}
    payload = json.dumps({"session_id": CODEX_SESSION, "cwd": "/Users/me/Repos/demo",
                          "hook_event_name": "SessionStart", "source": "startup"})  # fmt: skip
    result = CliRunner().invoke(app, ["hooks", "start", "--tool", "codex"], input=payload, env=run)
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart" and "ax:11111111" in out["additionalContext"]
    assert "ax:22222222" not in out["additionalContext"]  # the conversation starting
    broken = CliRunner().invoke(app, ["hooks", "start", "--tool", "claude"], input="not json",
                                env={"AX_CONFIG": str(env.root / "missing.toml")})  # fmt: skip
    assert broken.exit_code == 0


def test_installing_hooks_adds_the_start_hook_to_both_tools(env):
    changes = glue.plan_hooks(env.config, ax="/bin/ax")
    for change in changes:
        groups = json.loads(change.after)["hooks"]["SessionStart"]
        commands = [h["command"] for g in groups for h in g["hooks"]]
        assert any(c.startswith("/bin/ax hooks start --tool") for c in commands)

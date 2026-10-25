import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from ax import profile, scorecard, serve
from ax.cli import app
from ax.config import load
from ax.store import Store

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
THIS_WEEK = (NOW - timedelta(days=1)).isoformat()
LAST_WEEK = (NOW - timedelta(days=8)).isoformat()


def add_session(db, key, ended, *, provider="codex", entrypoint="codex_vscode", model=None,
                effort=None, cost=None, source=None):  # fmt: skip
    db.execute(
        "INSERT INTO sessions (key, provider, session_id, kind, project, entrypoint, model, "
        "effort, cost_usd, started, ended, source_path, updated_at) "
        "VALUES (?, ?, ?, 'main', 'demo', ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, provider, key, entrypoint, model, effort, cost, ended, ended, source, ended),
    )


def add_messages(db, key, ts, *items):
    for seq, (role, text) in enumerate(items):
        db.execute(
            "INSERT INTO messages (session_key, seq, ts, role, text) VALUES (?, ?, ?, ?, ?)",
            (key, seq, ts, role, text),
        )


@pytest.fixture
def card(env, tmp_path):
    env.config_path.write_text(
        env.config_path.read_text() + f'agents_home = "{tmp_path / "agents"}"\n'
    )
    env.config = load(env.config_path)
    worker_log = tmp_path / "worker.jsonl"
    denied = {"type": "tool_result", "is_error": True,
              "content": "Permission to use Bash has been denied because Claude Code is running in don't ask mode."}  # fmt: skip
    ok = {"type": "tool_result", "content": "ok"}
    worker_log.write_text(
        json.dumps({"type": "user", "message": {"content": [denied, denied]}}) + "\n"
        + json.dumps({"type": "user", "message": {"content": [ok]}}) + "\n"
    )  # fmt: skip

    def transcript(name, version, codex=False):
        warning = f"WARNING: there is a new pyright version available (v1.1.{version})"
        records = []
        if codex:
            item = {"type": "CommandExecution", "aggregated_output": f"0 errors\n{warning}",
                    "command": f"uv run pyright src/{name}"}  # fmt: skip
            records.append({"type": "event_msg",
                            "payload": {"type": "item_completed", "item": item}})  # fmt: skip
        else:
            call = {"type": "tool_use", "id": "t1", "name": "Bash",
                    "input": {"command": "pyright src\nwith a second line"}}  # fmt: skip
            records.append({"type": "assistant", "message": {"content": [call]}})
            block = {"type": "tool_result", "tool_use_id": "t1",
                     "content": [{"type": "text", "text": warning}]}  # fmt: skip
            records.append({"type": "user", "message": {"content": [block]}})
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return str(path)

    with Store(env.config.db_path) as store:
        db = store.db
        add_session(db, "c1", THIS_WEEK, provider="claude", entrypoint="claude-desktop",
                    model="claude-opus-5-5", effort="high", cost=12.5,
                    source=transcript("c1", 409))  # fmt: skip
        add_messages(db, "c1", THIS_WEEK,
                     ("user", "Don't touch unrelated files."), ("user", "Progress?"),
                     ("user", "I said leave the typings alone."),
                     ("tool", "used skill `dataviz`"))  # fmt: skip
        add_session(db, "x1", THIS_WEEK, model="gpt-6-astra", effort="xhigh",
                    source=transcript("x1", 410, codex=True))  # fmt: skip
        add_messages(db, "x1", THIS_WEEK, ("user", "Looks good."),
                     ("tool", "ran `sed -n 1,80p /Users/me/.codex/skills/plotting/SKILL.md`"))  # fmt: skip
        add_session(db, "x2", LAST_WEEK, source=transcript("x2", 411, codex=True))
        add_messages(db, "x2", LAST_WEEK, ("user", "Never commit without asking."),
                     ("user", "Very disappointing! You ignored the plan."),
                     ("user", "This is unacceptable."))  # fmt: skip
        [(confirmed,)] = db.execute(
            "SELECT id FROM messages WHERE text LIKE 'Very disappointing%'"
        ).fetchall()
        add_session(db, "w1", THIS_WEEK, provider="claude", entrypoint="sdk-cli",
                    model="claude-opus-5-5", effort="high", cost=2.0, source=str(worker_log))  # fmt: skip
        add_messages(db, "w1", THIS_WEEK, ("user", "Never do X; you are a worker."))
        store.commit()
    labels = env.config.data / "learn" / "labels.json"
    labels.parent.mkdir(parents=True)
    labels.write_text(json.dumps({f"m{confirmed}": {"kind": "none", "frustrated": True}}))
    (env.config.data / "guard.jsonl").write_text(
        json.dumps({"ts": "2026-10-23T10:00:00-0300", "rule": "stage-explicit-paths"}) + "\n"
    )
    profile.add(
        env.config, "stage-explicit-paths", rule="Stage explicit paths.", added="2026-10-01"
    )
    profile.add(env.config, "quiet-rule", rule="A rule that never fires.", added="2026-10-01")
    for folder, name in ((env.claude_home / "skills", "dataviz"),
                         (env.claude_home / "skills", "unused-skill"),
                         (env.codex_home / "skills", "plotting")):  # fmt: skip
        (folder / name).mkdir(parents=True)
        (folder / name / "SKILL.md").write_text(f"name: {name}\n")
    return scorecard.build(env.config, weeks=2, now=NOW)


def test_weeks_count_corrections_nudges_and_sessions(card):
    this, last = card["weeks"][-1], card["weeks"][0]
    assert this["sessions"] == {"claude": 1, "codex": 1} and this["user_messages"] == 4
    assert this["corrections"] == 2 and this["repeats"] == 1 and this["nudges"] == 1
    assert last["corrections"] == 1 and last["sessions"] == {"codex": 1}


def test_frustration_moments_count_once_the_labeller_confirms_them(card):
    last, this = card["weeks"][0], card["weeks"][-1]
    assert last["frustration"] == 1 and last["frustration_unchecked"] == 1
    assert this["frustration"] == 0 and this["frustration_unchecked"] == 0
    assert "Frustration" in scorecard.markdown(card) and "Frustration" in scorecard.render(card)
    assert "1 (+1 unchecked)" in scorecard.markdown(card)


def test_worker_denials_and_guard_fires_are_counted(card):
    this = card["weeks"][-1]
    assert this["denials"] == 2 and this["guard_fires"] == 1


def test_cost_is_split_by_model_and_effort(card):
    cost = card["weeks"][-1]["cost"]
    assert cost["claude-opus-5-5 · high"] == {"sessions": 2, "usd": 14.5}
    assert cost["gpt-6-astra · xhigh"] == {"sessions": 1, "usd": None}


def test_rules_show_which_fired_and_which_never_did(card):
    rules = {r["id"]: r for r in card["rules"]}
    assert rules["stage-explicit-paths"]["guard_fires"] == 1
    assert rules["quiet-rule"]["guard_fires"] == 0


def test_friction_finds_errors_that_recur_across_sessions(card):
    [top] = card["friction"]
    assert "new pyright version" in top["signature"] and top["sessions"] == 3


def test_friction_keeps_example_commands_and_projects(card, env):
    [top] = card["friction"]
    assert sorted(top["examples"]) == [
        "pyright src",
        "uv run pyright src/x1",
        "uv run pyright src/x2",
    ]
    assert top["projects"] == ["demo"]
    [everything] = scorecard.recurring(env.config, weeks=2, now=NOW)
    assert everything == top


def test_skills_never_used_are_listed(card):
    assert card["skills"]["used"] == {"dataviz": 1, "plotting": 1}
    assert card["skills"]["unused"] == ["unused-skill"]


def test_the_page_and_the_command_render(card, env):
    page = scorecard.render(card)
    assert "Scorecard" in page and "unused-skill" in page and "new pyright version" in page
    result = CliRunner().invoke(app, ["scorecard", "--weeks", "2"],
                                env={"AX_CONFIG": str(env.config_path)})  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "corrections" in result.output
    state = serve.collect_state(env.config, usage_of=lambda c: [], runs_of=lambda c: [])
    assert 'href="/scorecard"' in serve.render_body(state)


def test_the_scorecard_note_is_markdown_for_the_vault(card, env):
    note = scorecard.markdown(card)
    assert note.startswith("---\n") and "type: scorecard" in note
    assert "| Week |" in note and "| 2026-W43 |" in note
    assert "new pyright version" in note and "unused-skill" in note
    result = CliRunner().invoke(app, ["scorecard", "--weeks", "2", "--note"],
                                env={"AX_CONFIG": str(env.config_path)})  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "| Week |" in (env.config.vault / "Scorecard.md").read_text()

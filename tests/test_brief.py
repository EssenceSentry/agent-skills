import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ax import brief, profile, usage
from ax.cli import app
from ax.config import load
from ax.sync import sync
from conftest import CLAUDE_SESSION

NOW = datetime.now(UTC)


@pytest.fixture
def home(env, tmp_path):
    repo = tmp_path / "Repos" / "demo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "AGENTS.md").write_text("# Demo conventions\n")
    env.config_path.write_text(
        env.config_path.read_text()
        + f'\n[profile]\nrepos_root = "{tmp_path / "Repos"}"\nextra_dirs = []\n'
    )
    env.config = load(env.config_path)
    env.repo = repo
    add = profile.add
    add(
        env.config,
        "small-steps",
        rule="Do the requested step and stop.",
        tools=["claude", "codex", "workers"],
    )
    add(env.config, "parent-only", rule="Ask before launching agents.", tools=["claude", "codex"])
    add(env.config, "demo-uv", rule="In demo, never run a plain uv sync.", scope="repo:demo",
        tools=["claude", "codex", "workers"])  # fmt: skip
    add(env.config, "other-repo", rule="Other repo rule.", scope="repo:other",
        tools=["claude", "codex", "workers"])  # fmt: skip
    return env


def window(used, resets_in_hours=48):
    return usage.Window("claude", "weekly", used, NOW + timedelta(hours=resets_in_hours), NOW,
                        "fresh", 10080)  # fmt: skip


def test_a_review_brief_carries_the_worker_rules_for_that_repo(home):
    found = brief.build(
        home.config, "review", repo=home.repo, task="Check the parser handles empty input.",
        paths=["src/parse.py"], accept=["Each finding names a failing input."],
        windows=[window(30)],
    )  # fmt: skip
    text = found.text
    assert "Check the parser handles empty input." in text and "src/parse.py" in text
    assert "Do the requested step and stop." in text and "plain uv sync" in text
    assert "Ask before launching agents." not in text  # not marked for workers
    assert "Other repo rule." not in text
    assert str(home.repo / "AGENTS.md") in text
    assert "not the author's" in text  # reviewers form their own view
    assert found.plan["profile"] == "inspect" and found.plan["agents"] == 1
    assert found.plan["budget_usd"] == brief.KINDS["review"].budget


def test_the_budget_shrinks_when_usage_runs_short(home):
    found = brief.build(home.config, "implement", repo=home.repo, task="x", windows=[window(85)])
    assert found.plan["budget_usd"] == brief.KINDS["implement"].budget / 2
    assert "85%" in found.plan["usage_note"] and "85%" in found.text


def test_an_implement_brief_names_owned_files_and_a_worktree(home):
    found = brief.build(
        home.config, "implement", repo=home.repo, task="Add a flag.", paths=["src/cli.py"],
        windows=[],
    )  # fmt: skip
    assert "You own" in found.text and "src/cli.py" in found.text
    assert "worktree add ../demo-" in found.text
    assert found.plan["profile"] == "verify"
    assert "usage is unknown" in found.plan["usage_note"]


def test_a_continue_brief_points_at_the_session_note(home):
    sync(home.config)
    found = brief.build(
        home.config, "continue", repo=home.repo, task="Finish the retry helper.",
        session=CLAUDE_SESSION[:8], windows=[],
    )  # fmt: skip
    assert "Retry for fetch helper" in found.text and ".md" in found.text


def test_unknown_kinds_and_sessions_are_refused(home):
    with pytest.raises(ValueError, match="kind"):
        brief.build(home.config, "audit", repo=home.repo, task="x", windows=[])
    with pytest.raises(ValueError, match="no archived session"):
        brief.build(home.config, "continue", repo=home.repo, task="x", session="nope", windows=[])


def test_cli_writes_the_brief_outside_the_repo_and_prints_the_plan(home, monkeypatch):
    monkeypatch.setattr(brief, "_windows", lambda config: [window(20)])
    result = CliRunner().invoke(
        app,
        ["brief", "scout", "--repo", str(home.repo), "--task", "Where is the cache key built?",
         "--json"],
        env={"AX_CONFIG": str(home.config_path)},
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    path = plan["brief"]
    assert (
        path.startswith(str(home.config.data))
        and "Where is the cache key built?" in Path(path).read_text()
    )
    assert plan["command"][1].endswith("worker.py") and plan["command"][2] == "run"
    assert "worker.py" in " ".join(plan["command"]) and plan["model"] == brief.KINDS["scout"].model
    text = CliRunner().invoke(
        app, ["brief", "scout", "--repo", str(home.repo), "--task", "t"],
        env={"AX_CONFIG": str(home.config_path)},
    )  # fmt: skip
    assert "approval" in text.output.lower()


def test_compile_writes_worker_definitions_for_both_tools(home):
    profile.compile_profile(home.config, apply=True)
    agent = (home.claude_home / "agents" / "ax-review.md").read_text()
    assert agent.startswith("---\nname: ax-review\n")
    assert (
        "Do the requested step and stop." in agent and "Ask before launching agents." not in agent
    )
    assert "In demo:" in agent and "tools: Read, Grep, Glob, Bash" in agent
    codex = (home.codex_home / "ax-review.config.toml").read_text()
    assert 'sandbox_mode = "read-only"' in codex and "Do the requested step and stop." in codex
    implement = (home.codex_home / "ax-implement.config.toml").read_text()
    assert 'sandbox_mode = "workspace-write"' in implement
    assert profile.compile_profile(home.config) == []


def test_compile_leaves_a_hand_written_agent_alone(home):
    agents = home.claude_home / "agents"
    agents.mkdir(parents=True)
    (agents / "ax-review.md").write_text("---\nname: ax-review\n---\nMine.\n")
    profile.compile_profile(home.config, apply=True)
    assert (agents / "ax-review.md").read_text().endswith("Mine.\n")


def test_a_codex_plan_uses_the_codex_runner_and_the_configured_model(home):
    (home.codex_home / "config.toml").write_text('model = "gpt-test"\n')
    found = brief.write(
        home.config,
        brief.build(home.config, "review", repo=home.repo, task="t", provider="codex", windows=[]),
    )
    command = found.plan["command"]
    assert command[1].endswith("codex_worker.py") and command[2] == "run"
    assert command[command.index("--model") + 1] == "gpt-test"
    assert command[command.index("--permission") + 1] == "read-only"

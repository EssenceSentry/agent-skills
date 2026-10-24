import json
import plistlib
from dataclasses import replace

import pytest

from ax import glue

AX = "/usr/local/bin/ax"


@pytest.fixture
def homes(env, tmp_path):
    agents = tmp_path / "agents-skills"
    launch = tmp_path / "LaunchAgents"
    config = replace(env.config)
    return config, agents, launch


def commands(settings, event):
    return [h["command"] for group in settings["hooks"].get(event, []) for h in group["hooks"]]


def test_hooks_are_added_without_touching_existing_settings(homes):
    config, _, _ = homes
    settings = config.claude_home / "settings.json"
    existing = {
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]},
    }
    settings.write_text(json.dumps(existing))
    changes = glue.plan_hooks(config, ax=AX)
    claude = next(c for c in changes if c.path == settings)
    after = json.loads(claude.after)
    assert after["model"] == "opus"
    assert "mine" in commands(after, "Stop")
    assert any(AX in c for c in commands(after, "Stop"))
    assert any(AX in c for c in commands(after, "SessionEnd"))


def test_codex_hooks_file_is_created_with_a_short_timeout(homes):
    config, _, _ = homes
    changes = glue.plan_hooks(config, ax=AX)
    codex = next(c for c in changes if c.path == config.codex_home / "hooks.json")
    after = json.loads(codex.after)
    [group] = after["hooks"]["SessionEnd"]
    assert group["hooks"][0]["timeout"] <= 3
    assert codex.before is None


def test_applying_hooks_twice_changes_nothing_the_second_time(homes):
    config, _, _ = homes
    glue.apply(glue.plan_hooks(config, ax=AX))
    assert [c for c in glue.plan_hooks(config, ax=AX) if c.before != c.after] == []
    backups = list(config.codex_home.glob("hooks.json.ax-backup-*"))
    assert backups == []  # nothing existed before, so nothing to back up


def test_applying_backs_up_files_it_changes(homes):
    config, _, _ = homes
    (config.claude_home / "settings.json").write_text('{"model": "opus"}')
    glue.apply(glue.plan_hooks(config, ax=AX))
    [backup] = config.claude_home.glob("settings.json.ax-backup-*")
    assert json.loads(backup.read_text()) == {"model": "opus"}


def test_the_schedule_syncs_every_half_hour(homes):
    config, _, launch = homes
    [change] = glue.plan_schedule(config, ax=AX, launch_agents=launch)
    plist = plistlib.loads(change.after.encode())
    assert plist["StartInterval"] == 1800
    assert AX in " ".join(plist["ProgramArguments"])
    assert "vault" not in " ".join(plist["ProgramArguments"])  # pushing stays opt-in


def test_the_schedule_can_include_the_vault_push(homes):
    config, _, launch = homes
    [change] = glue.plan_schedule(config, ax=AX, launch_agents=launch, with_vault=True)
    assert "vault push" in " ".join(plistlib.loads(change.after.encode())["ProgramArguments"])


def test_skills_are_linked_only_where_nothing_is_installed(homes, tmp_path):
    config, agents, _ = homes
    repo = tmp_path / "repo-skills"
    for name in ("alpha", "beta", "gamma"):
        (repo / name).mkdir(parents=True)
        (repo / name / "SKILL.md").write_text(f"name: {name}\n")
    claude_skills = config.claude_home / "skills"
    claude_skills.mkdir()
    (claude_skills / "beta").mkdir()  # someone else's copy
    legacy = config.codex_home / "skills"
    (legacy / "gamma").mkdir(parents=True)  # Codex would list gamma twice

    actions = glue.plan_skill_links(
        config, names=["alpha", "beta", "gamma"], repo_skills=repo, agents_skills=agents
    )
    by = {(a.name, a.tool): a for a in actions}
    assert by[("alpha", "claude")].kind == "link"
    assert by[("alpha", "codex")].kind == "link"
    assert by[("beta", "claude")].kind == "conflict"
    assert by[("gamma", "codex")].kind == "conflict"
    assert "twice" in by[("gamma", "codex")].reason

    glue.apply_links(actions)
    assert (claude_skills / "alpha").resolve() == (repo / "alpha").resolve()
    assert (agents / "alpha").is_symlink()
    assert not (claude_skills / "beta").is_symlink()
    again = glue.plan_skill_links(config, names=["alpha"], repo_skills=repo, agents_skills=agents)
    assert {a.kind for a in again} == {"linked"}


def test_install_commands_are_dry_runs_by_default(env, monkeypatch):
    from typer.testing import CliRunner

    from ax.cli import app

    runner = CliRunner()
    environment = {"AX_CONFIG": str(env.config_path)}
    hooks = runner.invoke(app, ["hooks", "install"], env=environment)
    assert hooks.exit_code == 0, hooks.output
    assert "would write" in hooks.output
    assert not (env.codex_home / "hooks.json").exists()

    monkeypatch.setattr(glue, "launch_agents_dir", lambda: env.root / "LaunchAgents")
    schedule = runner.invoke(app, ["schedule", "install"], env=environment)
    assert "would write" in schedule.output
    assert not (env.root / "LaunchAgents").exists()

    links = runner.invoke(app, ["skills", "link", "session-recall"], env=environment)
    assert links.exit_code == 0, links.output
    assert "would link" in links.output


def test_the_schedule_finds_homebrew_and_user_tools():
    from ax.config import load

    config = load("/nonexistent/config.toml")
    [change] = glue.plan_schedule(config, ax=AX, launch_agents=config.data)
    path = plistlib.loads(change.after.encode())["EnvironmentVariables"]["PATH"]
    assert "/opt/homebrew/bin" in path and ".local/bin" in path


def test_the_hooks_dry_run_shows_only_hooks(env):
    from typer.testing import CliRunner

    from ax.cli import app

    (env.claude_home / "settings.json").write_text('{"env":{"TOKEN":"sekret-value-123"}}')
    result = CliRunner().invoke(app, ["hooks", "install"], env={"AX_CONFIG": str(env.config_path)})
    assert "would write" in result.output
    assert "sekret-value-123" not in result.output

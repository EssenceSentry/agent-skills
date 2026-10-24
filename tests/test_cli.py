import json

from typer.testing import CliRunner

from ax.cli import app

runner = CliRunner()


def test_sync_command_reports_counts(env):
    result = runner.invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 0, result.output
    assert "parsed 6" in result.output
    assert "wrote 5" in result.output


def test_doctor_flags_short_claude_retention_and_unknown_records(env):
    runner.invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    result = runner.invoke(app, ["doctor"], env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 1
    assert "cleanupPeriodDays" in result.output
    assert "future-thing" in result.output


def test_doctor_passes_with_long_retention_and_a_git_vault(env):
    (env.claude_home / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 3650}))
    (env.vault / ".git").mkdir()
    runner.invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    result = runner.invoke(app, ["doctor"], env={"AX_CONFIG": str(env.config_path)})
    assert "cleanupPeriodDays 3650" in result.output
    assert result.exit_code == 0, result.output


def test_sync_while_another_runs_exits_quietly(env):
    from ax.sync import lock

    with lock(env.config):
        result = runner.invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 0
    assert "another ax sync is running" in result.output


def test_the_cli_loads_even_when_a_feature_dependency_is_missing(monkeypatch):
    # Hooks and launchd run `ax sync`; a missing library for another command must not stop it.
    import importlib
    import sys

    import ax.cli
    import ax.exp

    monkeypatch.setitem(sys.modules, "yaml", None)
    importlib.reload(ax.exp)
    importlib.reload(ax.cli)

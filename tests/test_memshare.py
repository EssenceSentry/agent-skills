import json

from typer.testing import CliRunner

from ax import memshare
from ax.cli import app


def memory(env, project, name, body, *, kind="feedback"):
    folder = env.claude_home / "projects" / project / "memory"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.md"
    path.write_text(f"---\nname: {name}\ndescription: about {name}\ntype: {kind}\n---\n\n{body}\n")
    return path


def notes(env):
    folder = env.codex_home / "memories" / "extensions" / "ad_hoc" / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_each_claude_memory_becomes_one_codex_note(env):
    folder = notes(env)
    memory(env, "-Users-me-Repos-demo", "no-green", "Avoid green accents in designs.")
    memory(
        env, "-Users-me-Repos-demo", "token", "The key is ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    )
    (env.claude_home / "projects" / "-Users-me-Repos-demo" / "memory" / "MEMORY.md").write_text(
        "- index"
    )
    written = memshare.export(env.config)
    assert sorted(p.name for p in written) == [
        "claude-Repos-demo-no-green.md",
        "claude-Repos-demo-token.md",
    ]
    text = (folder / "claude-Repos-demo-no-green.md").read_text()
    assert "Avoid green accents" in text and "Claude Code" in text and "Repos-demo" in text
    assert "ghp_abcdefghij" not in (folder / "claude-Repos-demo-token.md").read_text()
    assert memshare.export(env.config) == []  # nothing changed


def test_a_changed_memory_edits_its_note_and_a_deleted_one_says_so(env):
    folder = notes(env)
    path = memory(env, "-Users-me-Repos-demo", "tabs", "Use tabs.")
    memshare.export(env.config)
    memory(env, "-Users-me-Repos-demo", "tabs", "Use four spaces, not tabs.")
    [edited] = memshare.export(env.config)
    assert "four spaces" in edited.read_text() and len(list(folder.iterdir())) == 1
    path.unlink()
    [removed] = memshare.export(env.config)
    assert removed == edited and "deleted" in removed.read_text()
    assert memshare.export(env.config) == []


def test_nothing_is_written_when_codex_has_no_ad_hoc_notes(env):
    memory(env, "-Users-me-Repos-demo", "tabs", "Use tabs.")
    assert memshare.export(env.config) == []
    assert not (env.codex_home / "memories" / "extensions" / "ad_hoc").exists()


def test_claudes_start_hook_carries_codexs_memory_summary_and_codexs_does_not(env):
    summary = env.codex_home / "memories" / "memory_summary.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("v1\n\n## User Profile\n\nPrefers concise answers.\n")
    run = {"AX_CONFIG": str(env.config_path)}
    claude = CliRunner().invoke(app, ["hooks", "start", "--tool", "claude"], input="{}", env=run)
    text = json.loads(claude.output)["hookSpecificOutput"]["additionalContext"]
    assert "What Codex remembers" in text and "Prefers concise answers." in text
    codex = CliRunner().invoke(app, ["hooks", "start", "--tool", "codex"], input="{}", env=run)
    assert "Prefers concise answers." not in codex.output


def test_sync_passes_claudes_memories_to_codex_unless_turned_off(env):
    folder = notes(env)
    memory(env, "-Users-me-Repos-demo", "tabs", "Use tabs.")
    run = {"AX_CONFIG": str(env.config_path)}
    env.config_path.write_text(env.config_path.read_text() + "\n[memory]\nshare = false\n")
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert list(folder.iterdir()) == []
    env.config_path.write_text(env.config_path.read_text().replace("share = false", "share = true"))
    assert CliRunner().invoke(app, ["sync"], env=run).exit_code == 0
    assert [p.name for p in folder.iterdir()] == ["claude-Repos-demo-tabs.md"]

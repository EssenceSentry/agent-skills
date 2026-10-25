import json
import subprocess

import pytest
from typer.testing import CliRunner

from ax import profile
from ax.cli import app
from ax.config import load


@pytest.fixture
def home(env, tmp_path):
    """A config whose repos live in tmp, with one git repo named demo."""
    repo = tmp_path / "Repos" / "demo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    agents = tmp_path / "agents"
    env.config_path.write_text(
        env.config_path.read_text()
        + f'agents_home = "{agents}"\n\n[profile]\nrepos_root = "{tmp_path / "Repos"}"\n'
        + "extra_dirs = []\n"
    )
    env.config = load(env.config_path)
    env.repo = repo
    return env


def rule(home, rule_id, **fields):
    return profile.add(home.config, rule_id, **fields)


def test_instruction_files_include_skills_linked_from_a_repository(home):
    # `ax skills link` puts symlinks in the skills folders; their SKILL.md still counts.
    real = home.repo / "skills" / "jobs"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("---\nname: jobs\n---\nRegister long jobs.\n")
    linked = home.config.claude_home / "skills"
    linked.mkdir(parents=True, exist_ok=True)
    (linked / "jobs").symlink_to(real)
    assert linked / "jobs" / "SKILL.md" in profile._instruction_files(home.config)


def test_seed_writes_the_starting_rules_once(home):
    written = profile.seed(home.config)
    rules = profile.load_rules(home.config)
    assert len(written) == len(rules) >= 9
    assert {"no-coauthor-trailer", "ds-models-uv"} <= {r.id for r in rules}
    assert all(r.rule and r.level in profile.LEVELS for r in rules)
    assert profile.seed(home.config) == []  # never overwrites


def test_rules_are_validated(home):
    with pytest.raises(ValueError):
        rule(home, "Bad Id", rule="x")
    with pytest.raises(ValueError):
        rule(home, "ok", rule="x", level="shout")
    with pytest.raises(ValueError):
        rule(home, "ok", rule="x", scope="team:x")
    with pytest.raises(ValueError):
        rule(home, "ok", rule="")


def test_compile_previews_by_default_and_applies_on_request(home):
    claude_md = home.claude_home / "CLAUDE.md"
    claude_md.write_text("# My notes\n\nKeep this paragraph.\n")
    codex_md = home.codex_home / "AGENTS.md"
    codex_md.write_text("Handle tasks in the current agent by default.")
    rule(home, "small-steps", rule="Do the requested step and stop.")
    rule(home, "demo-uv", rule="In demo, never run a plain uv sync.", scope="repo:demo")
    changes = profile.compile_profile(home.config)
    assert {c.path for c in changes} == {claude_md, codex_md, home.repo / "CLAUDE.local.md"}
    assert claude_md.read_text() == "# My notes\n\nKeep this paragraph.\n"  # preview only
    profile.compile_profile(home.config, apply=True)
    text = claude_md.read_text()
    assert text.startswith("# My notes\n\nKeep this paragraph.\n")
    assert "Do the requested step and stop." in text and "plain uv sync" not in text
    codex = codex_md.read_text()
    assert codex.startswith("Handle tasks in the current agent by default.")
    assert "Do the requested step and stop." in codex
    assert "In demo:" in codex and "plain uv sync" in codex
    local = (home.repo / "CLAUDE.local.md").read_text()
    assert "plain uv sync" in local and "Do the requested step" not in local
    assert "CLAUDE.local.md" in (home.repo / ".git" / "info" / "exclude").read_text()
    assert profile.compile_profile(home.config) == []  # nothing left to change


def test_editing_a_rule_replaces_only_the_block(home):
    rule(home, "small-steps", rule="Do the requested step and stop.")
    profile.compile_profile(home.config, apply=True)
    claude_md = home.claude_home / "CLAUDE.md"
    claude_md.write_text(claude_md.read_text() + "\nA line I added below.\n")
    rule(home, "small-steps", rule="Do the requested step, then stop.", replace=True)
    profile.compile_profile(home.config, apply=True)
    text = claude_md.read_text()
    assert "then stop." in text and "Do the requested step and stop." not in text
    assert text.count(profile.START) == 1 and "A line I added below." in text


def test_proposed_and_retired_rules_are_not_compiled(home):
    rule(home, "live", rule="Live rule.")
    rule(home, "maybe", rule="Proposed rule.", status="proposed")
    rule(home, "old", rule="Retired rule.", status="retired")
    profile.compile_profile(home.config, apply=True)
    text = (home.claude_home / "CLAUDE.md").read_text()
    assert "Live rule." in text and "Proposed rule." not in text and "Retired rule." not in text


def test_check_finds_instructions_that_contradict_a_rule(home):
    profile.seed(home.config)
    skill = home.claude_home / "skills" / "commit-guidelines" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "# Commits\n\n- **Keep the `Co-Authored-By: … Claude …` trailer on.** It is the only "
        "reliable way AI assistance gets attributed; without it, measurement falls back.\n"
    )
    (home.claude_home / "settings.json").write_text(json.dumps({"attribution": False}))
    found = profile.check(home.config)
    conflicts = [f for f in found if f.kind == "conflict"]
    assert any(
        f.rule == "no-coauthor-trailer" and f.path == skill and f.line == 3 for f in conflicts
    )
    (home.claude_home / "settings.json").write_text(json.dumps({}))
    found = profile.check(home.config)
    assert any(f.kind == "setting" and "attribution" in f.message for f in found)


def test_check_lists_feedback_memories_the_profile_does_not_cover(home):
    profile.seed(home.config)
    memory = home.claude_home / "projects" / "-Users-me-Repos-x" / "memory"
    memory.mkdir(parents=True)
    (memory / "new-pref.md").write_text(
        "---\nname: new-pref\ntype: feedback\n---\nAlways use tabs.\n"
    )
    (memory / "covered.md").write_text(
        "---\nname: no-claude-coauthor-trailer\ntype: feedback\n---\nx\n"
    )
    (memory / "fact.md").write_text("---\nname: fact\ntype: project\n---\nx\n")
    uncovered = [f for f in profile.check(home.config) if f.kind == "uncovered"]
    assert [f.path.name for f in uncovered] == ["new-pref.md"]


def cli(home, *args):
    return CliRunner().invoke(app, ["profile", *args], env={"AX_CONFIG": str(home.config_path)})


def test_cli_list_compile_and_check(home):
    assert cli(home, "seed").exit_code == 0
    listed = json.loads(cli(home, "list", "--json").stdout)
    assert any(r["id"] == "no-coauthor-trailer" for r in listed)
    preview = cli(home, "compile")
    assert preview.exit_code == 0 and "+- Never add" in preview.stdout
    assert not (home.claude_home / "CLAUDE.md").exists()
    assert cli(home, "compile", "--apply").exit_code == 0
    assert (home.claude_home / "CLAUDE.md").exists()
    (home.claude_home / "settings.json").write_text("{}")
    assert cli(home, "check").exit_code == 1


def test_a_sentence_that_restates_the_rule_across_lines_is_not_a_conflict(home):
    profile.seed(home.config)
    memory = home.claude_home / "projects" / "-Users-me-Repos-y" / "memory"
    memory.mkdir(parents=True)
    (memory / "conventions.md").write_text(
        "---\nname: conventions\ntype: project\n---\nCommit on main. Never add a\n"
        "`Co-Authored-By: Claude ...` trailer to any commit message.\n"
    )
    assert not [f for f in profile.check(home.config) if f.kind == "conflict"]


def test_a_rules_own_memories_and_kept_local_memories_are_not_reported(home):
    profile.seed(home.config)
    memory = home.claude_home / "projects" / "-Users-me-Repos-z" / "memory"
    memory.mkdir(parents=True)
    (memory / "feedback_exploratory_pacing.md").write_text(
        "---\nname: feedback-exploratory-pacing\ntype: feedback\n---\nOffer, don't push.\n"
    )
    (memory / "query-style.md").write_text("---\nname: query-style\ntype: feedback\n---\nx\n")
    (profile.rules_dir(home.config).parent / "keep-local.txt").write_text(
        "# project knowledge\nquery-style\n"
    )
    assert not [f for f in profile.check(home.config) if f.kind == "uncovered"]


def test_trash_is_skipped_and_acknowledged_conflicts_do_not_fail(home):
    profile.seed(home.config)
    line = "- **Keep the `Co-Authored-By: … Claude …` trailer on.**\n"
    for folder in ("pixability-dev", ".trash/123/pixability-dev"):
        skill = home.claude_home / "plugins" / folder / "skills" / "commit-guidelines" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(line)
    (home.claude_home / "settings.json").write_text(json.dumps({"attribution": False}))
    conflicts = [f for f in profile.check(home.config) if f.kind == "conflict"]
    assert len(conflicts) == 1 and ".trash" not in str(conflicts[0].path)
    (profile.rules_dir(home.config).parent / "acknowledged.txt").write_text(
        "# conflicts the guard hook handles\nno-coauthor-trailer pixability-dev/skills/commit-guidelines\n"
    )
    found = profile.check(home.config)
    assert [f.kind for f in found if f.rule == "no-coauthor-trailer"] == ["acknowledged"]
    assert cli(home, "check").exit_code == 0


def test_attribution_hidden_in_object_form_counts_as_off(home):
    profile.seed(home.config)
    settings = {"attribution": {"commit": "", "pr": "", "sessionUrl": False}}
    (home.claude_home / "settings.json").write_text(json.dumps(settings))
    assert not [f for f in profile.check(home.config) if f.kind == "setting"]
    settings["attribution"]["commit"] = "Co-Authored-By: Claude"
    (home.claude_home / "settings.json").write_text(json.dumps(settings))
    assert [f for f in profile.check(home.config) if f.kind == "setting"]

import json
import subprocess
import sys

import pytest
import yaml

from ax import lab, profile
from ax.store import Store


@pytest.fixture
def built(env):
    profile.seed(env.config)
    return lab.build(env.config)


def test_build_packages_the_rules_as_a_plugin_with_hooks(built, env):
    manifest = json.loads((built / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "ax-profile"
    rules = (built / "rules.md").read_text()
    assert "Co-Authored-By" in rules and "In ds-models:" in rules
    hooks = json.loads((built / "hooks" / "hooks.json").read_text())["hooks"]
    assert "${CLAUDE_PLUGIN_ROOT}" in hooks["SessionStart"][0]["hooks"][0]["command"]
    guard = hooks["PreToolUse"][0]
    assert guard["matcher"] == "Bash" and "--tool claude" in guard["hooks"][0]["command"]


def test_the_session_hook_injects_the_rules_as_context(built):
    done = subprocess.run(
        [sys.executable, str(built / "hooks" / "session_start.py")],
        capture_output=True, text=True, check=True,
        env={"CLAUDE_PLUGIN_ROOT": str(built)},
    )  # fmt: skip
    context = json.loads(done.stdout)["hookSpecificOutput"]
    assert context["hookEventName"] == "SessionStart"
    assert "Co-Authored-By" in context["additionalContext"]


def test_starter_cases_have_prompts_and_graders(built):
    cases = sorted(p.parent.name for p in (built / "evals").glob("*/prompt.md"))
    assert {"no-coauthor-trailer", "stage-explicit-paths", "do-only-what-is-asked",
            "agents-within-limits", "no-green-ui"} <= set(cases)  # fmt: skip
    for case in cases:
        folder = built / "evals" / case
        assert list((folder / "graders").glob("*.md")), case
        front = (folder / "prompt.md").read_text().split("---")[1]
        assert yaml.safe_load(front)["max_turns"] >= 5
    trailer = built / "evals" / "no-coauthor-trailer"
    assert yaml.safe_load((trailer / "case.yaml").read_text())["context"]["scaffold_script"]


def test_build_keeps_cases_the_user_edited(built, env):
    prompt = built / "evals" / "no-green-ui" / "prompt.md"
    prompt.write_text(prompt.read_text() + "\nEdited.\n")
    lab.build(env.config)
    assert prompt.read_text().endswith("Edited.\n")


def write_claude_session(env, tmp_path):
    path = tmp_path / "session.jsonl"
    records = [
        {"type": "user", "message": {"role": "user", "content": "Set up the repo."}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
        {"type": "user", "message": {"role": "user", "content": "Now commit it."}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Committed with a trailer."}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "user", "message": {"role": "user", "content": "Don't add the co-author trailer."}},
    ]  # fmt: skip
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    with Store(env.config.db_path) as store:
        store.db.execute(
            "INSERT INTO sessions (key, provider, session_id, kind, source_path, updated_at) "
            "VALUES ('k1', 'claude', 'sess-1', 'main', ?, 'x')",
            (str(path),),
        )
        store.commit()


def test_cut_turns_a_corrected_moment_into_a_history_case(built, env, tmp_path):
    write_claude_session(env, tmp_path)
    case = lab.cut(env.config, "sess-1", turn=2, name="trailer-moment")
    history = [json.loads(x) for x in (case / "history.jsonl").read_text().splitlines()]
    assert len(history) == 2  # everything before the second request
    assert "Now commit it." in (case / "prompt.md").read_text()
    rubric = (case / "graders" / "avoids-correction.md").read_text()
    assert "Don't add the co-author trailer." in rubric
    assert (
        yaml.safe_load((case / "case.yaml").read_text())["context"]["history_file"]
        == "history.jsonl"
    )


def test_cut_refuses_a_turn_that_does_not_exist(built, env, tmp_path):
    write_claude_session(env, tmp_path)
    with pytest.raises(ValueError, match="turn"):
        lab.cut(env.config, "sess-1", turn=9, name="nope")


def test_run_builds_a_bounded_two_arm_eval_command(built, env):
    command = lab.command(env.config, runs=1, model="sonnet", max_cost=5, case="no-*")
    assert command[:4] == ["claude", "plugin", "eval", str(built)]
    assert command[command.index("--ablation") + 1] == "with-without"
    assert "--scaffold" in command and "--trust-plugin" in command and "--no-publish" in command
    assert command[command.index("--max-cost-usd") + 1] == "5"
    assert command[command.index("--case") + 1] == "no-*"


def test_cases_are_tagged_by_whether_they_need_a_shell(built):
    def tags(case):
        front = (built / "evals" / case / "prompt.md").read_text().split("---")[1]
        return yaml.safe_load(front)["tags"]

    assert "shell" in tags("no-coauthor-trailer") and "no-shell" in tags("no-green-ui")


def test_no_shell_runs_drop_bash_and_keep_to_shell_free_cases(built, env):
    command = lab.command(env.config, no_shell=True)
    assert not any(arg.startswith("Bash") for arg in command)
    assert command[command.index("--tag") + 1] == "no-shell"


def test_the_summary_reports_each_case_and_flags_errors():
    result = {
        "costUsd": 0.42,
        "cases": [
            {"name": "a", "aggregates": {"score": 1, "scoreWithout": 0, "delta": 1},
             "arms": {"with": [{"error": None}], "without": [{"error": None}]}},
            {"name": "b", "aggregates": {"score": 0, "scoreWithout": 0, "delta": 0},
             "arms": {"with": [{"error": "sandbox refused"}], "without": [{}]}},
        ],
    }  # fmt: skip
    lines, errored = lab.summary(result)
    assert errored == ["b"]
    assert any(line.startswith("a ") and "+1.00" in line for line in lines)
    assert any("sandbox refused" in line for line in lines)

import io
import json
import subprocess
import sys

import pytest

from ax import glue, guard, profile


@pytest.fixture
def rules(env):
    profile.seed(env.config)
    profile.compile_profile(env.config, apply=True)
    return json.loads(guard.rules_path(env.config.data).read_text())


@pytest.fixture
def ds_models(tmp_path):
    repo = tmp_path / "Repos" / "ds-models"
    (repo / "models").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def blocked(rules, command, cwd="/tmp"):
    hit = guard.evaluate(rules, command, cwd)
    return hit["id"] if hit else None


def test_compile_writes_the_guard_rules(rules):
    assert {"no-coauthor-trailer", "stage-explicit-paths", "ds-models-uv"} <= {
        r["id"] for r in rules
    }
    assert all(r["pattern"] and r["message"] for r in rules)


@pytest.mark.parametrize(
    ("command", "rule"),
    [
        (
            'git commit -m "Fix x\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"',
            "no-coauthor-trailer",
        ),
        ("git commit -F - <<'EOF'\nFix\n\nCo-authored-by: Claude <x>\nEOF", "no-coauthor-trailer"),
        ('git commit -m "Fix the parser"', None),
        ("git add -A", "stage-explicit-paths"),
        ("git add . && git commit -m x", "stage-explicit-paths"),
        ("git commit -am 'x'", "stage-explicit-paths"),
        ("git add src/ax/guard.py tests/test_guard.py", None),
        ("git add ./src/ax/guard.py", None),
    ],
)
def test_global_rules(rules, command, rule):
    assert blocked(rules, command) == rule


def test_repo_rules_apply_only_inside_that_repo(rules, ds_models, tmp_path):
    inside = str(ds_models / "models")
    assert blocked(rules, "uv sync", inside) == "ds-models-uv"
    assert blocked(rules, "uv run --active python -c 'print(1)'", inside) == "ds-models-uv"
    assert blocked(rules, "cd x && uv sync && echo ok", inside) == "ds-models-uv"
    assert blocked(rules, "uv run python scripts/bootstrap_dev.py", inside) is None
    assert blocked(rules, "uv sync --help", inside) is None
    assert blocked(rules, "uv sync", str(tmp_path)) is None


def run_main(env, payload, tool="claude"):
    out = io.StringIO()
    code = guard.main(
        ["--tool", tool, "--data", str(env.config.data)], stdin=io.StringIO(payload), stdout=out
    )
    return code, out.getvalue()


def test_main_denies_with_a_reason_both_tools_understand(env, rules):
    payload = json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/tmp", "session_id": "s1",
         "tool_input": {"command": "git add -A"}}
    )  # fmt: skip
    code, out = run_main(env, payload, tool="codex")
    decision = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and decision["permissionDecision"] == "deny"
    assert decision["hookEventName"] == "PreToolUse"
    assert "stage-explicit-paths" in decision["permissionDecisionReason"]
    logged = [json.loads(line) for line in guard.log_path(env.config.data).read_text().splitlines()]
    assert logged[-1]["rule"] == "stage-explicit-paths" and logged[-1]["tool"] == "codex"
    assert logged[-1]["session"] == "s1"


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}}),
        json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/tmp"}),
        "not json",
        json.dumps({"tool_name": "Bash", "tool_input": {"command": ["git", "add", "-A"]}}),
    ],
)
def test_main_stays_silent_when_nothing_matches_or_input_is_odd(env, rules, payload):
    assert run_main(env, payload) == (0, "")


def test_missing_rules_never_block(env):
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "git add -A"}, "cwd": "/tmp"}
    )
    assert run_main(env, payload) == (0, "")


def test_the_guard_runs_as_its_own_quick_script(env, rules):
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "git add -A"}, "cwd": "/tmp"}
    )
    done = subprocess.run(
        [sys.executable, "-m", "ax.guard", "--tool", "claude", "--data", str(env.config.data)],
        input=payload, capture_output=True, text=True, timeout=10,
    )  # fmt: skip
    assert done.returncode == 0 and "deny" in done.stdout


def test_hooks_install_registers_the_guard_for_both_tools(env):
    changes = glue.plan_guard_hooks(env.config, guard="/bin/ax-guard")
    by_tool = {c.path.name: json.loads(c.after) for c in changes}
    claude = by_tool["settings.json"]["hooks"]["PreToolUse"]
    codex = by_tool["hooks.json"]["hooks"]["PreToolUse"]
    assert (
        claude[0]["matcher"] == "Bash"
        and claude[0]["hooks"][0]["command"] == "/bin/ax-guard --tool claude"
    )
    assert codex[0]["hooks"][0]["command"] == "/bin/ax-guard --tool codex"
    glue.apply(changes)
    again = glue.plan_guard_hooks(env.config, guard="/bin/ax-guard")
    assert all(c.before == c.after for c in again)

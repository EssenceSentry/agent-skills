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


@pytest.mark.parametrize(
    "command",
    [
        "python3 - <<'PY'\nnote = 'never run git add -A here'\nPY",
        "cat > PLAN.md <<EOF\nLive-tested on `git add -A`.\nEOF",
        'echo "avoid git add -A and git commit -am"',
        "git commit -m 'Explain why git add -A is blocked'",
    ],
)
def test_mentions_in_text_are_not_commands(rules, command):
    # Docs and scripts that mention a forbidden command don't run it.
    assert blocked(rules, command) is None


@pytest.mark.parametrize(
    "command",
    [
        # An apostrophe inside double quotes is not the start of a single-quoted string.
        "git commit -m \"Fix the parser's edge case\" && git add -A && echo 'done'",
        "echo \"don't\"; git add -A; echo 'ok'",
        "echo it\\'s; git add -A",
        # A here-string, arithmetic shift or quoted "<<EOF" is not a heredoc.
        "tr a-z A-Z <<< hello\ngit add -A",
        'git commit -m "Explain <<EOF usage"\ngit add -A',
        "echo $((1<<x))\ngit add -A",
        # <<- ends at a tab-indented delimiter; the command after it still runs.
        "cat <<-EOF\n\tnotes\n\tEOF\ngit add -A",
        "cat <<A <<B\na\nA\nb\nB\ngit add -A",
    ],
)
def test_commands_hidden_by_quoting_tricks_are_still_blocked(rules, command):
    assert blocked(rules, command) == "stage-explicit-paths"


def test_a_plain_heredoc_ends_only_at_an_unindented_delimiter(rules):
    # Bash keeps reading the body past "  EOF", so the line after it is still text.
    assert blocked(rules, "cat <<EOF\n  EOF\ngit add -A\nEOF") is None


def test_end_of_line_anchors_work_in_multi_line_commands(rules, ds_models):
    inside = str(ds_models / "models")
    assert blocked(rules, "uv sync\nuv run pytest", inside) == "ds-models-uv"


def test_commands_around_text_are_still_checked(rules):
    assert blocked(rules, "cat > a.txt <<EOF\nhello\nEOF\ngit add -A") == "stage-explicit-paths"
    assert blocked(rules, 'git commit -am "fix"') == "stage-explicit-paths"
    trailer = "git commit -F - <<'EOF'\nFix\n\nCo-Authored-By: Claude <x>\nEOF"
    assert blocked(rules, trailer) == "no-coauthor-trailer"  # message text still counts here


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


def transcript(tmp_path, *records):
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return str(path)


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant(text=None, command=None):
    content = []
    if command:
        content.append({"type": "tool_use", "name": "Bash", "input": {"command": command}})
    if text:
        content.append({"type": "text", "text": text})
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def tool_result():
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
    }


def stop(env, path, active=False):
    payload = json.dumps({"hook_event_name": "Stop", "session_id": "s1", "cwd": "/tmp",
                          "transcript_path": path, "stop_hook_active": active})  # fmt: skip
    out = io.StringIO()
    guard.main(["--tool", "claude", "--event", "stop", "--data", str(env.config.data)],
               stdin=io.StringIO(payload), stdout=out)  # fmt: skip
    return json.loads(out.getvalue()) if out.getvalue() else None


def test_claiming_tests_pass_without_running_them_keeps_the_agent_working(env, tmp_path):
    path = transcript(tmp_path, user("Fix the parser."), assistant(command="sed -i s/a/b/ p.py"),
                      tool_result(), assistant("Fixed it; all tests pass."))  # fmt: skip
    decision = stop(env, path)
    assert decision["decision"] == "block" and "no test" in decision["reason"]
    logged = [json.loads(x) for x in guard.log_path(env.config.data).read_text().splitlines()]
    assert logged[-1]["rule"] == "tests-claimed-not-run"


@pytest.mark.parametrize(
    "records",
    [
        [user("Fix it."), assistant(command="uv run pytest -q"), tool_result(),
         assistant("Fixed; 12 passed.")],
        [user("Fix it."), assistant("I changed p.py; I did not run the tests.")],
        [user("Run the tests."), assistant(command="uv run pytest"), tool_result(),
         user("Thanks. Now explain."), assistant("Sure: the change swaps a for b.")],
    ],
)  # fmt: skip
def test_honest_or_verified_endings_pass(env, tmp_path, records):
    assert stop(env, transcript(tmp_path, *records)) is None


def test_a_second_stop_after_a_block_is_let_through(env, tmp_path):
    path = transcript(tmp_path, user("Fix."), assistant("Done, all tests pass."))
    assert stop(env, path, active=True) is None


def test_hooks_install_adds_the_stop_check_for_claude(env):
    changes = glue.plan_guard_hooks(env.config, guard="/bin/ax-guard")
    claude = {c.path.name: json.loads(c.after) for c in changes}["settings.json"]
    commands = [h["command"] for e in claude["hooks"]["Stop"] for h in e["hooks"]]
    assert "/bin/ax-guard --tool claude --event stop" in commands


def run_raw(env, payload, rules_json, argv=None):
    data = env.config.data
    data.mkdir(parents=True, exist_ok=True)
    guard.rules_path(data).write_text(rules_json)
    out = io.StringIO()
    code = guard.main(argv or ["--tool", "codex", "--data", str(data)],
                      stdin=io.StringIO(json.dumps(payload)), stdout=out)  # fmt: skip
    return code, out.getvalue()


BASH = {"tool_name": "Bash", "tool_input": {"command": "git add -A"}, "cwd": "/tmp"}
RULE = {"id": "stage", "pattern": "git add -A", "message": "Stage by path."}


@pytest.mark.parametrize(
    ("payload", "rules_json"),
    [
        ({"tool_name": "Bash", "tool_input": "git add -A"}, json.dumps([RULE])),
        (BASH, json.dumps({"rules": [RULE]})),
        (BASH, json.dumps(["stage", 3, None])),
        (BASH, json.dumps([{"id": "bad", "pattern": "(unclosed", "message": "x"}])),
        (BASH, json.dumps([{"id": "nopattern", "message": "x"}])),
        ({**BASH, "cwd": 5}, json.dumps([{**RULE, "repo": "ds-models"}])),
    ],
)  # fmt: skip
def test_odd_payloads_and_rules_never_crash_the_guard(env, payload, rules_json):
    code, out = run_raw(env, payload, rules_json)
    assert code == 0 and (out == "" or json.loads(out))


def test_a_rule_missing_its_id_or_message_still_blocks_with_a_reason(env):
    code, out = run_raw(env, BASH, json.dumps([{"pattern": "git add -A"}]))
    reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    assert code == 0 and "profile" in reason


@pytest.mark.parametrize(
    "argv", [["--tool"], ["--data"], ["--event"], ["--tool", "codex", "--event"]]
)
def test_a_flag_without_its_value_does_not_crash(env, argv):
    assert guard.main(argv, stdin=io.StringIO("{}"), stdout=io.StringIO()) == 0


@pytest.mark.parametrize(
    "lines",
    [
        ["[]", '"x"', "3"],
        [json.dumps({"type": "user", "message": "a string"})],
        [json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": "pytest"}, {"type": "text", "text": "All tests pass."}]}})],
    ],
)  # fmt: skip
def test_odd_transcripts_never_crash_the_stop_check(env, tmp_path, lines):
    path = tmp_path / "odd.jsonl"
    path.write_text("\n".join(lines) + "\n")
    stop(env, str(path))  # no exception; a block is fine


def test_a_non_string_transcript_path_is_ignored(env):
    assert stop(env, 7) is None

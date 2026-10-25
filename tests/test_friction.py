"""Friction without walls: the main agent pauses once before an irreversible action and
goes on when it says why; subagents and workers stop."""

import io
import json
import subprocess

import pytest

from ax import guard, profile


@pytest.fixture
def rules(env):
    profile.seed(env.config)
    profile.compile_profile(env.config, apply=True)
    return env


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "work"
    path.mkdir()
    git = ["git", "-C", str(path)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "config", "user.email", "t@example.com"], check=True)
    subprocess.run([*git, "config", "user.name", "T"], check=True)
    (path / "a.txt").write_text("one\n")
    subprocess.run([*git, "add", "a.txt"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "first"], check=True)
    return path


def ask(env, command, cwd="/tmp", tool="claude", **fields):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
               "session_id": "s1", "tool_input": {"command": command}, **fields}  # fmt: skip
    out = io.StringIO()
    guard.main(["--tool", tool, "--data", str(env.config.data)],
               stdin=io.StringIO(json.dumps(payload)), stdout=out)  # fmt: skip
    text = out.getvalue()
    return json.loads(text)["hookSpecificOutput"]["permissionDecisionReason"] if text else None


def logged(env):
    path = guard.log_path(env.config.data)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_destructive_command_pauses_the_main_agent_and_says_what_is_at_stake(rules, repo):
    (repo / "a.txt").write_text("changed\n")
    said = ask(rules, "git reset --hard", cwd=repo)
    assert said.startswith("Pause:") and "1 uncommitted change" in said
    assert 'AX_INTENT="' in said
    assert "ask the user" not in said and "work around" not in said
    assert logged(rules)[-1]["kind"] == "pause" and logged(rules)[-1]["caller"] == "main"


def test_saying_why_lets_the_main_agent_through_and_is_logged(rules, repo):
    (repo / "a.txt").write_text("changed\n")
    assert ask(rules, 'AX_INTENT="drop my scratch edit" git reset --hard', cwd=repo) is None
    entry = logged(rules)[-1]
    assert entry["kind"] == "pass" and entry["intent"] == "drop my scratch edit"


def test_nothing_to_lose_means_no_pause(rules, repo):
    assert ask(rules, "git reset --hard", cwd=repo) is None
    assert ask(rules, "git clean -fd", cwd=repo) is None
    assert ask(rules, "git checkout -- .", cwd=repo) is None
    (repo / "loose.txt").write_text("x\n")
    assert "1 untracked file" in ask(rules, "git clean -fd", cwd=repo)


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin main",
        "git push -f",
        "git push origin --delete old-branch",
        "git push origin :old-branch",
        "git branch -D feature",
        "git stash drop",
        "git worktree remove --force ../wt",
        "rm -rf ~/Projects/old",
        "find . -name '*.parquet' -delete",
        "aws s3 rm s3://bucket/data --recursive",
        "aws s3 sync ./out s3://bucket/out --delete",
        "aws sagemaker delete-endpoint --endpoint-name x",
        "terraform destroy",
        'psql -c "DROP TABLE users"',
        "gh repo delete me/repo --yes",
    ],
)
def test_irreversible_commands_pause_the_main_agent(rules, command):
    said = ask(rules, command)
    assert said and said.startswith("Pause:"), command


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git push origin main",
        'git commit -m "Explain why git reset --hard was wrong"',
        "grep -rn 'rm -rf' .",
        "rm notes.txt",
        "rm -rf node_modules dist",
        "rm -rf /tmp/scratch",
        "echo 'DROP TABLE users' > notes.sql",
        "cat .env.toml",
        "python -c \"print('git push --force')\"",
        "cat <<'EOF'\ngit reset --hard\nEOF",
    ],
)
def test_ordinary_work_never_pauses(rules, command):
    assert ask(rules, command) is None, command


def test_a_subagent_is_stopped_and_a_reason_does_not_help(rules):
    said = ask(rules, 'AX_INTENT="told to" git push --force', agent_id="a1", agent_type="Explore")
    assert said.startswith("Stopped:") and "started you" in said
    assert logged(rules)[-1]["kind"] == "stop" and logged(rules)[-1]["caller"] == "subagent"


@pytest.mark.parametrize(
    ("meta", "caller"),
    [
        ({"originator": "codex_exec", "source": "exec"}, "worker"),
        ({"originator": "Codex Desktop", "source": {"subagent": {"thread_spawn": {}}}}, "subagent"),
        ({"originator": "Codex Desktop", "source": "vscode"}, "main"),
    ],
)
def test_codex_callers_are_told_apart_by_their_transcript(rules, tmp_path, meta, caller):
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(json.dumps({"type": "session_meta", "payload": meta}) + "\n")
    said = ask(rules, "git push --force", tool="codex", transcript_path=str(transcript))
    assert said.startswith("Stopped:" if caller != "main" else "Pause:")
    assert logged(rules)[-1]["caller"] == caller


def test_the_user_s_block_rules_pause_the_main_agent_and_stop_subagents(rules):
    said = ask(rules, "git add -A")
    assert said.startswith("Pause:") and "stage-explicit-paths" in said
    assert ask(rules, 'AX_INTENT="the repo is mine alone" git add -A') is None
    assert ask(rules, "git add -A", agent_id="a1").startswith("Stopped:")


def test_a_guard_error_lets_the_command_through_and_reports_itself(rules, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bad pattern")

    monkeypatch.setattr(guard, "destructive", broken)
    assert ask(rules, "git push --force") is None
    assert logged(rules)[-1]["kind"] == "error" and "bad pattern" in logged(rules)[-1]["error"]


# Limits the main agent sets for its subagents


def test_limits_for_this_conversation_stop_its_subagents_only(rules):
    from ax import policy

    policy.add(rules.config, r"\bnpm\s+publish\b", "We don't publish from here.", session="s1")
    said = ask(rules, "npm publish", agent_id="a1")
    assert said.startswith("Stopped:") and "We don't publish from here" in said
    assert ask(rules, "npm publish", agent_id="a1", session_id="s2") is None  # another conversation
    assert ask(rules, "npm publish") is None  # the main agent sets them; they don't bind it


def test_limits_for_every_subagent_reach_codex_workers(rules, tmp_path):
    from ax import policy

    policy.add(rules.config, r"\bnpm\s+publish\b", "No publishing by workers.")
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(json.dumps({"payload": {"source": "exec"}}) + "\n")
    said = ask(rules, "npm publish", tool="codex", transcript_path=str(transcript))
    assert said.startswith("Stopped:") and "No publishing by workers" in said


def test_a_limit_judges_what_runs_not_what_is_mentioned(rules):
    from ax import policy

    policy.add(rules.config, r"\bnpm\s+publish\b", "No publishing.")
    assert ask(rules, 'echo "npm publish is off"', agent_id="a1") is None


def test_limits_are_listed_removed_and_bad_patterns_refused(env):
    from ax import policy

    first = policy.add(env.config, r"\bnpm\s+publish\b", "No publishing.", session="s1")
    second = policy.add(env.config, r"\bdocker\s+push\b", "No image pushes.")
    assert (first["id"], second["id"]) == ("L1", "L2")
    assert [x["id"] for x in policy.listing(env.config)] == ["L1", "L2"]
    assert [x["id"] for x in policy.listing(env.config, session="s2")] == ["L2"]
    policy.remove(env.config, "L1")
    assert [x["id"] for x in policy.listing(env.config)] == ["L2"]
    with pytest.raises(ValueError, match="pattern"):
        policy.add(env.config, "(unclosed", "x")
    with pytest.raises(ValueError, match="no limit L9"):
        policy.remove(env.config, "L9")


def test_the_policy_commands_tie_a_limit_to_this_conversation(env, monkeypatch):
    from typer.testing import CliRunner

    from ax import policy
    from ax.cli import app as cli

    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "6942b4a0-7d35-4d5e-91a2-460a9fe6d7e6")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    result = CliRunner().invoke(cli, ["policy", "add", r"\bnpm\s+publish\b", "--why", "No."])
    assert result.exit_code == 0, result.output
    [limit] = policy.listing(env.config)
    assert limit["session"] == "6942b4a0-7d35-4d5e-91a2-460a9fe6d7e6"
    CliRunner().invoke(cli, ["policy", "add", r"\bdocker\s+push\b", "--why", "No.", "--all"])
    assert policy.listing(env.config)[-1]["session"] is None
    result = CliRunner().invoke(cli, ["policy", "list"])
    assert "L1" in result.output and "this conversation" in result.output
    assert CliRunner().invoke(cli, ["policy", "remove", "L1"]).exit_code == 0
    assert [x["id"] for x in policy.listing(env.config)] == ["L2"]


def test_a_brief_lists_the_limits_its_worker_works_under(env, tmp_path):
    from ax import brief, policy

    policy.add(env.config, r"\bnpm\s+publish\b", "No publishing from workers.")
    repo = tmp_path / "repo"
    repo.mkdir()
    text = brief.build(env.config, "review", repo=repo, task="Review it.", windows=[]).text
    assert "## Limits" in text and "No publishing from workers." in text
    assert "force push" in text  # the irreversible actions it can't take either

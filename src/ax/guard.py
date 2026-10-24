"""The PreToolUse guard Claude Code and Codex run before every shell command, and
Claude's stop check.

Before a command, it blocks one that a profile rule at level "block" forbids, says why,
and logs the block so the scorecard can count it. Both tools send `tool_name` "Bash"
with the command in `tool_input.command` and accept the same denial, so one script
serves both.

When Claude stops (`--event stop`), it reads the turn from the transcript: if the last
reply says tests pass but no test command ran since the user's last message, it asks
Claude to keep working, once.

It runs before every shell command, so it stays on the standard library and reads the
rules `ax profile compile --apply` prebuilds as JSON instead of the vault's notes. Bad
input or missing rules never block anything.
"""

import json
import os
import re
import sys
import time
from pathlib import Path


def rules_path(data: Path) -> Path:
    return Path(data) / "guard_rules.json"


def log_path(data: Path) -> Path:
    return Path(data) / "guard.jsonl"


def _repo_name(cwd: str) -> str | None:
    """The folder name of the git repository containing cwd, found without running git."""
    path = Path(cwd or ".")
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            return folder.name
    return None


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def code_only(command: str) -> str:
    """The command without heredoc bodies or quoted strings: what it runs, not what it mentions."""
    kept, end = [], None
    for line in command.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        if match := _HEREDOC.search(line):
            end = match.group(2)
        kept.append(line)
    text = re.sub(r"'[^']*'", "''", "\n".join(kept))
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def evaluate(rules: list[dict], command: str, cwd: str) -> dict | None:
    """The first rule the command breaks, or None.

    A rule with `where: command` looks only at what runs, so a script or doc that
    mentions a forbidden command isn't blocked; other rules read the whole text, which
    a commit message inside quotes or a heredoc needs.
    """
    repo, code = None, None
    for rule in rules:
        if rule.get("tool", "shell") != "shell":
            continue
        if rule.get("repo"):
            repo = repo or _repo_name(cwd) or ""
            if repo != rule["repo"]:
                continue
        text = command
        if rule.get("where") == "command":
            code = code_only(command) if code is None else code
            text = code
        if re.search(rule["pattern"], text):
            return rule
    return None


_TESTS_PASS = re.compile(
    r"(?i)\b(?:all |the )?tests? (?:now |all |still )?pass(?:es|ed)?\b|\b\d+ (?:tests? )?passed\b"
    r"|\btests? (?:are|is) (?:green|passing)\b"
)
_TEST_RUN = re.compile(
    r"(?i)\b(?:pytest|unittest|npm (?:run )?test|yarn test|pnpm test|bun test|go test|cargo test"
    r"|jest|vitest|tox|nox|make (?:test|check)|mvn test|gradle test|pre-commit run)\b"
)
_NOT_RUN = re.compile(r"(?i)\b(?:didn'?t|did not|haven'?t|have not|not) (?:run|re-?run)\b")


def _turn(transcript: Path) -> tuple[str, list[str]]:
    """The last reply's text and the shell commands run since the user's last message."""
    text, commands = "", []
    for line in transcript.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        content = (record.get("message") or {}).get("content")
        if record.get("type") == "user":
            is_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
            if not is_result:
                text, commands = "", []
        elif record.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "")
                elif block.get("type") == "tool_use" and block.get("name") == "Bash":
                    commands.append(str((block.get("input") or {}).get("command", "")))
    return text, commands


def stop_check(payload: dict) -> str | None:
    """Why Claude should keep working, or None to let it stop."""
    if payload.get("stop_hook_active"):
        return None  # it already continued once for this check
    try:
        text, commands = _turn(Path(payload["transcript_path"]))
    except (KeyError, OSError, TypeError):
        return None
    if not _TESTS_PASS.search(text) or _NOT_RUN.search(text):
        return None
    if any(_TEST_RUN.search(c) for c in commands):
        return None
    return (
        "You said tests pass, but no test command ran since the user's last message. "
        "Run the tests now, or say when they last ran instead of saying they pass."
    )


def _log(data: Path, entry: dict) -> None:
    try:
        log_path(data).parent.mkdir(parents=True, exist_ok=True)
        with log_path(data).open("a") as log:
            log.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry}) + "\n")
    except OSError:
        pass


def _default_data() -> Path:
    try:
        from ax.config import load

        return load().data
    except Exception:
        return Path("~/.local/share/ax").expanduser()


def main(argv=None, *, stdin=None, stdout=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    tool = argv[argv.index("--tool") + 1] if "--tool" in argv else "claude"
    data = Path(argv[argv.index("--data") + 1]) if "--data" in argv else _default_data()
    if "--event" in argv and argv[argv.index("--event") + 1] == "stop":
        try:
            payload = json.loads(stdin.read())
        except ValueError:
            return 0
        reason = stop_check(payload) if isinstance(payload, dict) else None
        if reason:
            _log(data, {"tool": tool, "rule": "tests-claimed-not-run", "cwd": payload.get("cwd"),
                        "session": payload.get("session_id")})  # fmt: skip
            stdout.write(json.dumps({"decision": "block", "reason": reason}) + "\n")
        return 0
    try:
        payload = json.loads(stdin.read())
        rules = json.loads(rules_path(data).read_text())
    except (OSError, ValueError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    hit = evaluate(rules, command, cwd)
    if not hit:
        return 0
    _log(data, {"tool": tool, "rule": hit["id"], "cwd": cwd,
                "session": payload.get("session_id"), "command": command[:300]})  # fmt: skip
    reason = (
        f"{hit['message']} (blocked by the user's profile rule {hit['id']}; "
        "if it is wrong here, ask the user rather than working around it)"
    )
    stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }) + "\n")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())

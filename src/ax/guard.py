"""The PreToolUse guard Claude Code and Codex run before every shell command.

It blocks a command that a profile rule at level "block" forbids, says why, and logs
the block so the scorecard can count it. Both tools send `tool_name` "Bash" with the
command in `tool_input.command` and accept the same denial, so one script serves both.

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


def evaluate(rules: list[dict], command: str, cwd: str) -> dict | None:
    """The first rule the command breaks, or None."""
    repo = None
    for rule in rules:
        if rule.get("tool", "shell") != "shell":
            continue
        if rule.get("repo"):
            repo = repo or _repo_name(cwd) or ""
            if repo != rule["repo"]:
                continue
        if re.search(rule["pattern"], command):
            return rule
    return None


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
    try:
        with log_path(data).open("a") as log:
            log.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": tool, "rule": hit["id"],
                "cwd": cwd, "session": payload.get("session_id"), "command": command[:300],
            }) + "\n")  # fmt: skip
    except OSError:
        pass
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

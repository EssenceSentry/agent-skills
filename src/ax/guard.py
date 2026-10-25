"""The PreToolUse guard Claude Code and Codex run before every shell command, and
Claude's stop check.

Before a command, it blocks one that a profile rule at level "block" forbids, says why,
and logs the block so the scorecard can count it. Both tools send `tool_name` "Bash"
with the command in `tool_input.command` and accept the same denial, so one script
serves both.

When Claude stops (`--event stop`), it reads the turn from the transcript: if a
sentence of the last reply says tests pass, without saying they weren't run or ran
earlier, and no command since the user's last prompt ran a test suite, it asks Claude to
keep working, once.

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


def _origin_name(git_dir: Path) -> str | None:
    """The repository name in the origin remote's URL, read from .git/config."""
    try:
        text = (git_dir / "config").read_text(errors="replace")
    except OSError:
        return None
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        elif section == '[remote "origin"]' and line.startswith("url"):
            url = line.split("=", 1)[-1].strip().rstrip("/")
            return url.rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git") or None
    return None


def _repo_names(cwd) -> set[str]:
    """Names the repository containing cwd goes by, found without running git: its
    folder, the main checkout's folder when cwd is in a worktree, and its origin's name.
    """
    path = Path(cwd if isinstance(cwd, str) and cwd else ".")
    for folder in (path, *path.parents):
        dot_git = folder / ".git"
        if not dot_git.exists():
            continue
        names, git_dir = {folder.name}, dot_git
        if dot_git.is_file():  # a worktree: "gitdir: <main>/.git/worktrees/<name>"
            try:
                pointer = dot_git.read_text(errors="replace").strip()
            except OSError:
                return names
            if pointer.startswith("gitdir:"):
                worktree_git = Path(pointer.split(":", 1)[1].strip())
                git_dir = worktree_git.parent.parent
                names.add(git_dir.parent.name)
        origin = _origin_name(git_dir)
        return names | ({origin} if origin else set())
    return set()


_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def _skip_bodies(command: str, i: int, pending: list) -> int:
    """Skip the heredoc bodies that start at `i`, in order; return where code resumes."""
    for word, tabs in pending:
        while i < len(command):
            end = command.find("\n", i)
            line = command[i : end if end >= 0 else len(command)]
            i = end + 1 if end >= 0 else len(command)
            if (line.lstrip("\t") if tabs else line) == word:
                break
    return i


def code_only(command: str) -> str:
    """The command without heredoc bodies or quoted strings: what it runs, not what it mentions.

    One pass, left to right, as the shell reads it: an apostrophe inside double quotes
    is just a character, and `<<` starts a heredoc only outside quotes, here-strings
    (`<<<`) and arithmetic (`$((…))`).
    """
    out, pending, i, n = [], [], 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\":
            out.append(command[i : i + 2])
            i += 2
        elif c == "'":
            end = command.find("'", i + 1)
            out.append("''")
            i = n if end < 0 else end + 1
        elif c == '"':
            j = i + 1
            while j < n and command[j] != '"':
                j += 2 if command[j] == "\\" else 1
            out.append('""')
            i = j + 1
        elif command.startswith("$((", i):
            end = command.find("))", i)
            end = n if end < 0 else end + 2
            out.append(command[i:end])
            i = end
        elif command.startswith("<<<", i):
            out.append("<<<")
            i += 3
        elif c == "<" and (match := _HEREDOC.match(command, i)):
            pending.append((match.group(3), match.group(1) == "-"))
            out.append(match.group(0))
            i = match.end()
        elif c == "\n" and pending:
            out.append("\n")
            i = _skip_bodies(command, i + 1, pending)
            pending = []
        else:
            out.append(c)
            i += 1
    return "".join(out)


def evaluate(rules: list[dict], command: str, cwd: str) -> dict | None:
    """The first rule the command breaks, or None.

    A rule with `where: command` looks only at what runs, so a script or doc that
    mentions a forbidden command isn't blocked; other rules read the whole text, which
    a commit message inside quotes or a heredoc needs.
    """
    repo, code = None, None
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("pattern"), str):
            continue
        if rule.get("tool", "shell") != "shell":
            continue
        if rule.get("repo"):
            repo = _repo_names(cwd) if repo is None else repo
            if rule["repo"] not in repo:
                continue
        text = command
        if rule.get("where") == "command":
            code = code_only(command) if code is None else code
            text = code
        # Line by line: `$` in a pattern means the end of a command line, not of the text.
        try:
            if re.search(rule["pattern"], text, re.MULTILINE):
                return rule
        except re.error:
            continue  # a broken pattern guards nothing; it must not stop every command
    return None


_TESTS_PASS = re.compile(
    r"(?i)\b(?:all |the )?tests? (?:now |all |still )?pass(?:es|ed)?\b|\b\d+ (?:tests? )?passed\b"
    r"|\btests? (?:are|is) (?:green|passing)\b"
)
# Test runners by program name; with a project tool, the subcommand that runs tests.
_RUNNERS = {"pytest", "py.test", "unittest", "tox", "nox", "jest", "vitest", "pytest-watch"}
_SUBCOMMANDS = {
    "npm": {"test"}, "yarn": {"test"}, "pnpm": {"test"}, "bun": {"test"}, "deno": {"test"},
    "go": {"test"}, "cargo": {"test"}, "mvn": {"test", "verify"}, "gradle": {"test"},
    "make": {"test", "check"}, "pre-commit": {"run"},
}  # fmt: skip
# Programs that only show or search text: a runner's name in their arguments isn't a run.
_READERS = {
    "rg", "grep", "cat", "head", "tail", "sed", "awk", "less", "more", "ls", "echo", "printf",
    "find", "git", "wc", "diff", "file", "stat", "which", "open", "code",
}  # fmt: skip
_HEDGE = re.compile(
    r"(?i)\b(?:didn'?t|did not|haven'?t|have not|weren'?t|were not|wasn'?t|was not|not)\s+"
    r"(?:yet\s+)?(?:been\s+)?(?:run|re-?run|execut\w*)\b"
    r"|\b(?:earlier|previously|last (?:run|time)|before (?:the|this|your))\b"
)
_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def ran_tests(command: str) -> bool:
    """Whether a shell command runs a test suite, rather than only naming a test tool."""
    for segment in re.split(r"&&|\|\||[;|\n]", code_only(command)):
        words = [w.rsplit("/", 1)[-1] for w in segment.split()]
        words = [w for w in words if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w)]
        if not words or words[0] in _READERS:
            continue
        if _RUNNERS & set(words):
            return True
        if _SUBCOMMANDS.get(words[0], set()) & set(words[1:4]):
            return True
    return False


def _unhedged_claim(text: str) -> bool:
    """Whether a sentence says tests pass without saying they weren't run or ran earlier."""
    return any(
        _TESTS_PASS.search(sentence) and not _HEDGE.search(sentence)
        for sentence in _SENTENCE.split(text)
    )


def _prompt(record: dict, content) -> bool:
    """Whether a user record is a real prompt, not a tool result, notice or meta record."""
    if record.get("isMeta"):
        return False
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return False
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    if not isinstance(content, str):
        return False
    content = content.strip()
    return bool(content) and not content.startswith(("<", "[Request interrupted"))


def _turn(transcript: Path) -> tuple[str, list[str]]:
    """The last reply's text and the shell commands run since the user's last message."""
    text, commands = "", []
    for line in transcript.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") if isinstance(record, dict) else None
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if record.get("type") == "user":
            if _prompt(record, content):
                text, commands = "", []
        elif record.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "")
                elif block.get("type") == "tool_use" and block.get("name") == "Bash":
                    given = block.get("input")
                    if isinstance(given, dict) and isinstance(given.get("command"), str):
                        commands.append(given["command"])
    return text, commands


def stop_check(payload: dict) -> str | None:
    """Why Claude should keep working, or None to let it stop."""
    if payload.get("stop_hook_active"):
        return None  # it already continued once for this check
    path = payload.get("transcript_path")
    if not isinstance(path, str):
        return None
    try:
        text, commands = _turn(Path(path))
    except (OSError, ValueError):
        return None
    if not _unhedged_claim(text) or any(ran_tests(c) for c in commands):
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


def _flag(argv: list, name: str) -> str | None:
    """The value after `name`, or None when the flag or its value is missing."""
    if name not in argv:
        return None
    at = argv.index(name) + 1
    return argv[at] if at < len(argv) else None


def main(argv=None, *, stdin=None, stdout=None) -> int:
    """Run the hook; it exits 0 whatever happens, so a guard bug never stops a session."""
    try:
        return _main(argv, stdin=stdin, stdout=stdout)
    except Exception:  # last resort: an unforeseen input must not block the user's work
        return 0


def _main(argv=None, *, stdin=None, stdout=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    tool = _flag(argv, "--tool") or "claude"
    data = Path(_flag(argv, "--data") or _default_data())
    if _flag(argv, "--event") == "stop":
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
    given = payload.get("tool_input")
    command = given.get("command") if isinstance(given, dict) else None
    if not isinstance(command, str) or not isinstance(rules, list):
        return 0
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    hit = evaluate(rules, command, cwd)
    if not hit:
        return 0
    rule_id = str(hit.get("id") or "unnamed")
    _log(data, {"tool": tool, "rule": rule_id, "cwd": cwd,
                "session": payload.get("session_id"), "command": command[:300]})  # fmt: skip
    message = hit.get("message") or "This command breaks a rule in the user's profile."
    reason = (
        f"{message} (blocked by the user's profile rule {rule_id}; "
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

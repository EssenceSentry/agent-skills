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
import subprocess
import sys
import time
from pathlib import Path


def rules_path(data: Path) -> Path:
    return Path(data) / "guard_rules.json"


def log_path(data: Path) -> Path:
    return Path(data) / "guard.jsonl"


def policy_path(data: Path) -> Path:
    """The limits main agents set for their subagents and workers (see ax.policy)."""
    return Path(data) / "subagent_limits.json"


def _limit(data: Path, session, command: str) -> dict | None:
    """The first limit for this conversation's subagents (or for all) the command breaks."""
    try:
        limits = json.loads(policy_path(data).read_text()).get("limits", [])
    except (OSError, ValueError, AttributeError):
        return None
    code = code_only(command)
    for limit in limits:
        if not isinstance(limit, dict) or not isinstance(limit.get("pattern"), str):
            continue
        if limit.get("session") and limit["session"] != session:
            continue
        try:
            if re.search(limit["pattern"], code, re.MULTILINE):
                return limit
        except re.error:
            continue
    return None


def probe_marker(data: Path) -> Path:
    """While this file exists, each call records who made it (not what it ran)."""
    return Path(data) / "guard-probe"


def probe_path(data: Path) -> Path:
    return Path(data) / "guard-probe.jsonl"


_WHO = ("session_id", "agent_id", "agent_type", "permission_mode", "hook_event_name",
        "tool_name", "model", "turn_id")  # fmt: skip


def _probe(data: Path, tool: str, payload: dict) -> None:
    if not probe_marker(data).exists():
        return
    record = {"tool": tool, "keys": sorted(payload)}
    record |= {k: payload[k] for k in _WHO if isinstance(payload.get(k), str | int | bool)}
    if isinstance(payload.get("transcript_path"), str):
        record["transcript"] = payload["transcript_path"]
    try:
        with probe_path(data).open("a") as out:
            out.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}) + "\n")
    except OSError:
        pass


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


# Friction without walls (PLAN component 19). The main agent, which has the whole
# conversation, pauses once before something it can't undo and goes on when it says why;
# a subagent or worker, with only part of the context, is stopped.

_SEG = r"[^;&|\n]*"  # within one command of a line
_GIT = r"\bgit(?:\s+-[Cc]\s+\S+)*\s+"
_DISPOSABLE = {"node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".ruff_cache",
               ".mypy_cache", ".venv", "venv", "checks", "coverage", ".next", ".turbo",
               ".cache", "target", ".parcel-cache"}  # fmt: skip
_TEMP = ("/tmp/", "/private/tmp/", "/var/folders/")
_SQL_CLIENT = re.compile(r"\b(?:psql|snowsql|sqlite3|mysql|duckdb|bq)\b")
_SQL_DROP = re.compile(r"(?i)\b(?:drop\s+(?:table|database|schema|view)|truncate\s+table)\b")
# (id, pattern over what runs, what it does, the check that can tell nothing would be lost)
_IRREVERSIBLE = [
    ("git-reset-hard", rf"{_GIT}reset\b{_SEG}--hard\b", "discards uncommitted changes", "tracked"),
    ("git-checkout-paths", rf"{_GIT}checkout\b(?:{_SEG}\s--(?:\s|$)|\s+\.(?:\s|$))",
     "discards uncommitted changes", "tracked"),
    ("git-restore", rf"{_GIT}restore\b{_SEG}", "discards uncommitted changes", "restore"),
    ("git-clean", rf"{_GIT}clean\b{_SEG}\s-[a-zA-Z]*f", "deletes untracked files", "untracked"),
    ("git-stash-drop", rf"{_GIT}stash\s+(?:drop|clear)\b", "deletes stashed work", None),
    ("git-branch-delete", rf"{_GIT}branch\b{_SEG}(?:\s-[a-zA-Z]*D\b|--delete\s+--force|--force\s+--delete)",
     "deletes a branch whether or not it was merged", None),
    ("git-force-push", rf"{_GIT}push\b{_SEG}(?:\s--force(?:-with-lease)?\b|\s-[a-zA-Z]*f\b|\s\+\S)",
     "overwrites history on the remote", None),
    ("git-remote-delete", rf"{_GIT}push\b{_SEG}(?:\s--delete\b|\s-d\b|\s:\S)",
     "deletes a branch or tag on the remote", None),
    ("git-worktree-force", rf"{_GIT}worktree\s+remove\b{_SEG}(?:--force\b|\s-f\b)",
     "removes a worktree with any uncommitted work in it", None),
    ("git-history", rf"{_GIT}(?:reflog\s+expire\b|gc\b{_SEG}--prune=now|filter-branch\b|filter-repo\b|update-ref\s+-d\b)",
     "rewrites or prunes history git keeps for recovery", None),
    ("rm-recursive", rf"(?:^|[\s;&|(])rm\s+{_SEG}", "deletes files and folders recursively", "rm"),
    ("find-delete", rf"\bfind\b{_SEG}\s-delete\b", "deletes every file find matches", None),
    ("cloud-delete", r"\baws\s+s3\s+(?:rm|rb)\b|\baws\s+[a-z0-9-]+\s+(?:delete|terminate|remove|deregister|purge)-[a-z0-9-]+"
     rf"|\baws\s+s3\s+sync\b{_SEG}--delete\b|\bgcloud\b{_SEG}\sdelete\b|\bkubectl\s+delete\b"
     rf"|\bterraform\s+(?:destroy\b|apply\b{_SEG}-destroy\b)",
     "deletes cloud resources or data", None),
    ("github-delete", rf"\bgh\s+(?:repo|release)\s+delete\b|\bgh\s+api\b{_SEG}(?:-X|--method)\s*DELETE\b",
     "deletes something on GitHub", None),
]  # fmt: skip
_INTENT = re.compile(r"""(?:^|[\s;&|(])AX_INTENT=(?:"([^"]*)"|'([^']*)'|([^\s;&|]+))""")
# `ax budget` pauses whoever would go over; a reason in front passes it, which only the
# main agent may give (see ax.budget).
_BUDGET_PASS = re.compile(r"\bax\s+budget\s+(?:add|check|reserve)\b")


def caller(payload: dict, tool: str) -> str:
    """main, subagent or worker. Claude marks a subagent's calls with agent_id; Codex says
    who started a session in the first line of its transcript."""
    if payload.get("agent_id"):
        return "subagent"
    path = payload.get("transcript_path")
    if tool == "codex" and isinstance(path, str):
        try:
            with open(path) as f:
                meta = json.loads(f.readline()).get("payload") or {}
        except (OSError, ValueError, AttributeError):
            return "main"
        source = meta.get("source") if isinstance(meta, dict) else None
        if isinstance(source, dict) and "subagent" in source:
            return "subagent"
        if source == "exec" or meta.get("originator") == "codex_exec":
            return "worker"
    return "main"


def intent(command: str) -> str | None:
    """The reason given as AX_INTENT="…" in front of the command, if any."""
    found = _INTENT.search(command)
    if not found or "AX_INTENT=" not in code_only(command):
        return None  # only inside a string or a heredoc: not given
    value = next(g for g in found.groups() if g is not None).strip()
    return value if len(value) >= 3 else None


def _git(cwd: str, segment: str, *args: str) -> list[str] | None:
    where = re.search(r"\bgit\s+-C\s+(\S+)", segment)
    folder = os.path.join(cwd, where.group(1)) if where else cwd
    try:
        done = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True,
                              timeout=2)  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.splitlines() if done.returncode == 0 else None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _rm_targets(segment: str) -> list[str]:
    words = segment.split()
    start = next((i for i, w in enumerate(words) if w == "rm"), None)
    return [] if start is None else words[start + 1 :]


def _loss(check: str | None, segment: str, cwd: str) -> str | None:
    """What would be lost, "" when it can't be told, None when nothing would be."""
    if check in ("tracked", "restore"):
        if (
            check == "restore"
            and "--staged" in segment
            and not re.search(r"--worktree|\s-W\b", segment)
        ):
            return None  # only unstages
        changed = _git(cwd, segment, "status", "--porcelain", "--untracked-files=no")
        if changed is None:
            return ""
        return _plural(len(changed), "uncommitted change") if changed else None
    if check == "untracked":
        flags = "".join(
            w[1:] for w in segment.split() if w.startswith("-") and not w.startswith("--")
        )
        extra = [f"-{c}" for c in "dxX" if c in flags]
        doomed = _git(cwd, segment, "clean", "-n", *extra)
        if doomed is None:
            return ""
        return _plural(len(doomed), "untracked file") if doomed else None
    if check == "rm":
        words = _rm_targets(segment)
        flags = [w for w in words if w.startswith("-")]
        if not any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*|--recursive", f) for f in flags):
            return None  # one file at a time is ordinary work
        targets = [w for w in words if not w.startswith("-")]

        def disposable(t: str) -> bool:
            path = os.path.expanduser(t).rstrip("/")
            return (os.path.isabs(path) and (path + "/").startswith(_TEMP)) or (
                os.path.basename(path) in _DISPOSABLE
            )

        if targets and all(disposable(t) for t in targets):
            return None
        return ", ".join(t for t in targets if not disposable(t))[:120] or ""
    return ""


def destructive(command: str, cwd: str) -> dict | None:
    """The first irreversible thing the command would do, with what would be lost; an
    action that would lose nothing (a reset on a clean tree) is not one."""
    code = code_only(command)
    sql = _SQL_CLIENT.search(code) and _SQL_DROP.search(command)
    if sql:
        return {"id": "sql-drop", "what": "drops a table or database", "detail": ""}
    for line in code.splitlines():
        for segment in re.split(r"&&|\|\||;|\|", line):
            for rule_id, pattern, what, check in _IRREVERSIBLE:
                if not re.search(pattern, segment):
                    continue
                lost = _loss(check, segment, cwd)
                if lost is None:
                    continue
                return {"id": rule_id, "what": what, "detail": lost}
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


_AX_JOB = re.compile(r"^\s*(?:\S+=\S*\s+)*(?:\S*/)?ax\s+job\b")

BACKGROUND = (
    "Pause: background work goes through ax, so it stays visible and wakes you when it "
    "ends or stops working. Start it as `ax job run --key KEY --expect 15m --label "
    '"what it does; what you\'ll do next" -- CMD`. Check it started correctly (`ax job '
    "wait KEY --timeout 60`, then its first output) before running `ax job wait KEY` in "
    "the background; jobs expected to take over 10 minutes get a Haiku look every 5 minutes. "
    'If this is not job-like work, run it again with AX_INTENT="<why>" in front.'
)


def background_nudge(given: dict) -> str | None:
    """The pause for a background Bash command that bypasses `ax job`, if this is one."""
    if not given.get("run_in_background"):
        return None
    command = given.get("command")
    if not isinstance(command, str) or _AX_JOB.search(code_only(command)):
        return None
    return BACKGROUND


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
    except ValueError:
        return 0
    if isinstance(payload, dict):
        _probe(data, tool, payload)
        given = payload.get("tool_input")
        nudge = (
            background_nudge(given)
            if payload.get("tool_name") == "Bash" and isinstance(given, dict)
            else None
        )
        if nudge:
            entry = {"tool": tool, "cwd": payload.get("cwd"), "session": payload.get("session_id"),
                     "command": str(given.get("command"))[:300], "rule": "background-via-ax"}  # fmt: skip
            if intent(str(given.get("command"))):
                _log(data, {**entry, "kind": "pass", "intent": intent(str(given.get("command")))})
                return 0
            _log(data, {**entry, "kind": "pause"})
            stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": nudge}}) + "\n")  # fmt: skip
            return 0
    try:
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
    entry = {"tool": tool, "cwd": cwd, "session": payload.get("session_id"),
             "command": command[:300]}  # fmt: skip
    try:
        who = caller(payload, tool)
        hit = evaluate(rules, command, cwd)
        found = None if hit else destructive(command, cwd)
        limit = None
        if not hit and not found and who != "main":
            limit = _limit(data, payload.get("session_id"), command)
            if not limit and intent(command) and _BUDGET_PASS.search(code_only(command)):
                found = {"id": "budget-over", "what": "goes past a budget's limit", "detail": ""}
    except Exception as exc:  # fail open: a guard bug never stops the work, but it says so
        _log(data, {**entry, "kind": "error", "error": f"{type(exc).__name__}: {exc}"})
        return 0
    if not hit and not found and not limit:
        return 0
    rule_id = str(hit.get("id") or "unnamed") if hit else (found or limit)["id"]
    if limit:
        what = (
            f"{limit['why'].rstrip('.')} (limit {limit['id']}, set by the agent that started you)"
        )
    elif hit:
        what = hit.get("message") or "This command breaks a rule in the user's profile."
        what = f"{what.rstrip('.')} (your profile rule {rule_id})"
    else:
        detail = f": {found['detail']}" if found["detail"] else ""
        what = f"this {found['what']}{detail}"
    entry |= {"rule": rule_id, "caller": who}
    reason_given = intent(command) if who == "main" else None
    if reason_given:
        _log(data, {**entry, "kind": "pass", "intent": reason_given})
        return 0
    if who == "main":
        _log(data, {**entry, "kind": "pause"})
        preview = command if len(command) <= 120 else command[:117] + "..."
        reason = (f"Pause: {what}. If you mean it, run the same command again with your reason "
                  f'in front: AX_INTENT="<why>" {preview}')  # fmt: skip
    else:
        _log(data, {**entry, "kind": "stop"})
        reason = (f"Stopped: {what}. An agent started by another agent doesn't do this; say "
                  "what you needed in your report to the agent that started you, which can "
                  "run it.")  # fmt: skip
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

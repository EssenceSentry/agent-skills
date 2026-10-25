"""Wire ax into Claude Code, Codex and macOS: hooks, a schedule and skill links.

Every function here plans first and changes nothing; `apply` and
`apply_links` perform a plan. Files are merged, never replaced, and a file
that existed is backed up before it is rewritten.
"""

import json
import os
import plistlib
import shlex
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ax.config import Config

LABEL = "com.ax.sync"
JOBS_LABEL = "com.ax.jobs"
APP_LABEL = "com.ax.app"
_EVENTS = ("SessionEnd", "Stop")
# Codex gives SessionEnd hooks at most 3 seconds; ours only starts a background sync.
_TIMEOUT = {"claude": 5, "codex": 3}


@dataclass
class Change:
    path: Path
    before: str | None  # None: the file doesn't exist yet
    after: str


@dataclass
class LinkAction:
    name: str
    tool: str  # "claude" or "codex"
    target: Path  # where the link goes
    source: Path  # the skill in this repository
    kind: str  # "link", "linked" (already done) or "conflict"
    reason: str = ""


def hook_command(config: Config, ax: str) -> str:
    """Start a quiet background sync and return at once; hooks must not block a session."""
    log = config.data / "hook.log"
    inner = f"{shlex.quote(ax)} sync --quiet >> {shlex.quote(str(log))} 2>&1 &"
    return f"/bin/sh -c {shlex.quote(inner)}"


def _add_sync(settings: dict, command: str, tool: str) -> None:
    hooks = settings.setdefault("hooks", {})
    for event in _EVENTS:
        groups = hooks.setdefault(event, [])
        present = any(h.get("command") == command for g in groups for h in g.get("hooks", []))
        if not present:
            handler = {"type": "command", "command": command, "timeout": _TIMEOUT[tool]}
            groups.append({"hooks": [handler]})


def _add_start(settings: dict, ax: str, tool: str) -> None:
    """The SessionStart hook that hands a new conversation the digest of recent work."""
    groups = settings.setdefault("hooks", {}).setdefault("SessionStart", [])
    command = f"{shlex.quote(ax)} hooks start --tool {tool}"
    if not any(h.get("command") == command for g in groups for h in g.get("hooks", [])):
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})


def _add_guard(settings: dict, guard: str, tool: str) -> None:
    groups = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    command = f"{shlex.quote(guard)} --tool {tool}"
    present = any(h.get("command") == command for g in groups for h in g.get("hooks", []))
    if not present:
        groups.append(
            {"matcher": "Bash", "hooks": [{"type": "command", "command": command, "timeout": 5}]}
        )
    if tool == "claude":
        # The stop check reads Claude's transcript; Codex's has another format.
        stops = settings["hooks"].setdefault("Stop", [])
        check = f"{command} --event stop"
        if not any(h.get("command") == check for g in stops for h in g.get("hooks", [])):
            stops.append({"hooks": [{"type": "command", "command": check, "timeout": 5}]})


def _plan(config: Config, edit) -> list[Change]:
    targets = {
        "claude": config.claude_home / "settings.json",
        "codex": config.codex_home / "hooks.json",
    }
    changes = []
    for tool, path in targets.items():
        before = path.read_text() if path.exists() else None
        settings = json.loads(before) if before else {}
        edit(settings, tool)
        changes.append(Change(path, before, json.dumps(settings, indent=2) + "\n"))
    return changes


def plan_hooks(config: Config, *, ax: str, guard: str | None = None) -> list[Change]:
    """Sync hooks at session end and turn stop, the recent-work digest at session start;
    with `guard`, the shell-command guard too."""
    command = hook_command(config, ax)

    def edit(settings, tool):
        _add_sync(settings, command, tool)
        _add_start(settings, ax, tool)
        if guard:
            _add_guard(settings, guard, tool)

    return _plan(config, edit)


def plan_guard_hooks(config: Config, *, guard: str) -> list[Change]:
    """Run `ax-guard` before every shell command in both tools, and as Claude's stop check."""
    return _plan(config, lambda settings, tool: _add_guard(settings, guard, tool))


def guard_path() -> str:
    found = shutil.which("ax-guard")
    if found:
        return found
    sibling = Path(ax_path()).with_name("ax-guard")
    return str(sibling) if sibling.exists() else "ax-guard"


def plan_schedule(
    config: Config, *, ax: str, launch_agents: Path, with_vault: bool = False
) -> list[Change]:
    steps = [
        f"{shlex.quote(ax)} sync --quiet",
        f"{shlex.quote(ax)} usage --cached --json > /dev/null",
    ]
    if with_vault:
        steps.append(f"{shlex.quote(ax)} vault commit && {shlex.quote(ax)} vault push")
    log = str(config.data / "schedule.log")
    plist = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/sh", "-c", "; ".join(steps)],
        "StartInterval": 1800,
        # launchd starts jobs with /usr/bin:/bin only; gitleaks, gh and ax live elsewhere.
        "EnvironmentVariables": {"PATH": _launchd_path()},
        "RunAtLoad": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    path = launch_agents / f"{LABEL}.plist"
    before = path.read_text() if path.exists() else None
    return [Change(path, before, plistlib.dumps(plist).decode())]


def plan_jobs_service(config: Config, *, ax: str, launch_agents: Path) -> list[Change]:
    """A launchd agent that refreshes unfollowed jobs and restarts dead followers each minute."""
    log = str(config.data / "jobs-service.log")
    plist = {
        "Label": JOBS_LABEL,
        "ProgramArguments": [ax, "job", "poll", "--background", "--quiet"],
        "StartInterval": 60,
        "EnvironmentVariables": {"PATH": _launchd_path()},
        "RunAtLoad": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    path = launch_agents / f"{JOBS_LABEL}.plist"
    before = path.read_text() if path.exists() else None
    return [Change(path, before, plistlib.dumps(plist).decode())]


def plan_app_service(
    config: Config, *, ax: str, launch_agents: Path, port: int, share: str = "none",
    notify: bool = False,
) -> list[Change]:  # fmt: skip
    """A launchd agent that keeps `ax serve` running from login, restarted whenever it stops;
    with `share` and `notify`, it also keeps a Cloudflare link and sends each new one."""
    log = str(config.data / "app" / "serve.log")
    plist = {
        "Label": APP_LABEL,
        "ProgramArguments": [
            ax,
            "serve",
            "--port",
            str(port),
            *(["--share", share] if share != "none" else []),
            *(["--notify"] if notify else []),
        ],  # fmt: skip
        "KeepAlive": True,
        "RunAtLoad": True,
        "EnvironmentVariables": {"PATH": _launchd_path()},
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    path = launch_agents / f"{APP_LABEL}.plist"
    before = path.read_text() if path.exists() else None
    return [Change(path, before, plistlib.dumps(plist).decode())]


def _launchd_path() -> str:
    dirs = [Path.home() / ".local/bin", "/opt/homebrew/bin", "/usr/local/bin"]
    return ":".join([*map(str, dirs), "/usr/bin", "/bin", "/usr/sbin", "/sbin"])


def plan_mcp(config: Config, *, ax: str) -> tuple[list[Change], list[list[str]]]:
    """Register `ax mcp` with both tools: a block in Codex's config.toml, and the command
    that adds it to Claude Code's user scope (Claude rewrites its own config file)."""
    path = config.codex_home / "config.toml"
    before = path.read_text() if path.exists() else None
    block = f'[mcp_servers.ax]\ncommand = {json.dumps(ax)}\nargs = ["mcp"]\n'
    text = before or ""
    if "[mcp_servers.ax]" not in text:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block
    claude = ["claude", "mcp", "add", "--scope", "user", "ax", "--", ax, "mcp"]
    return [Change(path, before, text)], [claude]


def apply(changes: list[Change]) -> list[Path]:
    """Write every changed file, backing up the ones that already existed."""
    written = []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for change in changes:
        if change.before == change.after:
            continue
        change.path.parent.mkdir(parents=True, exist_ok=True)
        if change.before is not None:
            backup = change.path.with_name(f"{change.path.name}.ax-backup-{stamp}")
            backup.write_text(change.before)
        change.path.write_text(change.after)
        written.append(change.path)
    return written


def plan_skill_links(
    config: Config, *, names: list[str], repo_skills: Path, agents_skills: Path
) -> list[LinkAction]:
    """Link each named skill for both tools where nothing of that name is installed."""
    roots = {"claude": config.claude_home / "skills", "codex": agents_skills}
    legacy = config.codex_home / "skills"
    actions = []
    for name in names:
        source = repo_skills / name
        for tool, root in roots.items():
            target = root / name
            action = LinkAction(name, tool, target, source, "link")
            if target.is_symlink() and target.resolve() == source.resolve():
                action.kind = "linked"
            elif target.exists() or target.is_symlink():
                action.kind, action.reason = "conflict", f"{target} already exists"
            elif tool == "codex" and (legacy / name).exists():
                action.kind = "conflict"
                action.reason = f"{legacy / name} exists; Codex would list {name} twice"
            actions.append(action)
    return actions


def apply_links(actions: list[LinkAction]) -> list[Path]:
    made = []
    for action in actions:
        if action.kind == "link":
            action.target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(action.source.resolve(), action.target)
            made.append(action.target)
    return made


def ax_path() -> str:
    return shutil.which("ax") or "ax"


def repo_skills() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def agents_skills_dir() -> Path:
    """Where Codex reads user skills; `~/.codex/skills` is its deprecated location."""
    return Path.home() / ".agents" / "skills"

"""What a session's / menu offers: its tool's own commands and skills.

Each tool is asked in the session's folder, so project skills show too, without a model
call: Claude through its start-up handshake, run with the user's and the project's
settings but no hooks; Codex through its app server's `skills/list`. A folder is asked at
most every ten minutes.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

TTL = 600  # seconds what a folder offers is reused
_SCOPES = {"user": "Personal", "repo": "Project", "system": "System", "admin": "Admin"}
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
BUILTINS = [
    {
        "name": name,
        "title": f"/{name}",
        "description": description,
        "hint": "",
        "insert": f"/{name}",
        "scope": "ax",
        "action": name,
    }
    for name, description in (
        ("compact", "Compact conversation context"),
        ("review", "Review uncommitted workspace changes"),
        ("fork", "Fork this conversation"),
        ("archive", "Archive this conversation"),
    )
]


def claude_command() -> list[str]:
    """Claude, asked only for what it offers: with the user's and the project's settings,
    so their skills and plugins show, but with every hook off and no session kept."""
    return [shutil.which("claude") or "claude", "-p", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--settings", json.dumps({"disableAllHooks": True})]  # fmt: skip


def claude_items(found: list) -> list[dict]:
    """Claude's commands, its skills among them, each typed after a slash."""
    return [
        {"name": c["name"], "title": c["name"], "description": c.get("description") or "",
         "hint": c.get("argumentHint") or "", "insert": f"/{c['name']} ", "scope": None}
        for c in found
        if isinstance(c, dict) and c.get("name") and not str(c["name"]).startswith("__")
    ]  # fmt: skip


def codex_items(listed: dict) -> list[dict]:
    """Codex's skills for the folder, each mentioned with a dollar sign."""
    entries = listed.get("data") or [] if isinstance(listed, dict) else []
    found = []
    for skill in (entries[0].get("skills") or []) if entries else []:
        face = skill.get("interface") or {}
        found.append({
            "name": skill["name"], "title": face.get("displayName") or skill["name"],
            "description": face.get("shortDescription") or skill.get("description") or "",
            "hint": "", "insert": f"${skill['name']} ", "scope": _SCOPES.get(skill.get("scope")),
            **({"path": skill["path"]} if skill.get("path") else {}),
            "enabled": skill.get("enabled", True),
        })  # fmt: skip
    return found


def _ask_claude(config, folder: str) -> list:
    from ax import chat

    return chat._claude_offers(config, claude_command(), cwd=folder).get("commands") or []


def _ask_codex(config, folder: str) -> dict:
    from ax import live_sessions

    server = live_sessions.AppServer(live_sessions.codex_command(config)).start()
    try:
        return server.request("skills/list", {"cwds": [folder]}) or {}
    finally:
        server.close()


def offered(config, provider: str, cwd: str | None, *, ask_claude=None, ask_codex=None,
            now: float | None = None) -> dict:  # fmt: skip
    """What the / menu lists for a session of `provider` working in `cwd`: Claude's
    commands (its skills among them) or Codex's skills; empty, with the reason, when the
    tool can't answer."""
    if provider not in ("claude", "codex"):
        raise ValueError(f"unknown provider {provider!r}")
    folder = cwd if cwd and Path(cwd).is_dir() else str(config.data)
    now = time.monotonic() if now is None else now
    kept = _cache.get((provider, folder))
    if kept and now - kept[0] < TTL:
        return kept[1]
    try:
        if provider == "claude":
            found = {"commands": claude_items((ask_claude or _ask_claude)(config, folder)),
                     "skills": []}  # fmt: skip
        else:
            found = {
                "commands": BUILTINS,
                "skills": codex_items((ask_codex or _ask_codex)(config, folder)),
            }
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"commands": [], "skills": [], "error": f"{provider}: {exc}"}
    _cache[(provider, folder)] = (now, found)
    return found

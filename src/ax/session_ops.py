"""User-initiated session operations. Disk helpers never run a model."""

import json
import os
import subprocess
import sys

from ax import chat_store, live_sessions

OPERATIONS = {
    "rename",
    "archive",
    "unarchive",
    "pin",
    "group",
    "order",
    "fork",
    "compact",
    "review",
    "capability",
    "restore-preview",
    "restore-apply",
}


def _claude(config, operation, **arguments):
    script = """import dataclasses,json,sys
import claude_agent_sdk as sdk
given=json.load(sys.stdin)
result=getattr(sdk,given['operation'])(**given['arguments'])
print(json.dumps(dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps({"operation": operation, "arguments": arguments}),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_CONFIG_DIR": str(config.claude_home)},
        timeout=30,
    )
    if result.returncode:
        raise ValueError(
            result.stderr.strip().splitlines()[-1]
            if result.stderr.strip()
            else "Claude session operation failed"
        )
    return json.loads(result.stdout)


def _codex(config, sid, method, params):
    from ax.chat import CHATS

    driver = CHATS.get("codex", sid)
    if driver:
        return driver.call(method, params)
    server = live_sessions.AppServer(live_sessions.codex_command(config)).start()
    try:
        return server.request(method, params)
    finally:
        server.close()


def act(config, payload):
    from ax import chat

    provider, sid, action = payload["provider"], payload["id"], payload["action"]
    driver = chat.CHATS.get(provider, sid)
    if action == "capability":
        operation = payload.get("operation")
        if operation == "refresh-mcp" and provider == "codex":
            _codex(config, sid, "config/mcpServer/reload", {})
        elif operation == "skill-enabled" and provider == "codex":
            _codex(
                config,
                sid,
                "skills/config/write",
                {"path": payload.get("path"), "enabled": bool(payload.get("enabled"))},
            )
        elif operation == "mcp-login" and provider == "codex":
            result = _codex(
                config,
                sid,
                "mcpServer/oauth/login",
                {"name": str(payload.get("server_name")), "threadId": sid},
            )
            return {"ok": True, **result, "message": "Open the authorization link to sign in."}
        elif operation == "plugin-enabled" and provider == "claude":
            name = str(payload.get("plugin") or "")
            if not name or name.startswith("-"):
                raise ValueError("Choose an installed plugin")
            result = subprocess.run(
                ["claude", "plugin", "enable" if payload.get("enabled") else "disable", name],
                capture_output=True,
                text=True,
                env={**os.environ, "CLAUDE_CONFIG_DIR": str(config.claude_home)},
                timeout=30,
            )
            if result.returncode:
                raise ValueError(result.stderr.strip() or "Plugin configuration was rejected")
        else:
            raise ValueError("This provider exposes that operation through its native app or CLI")
        from ax import commands

        commands._cache.pop((provider, payload.get("cwd") or str(config.data)), None)
        return {
            "ok": True,
            "message": "Configuration updated. Existing sessions may need a reload to use it.",
        }
    if action.startswith("restore-"):
        from ax import session_restore

        if action == "restore-preview":
            return session_restore.preview(config, provider, sid, payload.get("target"))
        external = (
            chat.claude_open_elsewhere(config, sid)
            if provider == "claude"
            else chat.codex_open_in_app(config, sid)
        )
        if (driver and driver.busy) or (driver is None and external is not False):
            raise ValueError(
                "Finish the active turn and close other writers before restoring files"
            )
        return session_restore.apply(
            config, provider, sid, payload.get("token"), payload.get("paths") or []
        )
    if action in ("archive", "fork") and driver and driver.busy:
        raise ValueError("Wait for this turn to finish before changing its history")
    if action in ("pin", "group", "order"):
        values = {
            "pin": ("pinned", bool(payload.get("pinned"))),
            "group": ("group", str(payload.get("group") or "")),
            "order": ("order", int(payload.get("order") or 0)),
        }
        field, value = values[action]
        meta = chat_store.metadata(config, provider, sid, {field: value})
        live_sessions.clear_cache()
        return {"ok": True, "metadata": meta, "message": "Updated."}
    if action == "rename":
        title = str(payload.get("name") or "").strip()
        if not title:
            raise ValueError("Give the session a name")
        if provider == "codex":
            _codex(config, sid, "thread/name/set", {"threadId": sid, "name": title})
        else:
            _claude(
                config, "rename_session", session_id=sid, title=title, directory=payload.get("cwd")
            )
        chat_store.metadata(config, provider, sid, {"name": title})
        if driver:
            driver.name = title
    elif action in ("archive", "unarchive"):
        archived = action == "archive"
        if provider == "codex":
            _codex(config, sid, f"thread/{action}", {"threadId": sid})
        else:
            _claude(
                config,
                "tag_session",
                session_id=sid,
                tag="__hidden" if archived else None,
                directory=payload.get("cwd"),
            )
        chat_store.metadata(
            config,
            provider,
            sid,
            {
                "archived": archived,
                "cwd": payload.get("cwd"),
                "name": payload.get("name") or (driver.name if driver else sid[:8]),
            },
        )
        if archived:
            chat.CHATS.release(provider, sid)
    elif action == "fork":
        if provider == "codex":
            params = {"threadId": sid}
            if payload.get("turn_id"):
                params["lastTurnId"] = payload["turn_id"]
            result = _codex(config, sid, "thread/fork", params)
            new_id = result["thread"]["id"]
        else:
            result = _claude(
                config,
                "fork_session",
                session_id=sid,
                directory=payload.get("cwd"),
                up_to_message_id=payload.get("message_id"),
                title=payload.get("name"),
            )
            new_id = result["session_id"]
        return {
            "ok": True,
            "provider": provider,
            "id": new_id,
            "message": "Forked; the original is preserved.",
        }
    elif action in ("compact", "review"):
        if provider == "codex":
            current = chat._hold(config, provider, sid, payload.get("cwd"), payload.get("name"))
            if current.busy:
                raise ValueError("Queue this command after the active turn finishes")
            method = "thread/compact/start" if action == "compact" else "review/start"
            params = {"threadId": sid}
            if action == "review":
                params.update(target={"type": "uncommittedChanges"}, delivery="inline")
            current.call(method, params)
        else:
            return chat._send(
                config,
                provider,
                sid,
                "/compact"
                if action == "compact"
                else "Review the current uncommitted changes. Report actionable findings with file and line references; do not modify files.",
                payload.get("cwd"),
                payload.get("name"),
                delivery="queue",
            )
    else:
        raise ValueError("Unsupported session operation")
    live_sessions.clear_cache()
    return {"ok": True, "message": "Updated."}


def catalog(config, provider, sid=None, cwd=None):
    """Only documented status APIs; unstable plugin RPCs are deliberately excluded."""
    from ax import commands

    found = {
        "skills": commands.offered(config, provider, cwd),
        "mcp": None,
        "apps": None,
        "plugins": [],
        "handoff": "Manage provider-exclusive catalogs in the native app or CLI.",
    }
    if provider == "codex":
        errors = []
        for key, method in (("mcp", "mcpServerStatus/list"), ("apps", "app/list")):
            try:
                params = {"threadId": sid} if sid else {}
                found[key] = _codex(config, sid, method, params)
            except (ValueError, RuntimeError) as exc:
                errors.append(str(exc))
        found["errors"] = errors
        root = config.codex_home / "plugins" / "cache"
    else:
        root = config.claude_home / "plugins" / "cache"
        run = subprocess.run(
            ["claude", "mcp", "list"],
            cwd=cwd,
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_CONFIG_DIR": str(config.claude_home)},
            timeout=30,
        )
        found["mcp"] = {"text": run.stdout, "error": run.stderr if run.returncode else None}
    if root.is_dir():
        found["plugins"] = sorted({p.name for p in root.glob("*/*") if p.is_dir()})
    if provider == "claude":
        settings = config.claude_home / "settings.json"
        installed = config.claude_home / "plugins" / "installed_plugins.json"
        try:
            enabled = (
                json.loads(settings.read_text()).get("enabledPlugins", {})
                if settings.exists()
                else {}
            )
            names = (
                json.loads(installed.read_text()).get("plugins", {}) if installed.exists() else {}
            )
            found["plugins"] = [
                {"name": name, "enabled": enabled.get(name, True)} for name in names
            ]
        except (OSError, ValueError):
            found["errors"] = ["Installed plugin metadata could not be read"]
    return found

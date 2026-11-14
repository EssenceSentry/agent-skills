"""Add missing Claude Desktop registrations for shared local transcripts.

Desktop reads its registry on launch. Never open clients, resume models, modify
transcripts, or overwrite records the client owns. VS Code already reads the
same transcript files. Codex already shares its native thread store.
"""

import json
import math
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ax import catalog

LOCK = threading.Lock()
INTERACTIVE = {"cli", "claude-vscode"}
CACHE = {}


def uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def read_json(path):
    if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f"unsafe or oversized registration file: {path.name}")
    return json.loads(path.read_text())


def registry(config):
    root = config.claude_desktop
    if root is None or not root.is_dir() or not config.claude_json.exists():
        return None, "desktop_or_identity_unavailable"
    identity_file = read_json(config.claude_json)
    if not isinstance(identity_file, dict) or not isinstance(
        identity_file.get("oauthAccount", {}), dict
    ):
        raise ValueError("invalid Claude identity file")
    identity = identity_file.get("oauthAccount", {})
    account, org = identity.get("accountUuid"), identity.get("organizationUuid")
    if not uuid(account) or not uuid(org):
        return None, "desktop_or_identity_unavailable"
    desktop_identity = root / "config.json"
    if not desktop_identity.exists():
        return None, "desktop_identity_unavailable"
    desktop_account = read_json(desktop_identity)
    if not isinstance(desktop_account, dict):
        raise ValueError("invalid Desktop identity file")
    if desktop_account.get("lastKnownAccountUuid") != account:
        return None, "account_mismatch"
    account_dir = root / "claude-code-sessions" / account
    if not account_dir.is_dir():
        return None, "desktop_registry_unavailable"
    orgs = [p for p in account_dir.iterdir() if p.is_dir() and uuid(p.name)]
    if len(orgs) != 1 or orgs[0].name != org:
        return None, "organization_ambiguous_or_mismatched"
    folder = orgs[0]
    if any(p.is_symlink() for p in (account_dir.parent, account_dir, folder)):
        raise ValueError("Desktop registry must not contain directory symlinks")
    return folder, None


def known_ids(folder):
    known = set()
    for path in folder.glob("local_*.json"):
        record = read_json(path)
        if not isinstance(record, dict):
            raise ValueError(f"invalid Desktop registration: {path.name}")
        values = [path.stem.removeprefix("local_")]
        values.extend(
            record.get(k)
            for k in ("cliSessionId", "unarchivedCliSessionId", "preClearCliSessionId")
        )
        previous = record.get("previousCliSessionIds", [])
        if not isinstance(previous, list):
            raise ValueError(f"unsupported Desktop registration: {path.name}")
        known.update(value for value in [*values, *previous] if uuid(value))
    for path in folder.glob("deleted_*"):
        value = path.name.removeprefix("deleted_")
        if uuid(value):
            known.add(value)
    index = folder / "archived-sessions.idx"
    if index.exists():
        data = read_json(index)
        if (
            not isinstance(data, dict)
            or data.get("v") != 1
            or not isinstance(data.get("archived"), list)
        ):
            raise ValueError("unsupported Desktop archive index; registration sync withheld")
        for value in data["archived"]:
            if not isinstance(value, str):
                raise ValueError("unsupported Desktop archive entry")
            value = value.removeprefix("local_").removesuffix(".json")
            if not uuid(value):
                raise ValueError("unsupported Desktop archive identity")
            known.add(value)
    return known


def transcript_record(path, now):
    """Stream metadata without retaining or copying conversation content."""
    if not uuid(path.stem) or path.is_symlink() or path.parent.is_symlink():
        return None
    entry = path.stat()
    if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1 or now - entry.st_mtime < 5:
        return None
    fingerprint = (entry.st_ino, entry.st_size, entry.st_mtime_ns)
    cached = CACHE.get(str(path))
    if cached is not None and cached[0] == fingerprint:
        return cached[1] if Path(cached[1]["cwd"]).is_dir() else None
    record = scan_transcript(path, fingerprint)
    if record is not None:
        CACHE[str(path)] = (fingerprint, record)
    return record


def scan_transcript(path, fingerprint):
    first_user, model, assistant, cwd = None, None, False, None
    titles = {}
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return None
        for line in source:
            try:
                r = json.loads(line)
            except (ValueError, UnicodeError):
                return None
            if not isinstance(r, dict):
                return None
            if r.get("sessionId") != path.stem or r.get("isSidechain") or r.get("isMeta"):
                continue
            kind = r.get("type")
            if kind == "user" and first_user is None:
                if r.get("entrypoint") not in INTERACTIVE or r.get("sessionKind") not in (
                    None,
                    "interactive",
                ):
                    return None
                if r.get("isSynthetic") or r.get("isCompactSummary"):
                    continue
                message = r.get("message", {})
                if not isinstance(message, dict):
                    return None
                content = message.get("content")
                if isinstance(content, list):
                    content = next(
                        (
                            item.get("text")
                            for item in content
                            if isinstance(item, dict) and item.get("type") == "text"
                        ),
                        "Claude conversation",
                    )
                first_user = {
                    "timestamp": r.get("timestamp"),
                    "title": content[:120] if isinstance(content, str) else "Claude conversation",
                }
            if kind in ("user", "assistant"):
                candidate = r.get("cwd")
                if (
                    isinstance(candidate, str)
                    and re.sub(r"[^A-Za-z0-9]", "-", candidate) == path.parent.name
                ):
                    cwd = candidate
            if kind == "assistant":
                message = r.get("message", {})
                if isinstance(message, dict) and message.get("role") == "assistant":
                    assistant = True
                    value = message.get("model")
                    if isinstance(value, str) and value:
                        model = value
            if kind in ("custom-title", "ai-title"):
                value = r.get("customTitle") if kind == "custom-title" else r.get("aiTitle")
                if isinstance(value, str) and value.strip():
                    titles[kind] = value[:120]
        after = os.fstat(source.fileno())
    current = path.stat(follow_symlinks=False)
    if any((s.st_ino, s.st_size, s.st_mtime_ns) != fingerprint for s in (before, after, current)):
        return None
    if (
        first_user is None
        or not assistant
        or cwd is None
        or not Path(cwd).is_absolute()
        or not Path(cwd).is_dir()
    ):
        return None
    title = titles.get("custom-title") or titles.get("ai-title") or first_user["title"]
    title = title.strip().splitlines()[0][:120] if title.strip() else "Claude conversation"
    created = before.st_mtime
    try:
        parsed = datetime.fromisoformat(first_user["timestamp"].replace("Z", "+00:00")).timestamp()
        if math.isfinite(parsed):
            created = parsed
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass
    return {
        "sessionId": "local_" + path.stem,
        "cliSessionId": path.stem,
        "cwd": cwd,
        "originCwd": cwd,
        "createdAt": int(created * 1000),
        "lastActivityAt": int(before.st_mtime * 1000),
        "lastFocusedAt": 0,
        "isArchived": False,
        "title": title,
        "titleSource": "user",
        "model": model,
        "permissionMode": "default",
        "remoteMcpServersConfig": [],
        "alwaysAllowedReasons": [],
        "sessionPermissionUpdates": [],
        "adoptedFromOtherSurface": True,
        "fromCliTranscript": True,
    }


def create_record(folder, record):
    """Publish a complete private file without replacing a concurrent client write."""
    descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".ax-register-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w") as out:
            json.dump(record, out, ensure_ascii=False, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, folder / (record["sessionId"] + ".json"))
            return True
        except FileExistsError:
            return False
    finally:
        Path(temporary).unlink(missing_ok=True)


def desktop_running():
    result = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-x", "Claude"],
        capture_output=True,
        timeout=3,
    )
    if result.returncode not in (0, 1):
        raise ValueError("cannot verify Desktop has exited; registration sync withheld")
    return result.returncode == 0


def sync(config):
    with LOCK:
        report = {
            "available": False,
            "created": 0,
            "known": 0,
            "skipped": 0,
            "errors": [],
            "checked_at": time.time(),
        }
        try:
            folder, reason = registry(config)
            if folder is None:
                report["reason"] = reason
                return report
            known = known_ids(folder)
            key = "desktop_registrations:" + str(folder)
            with catalog.connect(config) as db:
                previous = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            seen_values = json.loads(previous["value"]) if previous else []
            if not isinstance(seen_values, list) or not all(uuid(value) for value in seen_values):
                raise ValueError("invalid ax registration inventory")
            seen = set(seen_values)
            known.update(seen)
            report.update(available=True, known=len(known), desktop_refresh="next_launch")
            projects = config.claude_home / "projects"
            if projects.is_symlink():
                raise ValueError("Claude transcript root must not be a symlink")
            files = {}
            for path in projects.glob("*/*.jsonl"):
                files.setdefault(path.stem, []).append(path)
            live_paths = {str(path) for paths in files.values() for path in paths}
            for path in list(CACHE):
                if path not in live_paths:
                    del CACHE[path]
            candidates = []
            for sid, paths in files.items():
                if sid in known:
                    continue
                if len(paths) > 1:
                    report["errors"].append(
                        {
                            "id": sid,
                            "error": "multiple transcripts share this ID; registration withheld",
                        }
                    )
                    continue
                path = paths[0]
                try:
                    record = transcript_record(path, report["checked_at"])
                    if record is None:
                        report["skipped"] += 1
                        continue
                    candidates.append(record)
                except (OSError, ValueError) as exc:
                    report["errors"].append({"path": str(path), "error": str(exc)})
            report["pending"] = len(candidates)
            if candidates and desktop_running():
                report["reason"] = "waiting_for_desktop_exit"
            else:
                for record in candidates:
                    sid = record["cliSessionId"]
                    if (folder / ("deleted_" + sid)).exists():
                        known.add(sid)
                        report["pending"] -= 1
                        continue
                    try:
                        report["created"] += int(create_record(folder, record))
                        known.add(sid)
                        report["pending"] -= 1
                    except OSError as exc:
                        report["errors"].append({"id": sid, "error": str(exc)})
            with catalog.connect(config) as db:
                db.execute(
                    "INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, json.dumps(sorted(known)))
                )
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
            report["errors"].append(str(exc))
        return report

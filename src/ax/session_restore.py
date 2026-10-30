"""Preview and apply inverse changes from provider history, with revision checks."""

import difflib
import hashlib
import os
import secrets
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

from ax import live_sessions
from ax import session_changes as history
from ax.sources.common import iter_records

_plans: dict[str, dict] = {}
_lock = threading.Lock()


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest() if text is not None else "absent"


def preview(config, provider, sid, target=None):
    found = history._read(config, provider, sid)
    path = live_sessions.transcript_path(config, provider, sid)
    records = list(iter_records(path, Counter()))
    if target:
        index = next(
            (
                i
                for i, r in enumerate(records)
                if r.get("uuid") == target
                or (
                    (r.get("payload") or {}).get("type") == "task_started"
                    and (
                        (r.get("payload") or {}).get("turn_id")
                        or (r.get("payload") or {}).get("turnId")
                    )
                    == target
                )
            ),
            None,
        )
        if index is None:
            raise ValueError("This point has no provider checkpoint")
        found.start = index
        if provider == "claude":
            found.prompt = target
    files, skipped = [], []
    codex_texts, codex_errors, dependencies = (
        history._codex_tree(found) if provider == "codex" else ({}, {}, {})
    )
    for name in history._unique(p for i, p in found.edits if i > found.start):
        file = Path(name)
        try:
            if file.is_symlink() or (
                file.exists() and (not file.is_file() or file.stat().st_nlink != 1)
            ):
                raise ValueError("links and nonregular files cannot be restored")
            current = history._on_disk(name)
            if provider == "codex":
                if name in codex_errors:
                    raise ValueError(codex_errors[name])
                restored = codex_texts.get(name, current)
            else:
                before = history._claude_turn(config, sid, found, name)
                expected = before or ""
                for r in records[found.start + 1 :]:
                    if r.get("type") != "assistant":
                        continue
                    for block in (r.get("message") or {}).get("content") or []:
                        given = block.get("input") or {} if isinstance(block, dict) else {}
                        if given.get("file_path") != name:
                            continue
                        if isinstance(given.get("content"), str):
                            expected = given["content"]
                        else:
                            for edit in given.get("edits") or [given]:
                                old, new = edit.get("old_string"), edit.get("new_string")
                                if (
                                    not isinstance(old, str)
                                    or not isinstance(new, str)
                                    or old not in expected
                                ):
                                    raise ValueError(
                                        "provider history cannot reconstruct this edit"
                                    )
                                expected = expected.replace(
                                    old, new, -1 if edit.get("replace_all") else 1
                                )
                if before is None:
                    creation_record = any(
                        name in files
                        and "backupFileName" in (files[name] or {})
                        and files[name]["backupFileName"] is None
                        for files in found.snapshots.values()
                    )
                    creation_record = creation_record or any(
                        isinstance(r.get("toolUseResult"), dict)
                        and r["toolUseResult"].get("type") == "create"
                        and r["toolUseResult"].get("filePath") == name
                        for r in records[found.start + 1 :]
                    )
                    if not creation_record:
                        raise ValueError(
                            "Provider history does not confirm a newly created file; no original backup is available"
                        )
                    if current != expected:
                        raise ValueError("the created file has additional changes")
                    restored = None
                elif current is None:
                    raise ValueError("the file was removed outside the recorded edits")
                else:
                    patch = history.text_diff(before, expected)
                    restored = history.unapply(current, patch)
            if restored == current:
                continue
            files.append(
                {
                    "path": name,
                    "requires": sorted(dependencies.get(name, {name})),
                    "canonical": str(file.resolve()),
                    "revision": _hash(current),
                    "text": restored,
                    "diff": "".join(
                        difflib.unified_diff(
                            (current or "").splitlines(True),
                            (restored or "").splitlines(True),
                            fromfile=name,
                            tofile=name,
                        )
                    ),
                }
            )
        except (ValueError, OSError, history.NotFound) as exc:
            skipped.append({"path": name, "reason": str(exc)})
    included = {f["path"] for f in files}
    for f in files:
        f["requires"] = [path for path in f["requires"] if path in included]
    token = secrets.token_urlsafe(24)
    with _lock:
        for key, value in list(_plans.items()):
            if time.monotonic() - value["at"] > 600:
                _plans.pop(key, None)
        _plans[token] = {
            "at": time.monotonic(),
            "owner": (str(config.data), provider, sid),
            "files": files,
        }
    return {
        "ok": True,
        "token": token,
        "files": [{k: v for k, v in f.items() if k != "text"} for f in files],
        "skipped": skipped,
        "coverage": "Provider history only; shell-only changes and missing checkpoints are excluded.",
    }


def apply(config, provider, sid, token, paths):
    with _lock:
        plan = _plans.get(token)
        if (
            not plan
            or plan["owner"] != (str(config.data), provider, sid)
            or time.monotonic() - plan["at"] > 600
        ):
            raise ValueError("This restore preview expired; preview it again")
        chosen = [f for f in plan["files"] if f["path"] in paths]
        if not chosen or len(chosen) != len(set(paths)):
            raise ValueError("Choose paths from this restore preview")
        if any(set(f.get("requires", [])) - set(paths) for f in chosen):
            raise ValueError("Select both sides of every recorded rename")
        for f in chosen:
            file = Path(f["path"])
            if (
                file.is_symlink()
                or str(file.resolve()) != f["canonical"]
                or (file.exists() and file.stat().st_nlink != 1)
                or _hash(history._on_disk(f["path"])) != f["revision"]
            ):
                raise ValueError(f"{f['path']} changed after the preview; nothing was restored")
        originals = {
            f["path"]: (Path(f["path"]).read_bytes(), Path(f["path"]).stat().st_mode & 0o777)
            if Path(f["path"]).exists()
            else (None, 0o600)
            for f in chosen
        }
        staged, applied = {}, []
        try:
            # Finish all preparation before changing a selected file. These temporary
            # writes are only for this explicit restore, never recurring snapshots.
            for f in chosen:
                if f["text"] is None:
                    continue
                file = Path(f["path"])
                file.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(dir=file.parent, prefix=".ax-restore-")
                staged[f["path"]] = temporary
                with os.fdopen(fd, "wb") as out:
                    out.write(f["text"].encode())
                    out.flush()
                    os.fsync(out.fileno())
                os.chmod(temporary, originals[f["path"]][1])
            for f in chosen:
                file = Path(f["path"])
                if _hash(history._on_disk(f["path"])) != f["revision"]:
                    raise ValueError(f"{f['path']} changed while preparing the restore")
                if f["text"] is None:
                    file.unlink(missing_ok=True)
                else:
                    os.replace(staged[f["path"]], file)
                applied.append(f)
        except (OSError, ValueError) as exc:
            remaining = []
            for f in reversed(applied):
                file = Path(f["path"])
                try:
                    if _hash(history._on_disk(f["path"])) != _hash(f["text"]):
                        raise ValueError("another writer changed the restored file")
                    content, mode = originals[f["path"]]
                    if content is None:
                        file.unlink(missing_ok=True)
                    else:
                        fd, temporary = tempfile.mkstemp(dir=file.parent, prefix=".ax-rollback-")
                        try:
                            with os.fdopen(fd, "wb") as out:
                                out.write(content)
                            os.chmod(temporary, mode)
                            os.replace(temporary, file)
                        finally:
                            Path(temporary).unlink(missing_ok=True)
                except (OSError, ValueError):
                    remaining.append(f["path"])
            detail = (
                f"Check these partially restored files: {', '.join(remaining)}"
                if remaining
                else "Original selected files were preserved."
            )
            raise ValueError(f"Restore stopped: {exc}. {detail}") from exc
        finally:
            for temporary in staged.values():
                Path(temporary).unlink(missing_ok=True)
        _plans.pop(token, None)
    live_sessions.clear_cache()
    return {"ok": True, "paths": [f["path"] for f in chosen], "message": "Selected files restored."}

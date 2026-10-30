"""Text diffs for the shared review UI, using Git or provider history."""

import difflib
import hashlib

from ax import session_changes as history


def read(config, provider, sid, base="turn", cwd=None):
    if base == "commit":
        if not cwd:
            cwd = history.changes(config, provider, sid)["cwd"]
        workspace = history.workspace(cwd)
        paths, coverage = workspace["paths"], workspace["coverage"]
    elif base in ("turn", "session"):
        found = history.changes(config, provider, sid)
        paths, coverage = found[base], found["coverage"]
    else:
        raise ValueError("Compare this turn or the workspace since commit")
    files, skipped = [], []
    for path in paths:
        try:
            before = (
                history._at_commit(path)
                if base == "commit"
                else history.before(config, provider, sid, path, base=base)
            )
            current = history._on_disk(path)
            if before == current:
                continue
            diff = "".join(
                difflib.unified_diff(
                    (before or "").splitlines(True),
                    (current or "").splitlines(True),
                    fromfile=path,
                    tofile=path,
                )
            )
            revision = (
                hashlib.sha256(current.encode()).hexdigest() if current is not None else "absent"
            )
            files.append({"path": path, "diff": diff, "revision": revision})
        except (history.NotFound, ValueError, OSError) as exc:
            skipped.append({"path": path, "reason": str(exc)})
    return {"files": files, "skipped": skipped, "coverage": coverage}

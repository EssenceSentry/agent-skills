"""Exchange provenance-bearing notes, preserving native generated memory files."""

import hashlib
import os
import re
import threading
from pathlib import Path

from ax.db import connect
from ax.redact import redact

LOCK = threading.Lock()
MARKER = "<!-- ax-shared-memory -->"
END = "<!-- /ax-shared-memory -->"


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".ax-tmp")
    temp.write_text(text)
    os.chmod(temp, 0o600)
    temp.replace(path)


def inputs(config):
    for path in (config.claude_home / "projects").glob("*/memory/**/*.md"):
        if path.name != "MEMORY.md" and not path.name.startswith("ax-"):
            yield "claude", path
    for root in (config.codex_home / "memories", config.codex_home / "memories_v2"):
        summary = root / "memory_summary.md"
        if summary.is_file():
            yield "codex", summary
        for path in (root / "extensions/ad_hoc/notes").glob("*.md"):
            if not path.name.startswith("ax-"):
                yield "codex", path


def sync(config):
    with LOCK:
        shared = config.data / "shared-memory"
        codex_root = config.codex_home / (
            "memories_v2" if (config.codex_home / "memories_v2").exists() else "memories"
        )
        exported = codex_root / "extensions/ad_hoc/notes"
        seen = set()
        report = {"updated": 0, "deleted": 0, "conflicts": [], "errors": []}
        for provider, source in inputs(config):
            origin = str(source.resolve())
            seen.add(origin)
            try:
                content = redact(source.read_text())
                if "<!-- ax-origin:" in content:
                    continue
                digest = hashlib.sha256(content.encode()).hexdigest()
                key = hashlib.sha256(origin.encode()).hexdigest()[:20]
                target = shared / (key + ".md")
                with connect(config) as db:
                    previous = db.execute(
                        "SELECT * FROM memories WHERE origin=?", (origin,)
                    ).fetchone()
                rendered = f"<!-- ax-origin: {origin} -->\n# Shared memory from {provider}\nSource: {origin}\n\n{content}"
                if previous and previous["digest"] == digest and not previous["deleted"]:
                    continue
                if previous and target.exists():
                    old = target.read_text()
                    old_content = old.split("\n\n", 1)[-1]
                    if (
                        not previous["deleted"]
                        and hashlib.sha256(old_content.encode()).hexdigest() != previous["digest"]
                    ):
                        report["conflicts"].append(str(target))
                        continue
                destination = exported / ("ax-" + key + ".md")
                if provider == "claude" and destination.exists():
                    expected = target.read_text() if target.exists() else None
                    if destination.read_text() != expected:
                        report["conflicts"].append(str(destination))
                        continue
                atomic(target, rendered)
                if provider == "claude":
                    atomic(destination, rendered)
                with connect(config) as db:
                    db.execute(
                        "INSERT OR REPLACE INTO memories VALUES(?,?,?,?,0)",
                        (origin, provider, digest, str(target)),
                    )
                report["updated"] += 1
            except (OSError, UnicodeError) as exc:
                report["errors"].append({"source": origin, "error": str(exc)})
        with connect(config) as db:
            rows = db.execute("SELECT * FROM memories WHERE deleted=0").fetchall()
        for row in rows:
            if row["origin"] in seen:
                continue
            key = Path(row["target"]).stem
            text = f"<!-- ax-origin: {row['origin']} -->\n# Withdrawn shared memory\nThe source note was removed. Withdraw its previous claims: {row['origin']}\n"
            target = Path(row["target"])
            if row["provider"] == "claude":
                destination = exported / ("ax-" + key + ".md")
                if destination.exists() and (
                    not target.exists() or destination.read_text() != target.read_text()
                ):
                    report["conflicts"].append(str(destination))
                    continue
                atomic(destination, text)
            atomic(target, text)
            with connect(config) as db:
                db.execute("UPDATE memories SET deleted=1 WHERE origin=?", (row["origin"],))
            report["deleted"] += 1
        with connect(config) as db:
            notes = db.execute("SELECT * FROM memories ORDER BY origin").fetchall()
        index = shared / "index.md"
        body = "# Shared memories\n\nShared notes from Claude and Codex, maintained by ax. Read relevant notes when needed.\n\n"
        body += (
            "\n".join(
                f"- [{r['provider']}: {Path(r['origin']).name}{' (withdrawn)' if r['deleted'] else ''}]({r['target']})"
                for r in notes
            )
            + "\n"
        )
        if not index.exists() or index.read_text() != body:
            atomic(index, body)
        instructions = config.claude_home / "CLAUDE.md"
        current = instructions.read_text() if instructions.exists() else ""
        block = f"{MARKER}\n@{index}\n{END}"
        pattern = re.compile(re.escape(MARKER) + ".*?" + re.escape(END), re.S)
        if (MARKER in current) != (END in current):
            report["conflicts"].append(str(instructions))
        else:
            updated = (
                pattern.sub(lambda _: block, current)
                if MARKER in current
                else current + "\n\n" + block + "\n"
            )
            if updated != current:
                atomic(instructions, updated)
        return report

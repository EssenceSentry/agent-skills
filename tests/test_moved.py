import json
import os

from ax import sync as sync_module
from ax.sources import claude
from ax.store import Store

SID = "aaaa1111-2222-4333-8444-555566667777"
SCRATCH = "/Users/me/Library/Application Support/Claude/scratch-workspaces/w1/scratch-a1"


def transcript(folder, cwds, *, day="2026-10-24"):
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for i, cwd in enumerate(cwds):
        records.append({"cwd": cwd, "sessionId": SID, "version": "2.1.283", "uuid": f"u{i}",
                        "entrypoint": "claude-desktop", "timestamp": f"{day}T12:0{i}:00.000Z",
                        "type": "user", "turnOrigin": "human",
                        "message": {"role": "user", "content": f"turn {i} in {cwd}"}})  # fmt: skip
    path = folder / f"{SID}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_a_conversation_moved_to_a_project_is_filed_under_it(tmp_path):
    folder = tmp_path / "projects" / "-Users-me-Repos-atelier"
    session = claude.parse(transcript(folder, [SCRATCH, SCRATCH, "/Users/me/Repos/atelier"]))
    assert session.cwd == "/Users/me/Repos/atelier" and session.project == "atelier"


def test_a_folder_the_transcript_does_not_live_in_is_not_its_project(tmp_path):
    folder = tmp_path / "projects" / "-Users-me-Repos-demo"
    session = claude.parse(transcript(folder, ["/Users/me/Repos/demo", "/Users/me/Repos/other"]))
    assert session.project == "demo"


def test_sync_keeps_the_newest_copy_of_a_conversation_kept_in_two_folders(env):
    projects = env.claude_home / "projects"
    old = transcript(projects / "-Users-me-Library-Application-Support-Claude-scratch-workspaces-w1-scratch-a1", [SCRATCH, SCRATCH])  # fmt: skip
    new = transcript(projects / "-Users-me-Repos-atelier",
                     [SCRATCH, SCRATCH, "/Users/me/Repos/atelier", "/Users/me/Repos/atelier"])  # fmt: skip
    os.utime(old, (1_000_000, 1_000_000))
    sync_module.sync(env.config)
    with Store(env.config.db_path) as store:
        row = store.session(f"claude:{SID}")
        turns = store.db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_key = ? AND role = 'user'", (row["key"],)
        ).fetchone()[0]
    assert row["project"] == "atelier" and turns == 4
    assert row["source_path"] == str(new) and "atelier" in row["note_path"]

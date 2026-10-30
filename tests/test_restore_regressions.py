from pathlib import Path

import pytest

from ax import session_changes, session_restore
from test_session_changes import TID, git
from test_session_changes import codex_thread as codex_thread
from test_session_changes import repo as repo


def test_workspace_includes_staged_untracked_renamed_and_deleted_paths(repo):
    (repo / "d.txt").write_text("delete me\n")
    git(repo, "add", "d.txt")
    git(repo, "commit", "-q", "-m", "add deletion target")
    (repo / "a.txt").write_text("staged change\n")
    git(repo, "add", "a.txt")
    (repo / "new.txt").write_text("untracked\n")
    git(repo, "mv", "b.txt", "renamed.txt")
    (repo / "d.txt").unlink()
    paths = set(session_changes.workspace(str(repo))["paths"])
    assert paths == {
        str(repo / name) for name in ("a.txt", "new.txt", "b.txt", "renamed.txt", "d.txt")
    }


def test_restore_rechecks_every_selected_revision_before_writing(env, codex_thread):
    repo, _, _ = codex_thread
    plan = session_restore.preview(env.config, "codex", TID)
    assert {f["path"] for f in plan["files"]} == {str(repo / "x.py"), str(repo / "y.py")}
    changed = (repo / "x.py").read_text() + "unrelated user work\n"
    (repo / "x.py").write_text(changed)
    with pytest.raises(ValueError, match="nothing was restored"):
        session_restore.apply(
            env.config, "codex", TID, plan["token"], [f["path"] for f in plan["files"]]
        )
    assert (repo / "x.py").read_text() == changed
    assert (repo / "y.py").read_text() == "y\n"


def test_selected_restore_leaves_other_dirty_files_alone(env, codex_thread):
    repo, _, _ = codex_thread
    plan = session_restore.preview(env.config, "codex", TID)
    changed = (repo / "x.py").read_text() + "keep this\n"
    (repo / "x.py").write_text(changed)
    session_restore.apply(env.config, "codex", TID, plan["token"], [str(repo / "y.py")])
    assert not (repo / "y.py").exists()
    assert (repo / "x.py").read_text() == changed


def test_an_added_file_with_later_user_edits_cannot_be_deleted_by_restore(env, codex_thread):
    repo, _, _ = codex_thread
    (repo / "y.py").write_text("y\nuser work\n")
    plan = session_restore.preview(env.config, "codex", TID)
    assert str(repo / "y.py") not in {f["path"] for f in plan["files"]}
    assert any(f["path"] == str(repo / "y.py") for f in plan["skipped"])


def test_steering_keeps_the_original_turn_boundary():
    records = [
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Start"}},
        {
            "type": "event_msg",
            "payload": {
                "item": {
                    "type": "FileChange",
                    "status": "completed",
                    "changes": {"/a": {"type": "add", "content": "a"}},
                }
            },
        },
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Steer"}},
        {
            "type": "event_msg",
            "payload": {
                "item": {
                    "type": "FileChange",
                    "status": "completed",
                    "changes": {"/b": {"type": "add", "content": "b"}},
                }
            },
        },
    ]
    found = session_changes._codex(records)
    assert [path for index, path in found.edits if index > found.start] == ["/a", "/b"]


def test_inverse_diffs_preserve_a_missing_final_newline():
    patch = session_changes.text_diff("before", "after")
    assert session_changes.unapply("after", patch) == "before"


def test_io_failure_rolls_back_earlier_files_in_the_same_restore(env, codex_thread, monkeypatch):
    repo, _, _ = codex_thread
    plan = session_restore.preview(env.config, "codex", TID)
    original = {f["path"]: Path(f["path"]).read_bytes() for f in plan["files"]}
    session_restore._plans[plan["token"]]["files"].sort(key=lambda f: f["path"], reverse=True)
    real_replace = session_restore.os.replace
    calls = []

    def fail_once(source, destination):
        calls.append(str(destination))
        if len(calls) == 1:
            raise OSError("simulated storage error")
        return real_replace(source, destination)

    # Delete the created file first, then fail on replacing the existing one.
    monkeypatch.setattr(session_restore.os, "replace", fail_once)
    with pytest.raises(ValueError, match="Original selected files were preserved"):
        session_restore.apply(
            env.config, "codex", TID, plan["token"], [str(repo / "y.py"), str(repo / "x.py")]
        )
    for path, content in original.items():
        assert Path(path).read_bytes() == content


def test_rename_restore_moves_content_back_and_refuses_a_partial_pair(env, tmp_path, monkeypatch):
    source, target = tmp_path / "old.py", tmp_path / "new.py"
    target.write_text("new\n")
    found = session_changes._codex(
        [
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {
                "type": "event_msg",
                "payload": {
                    "item": {
                        "type": "FileChange",
                        "status": "completed",
                        "changes": {
                            str(source): {
                                "type": "update",
                                "move_path": str(target),
                                "unified_diff": session_changes.text_diff("old\n", "new\n"),
                            }
                        },
                    }
                },
            },
        ]
    )
    monkeypatch.setattr(session_changes, "_read", lambda *args: found)
    path = tmp_path / "transcript.jsonl"
    path.write_text("")
    monkeypatch.setattr(session_restore.live_sessions, "transcript_path", lambda *args: path)
    plan = session_restore.preview(env.config, "codex", "rename")
    with pytest.raises(ValueError, match="both sides"):
        session_restore.apply(env.config, "codex", "rename", plan["token"], [str(target)])
    session_restore.apply(env.config, "codex", "rename", plan["token"], [str(source), str(target)])
    assert source.read_text() == "old\n" and not target.exists()


def test_restore_refuses_a_recreated_deleted_file(tmp_path):
    path = tmp_path / "deleted.py"
    path.write_text("user recreation\n")
    found = session_changes._Read(
        start=0, patches=[(1, str(path), {"type": "delete", "content": "old\n"})]
    )
    with pytest.raises(session_changes.NotFound, match="recreated"):
        session_changes._codex_turn(found, str(path))


def test_full_provider_session_diff_inverts_earlier_turns_too(env, codex_thread):
    repo, _, _ = codex_thread
    assert session_changes.before(
        env.config, "codex", TID, str(repo / "x.py"), base="session"
    ) != session_changes.before(env.config, "codex", TID, str(repo / "x.py"), base="turn")


def test_missing_claude_original_is_not_treated_as_a_known_new_file(env, tmp_path, monkeypatch):
    import json

    file = tmp_path / "existing.txt"
    file.write_text("replaced\n")
    records = [
        {
            "type": "file-history-snapshot",
            "messageId": "u1",
            "snapshot": {"trackedFileBackups": {}},
        },
        {"type": "user", "uuid": "u1", "message": {"content": "Change this file"}},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Write",
                        "input": {"file_path": str(file), "content": "replaced\n"},
                    }
                ]
            },
        },
    ]
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in records))
    monkeypatch.setattr(session_changes, "_read", lambda *args: session_changes._claude(records))
    monkeypatch.setattr(session_restore.live_sessions, "transcript_path", lambda *args: transcript)
    plan = session_restore.preview(env.config, "claude", "missing-original")
    assert not plan["files"]
    assert "no original backup" in plan["skipped"][0]["reason"]
    assert file.read_text() == "replaced\n"


def test_claude_steering_uses_the_original_checkpoint_boundary():
    records = [
        {
            "type": "file-history-snapshot",
            "messageId": "turn-start",
            "snapshot": {"trackedFileBackups": {}},
        },
        {
            "type": "user",
            "uuid": "turn-start",
            "promptId": "native-turn",
            "message": {"content": "Start work"},
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Write",
                        "input": {"file_path": "/before", "content": "before"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "uuid": "steer",
            "promptId": "native-turn",
            "message": {"content": "Keep going this way"},
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Write",
                        "input": {"file_path": "/after", "content": "after"},
                    }
                ]
            },
        },
    ]
    found = session_changes._claude(records)
    assert found.prompt == "turn-start"
    assert [path for index, path in found.edits if index > found.start] == ["/before", "/after"]


@pytest.mark.parametrize(
    "current,patch",
    [
        ("new\nnew\n", "@@ -1 +1 @@\n-old\n+new\n"),
        ("unrecorded work\n", "@@ -1 +0,0 @@\n-old\n"),
    ],
)
def test_restore_refuses_ambiguous_or_unlocated_inverse_hunks(current, patch):
    with pytest.raises(session_changes.CantUndo):
        session_changes.unapply(current, patch)

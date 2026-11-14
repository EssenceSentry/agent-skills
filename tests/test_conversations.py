import json
import os
import re
import time
from dataclasses import replace
from uuid import uuid4

import pytest

from ax import conversations


@pytest.fixture
def desktop(config, tmp_path, monkeypatch):
    monkeypatch.setattr(conversations, "desktop_running", lambda: False)
    root = tmp_path / "desktop"
    account, org = str(uuid4()), str(uuid4())
    folder = root / "claude-code-sessions" / account / org
    folder.mkdir(parents=True)
    (root / "config.json").write_text(json.dumps({"lastKnownAccountUuid": account}))
    config.claude_json.write_text(
        json.dumps({"oauthAccount": {"accountUuid": account, "organizationUuid": org}})
    )
    return replace(config, claude_desktop=root), folder


def transcript(
    config, tmp_path, *, entrypoint="claude-vscode", content="A human question", sidechain=False
):
    sid = str(uuid4())
    cwd = tmp_path / "project"
    cwd.mkdir(exist_ok=True)
    folder = config.claude_home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    folder.mkdir(parents=True, exist_ok=True)
    common = dict(sessionId=sid, cwd=str(cwd), entrypoint=entrypoint, isSidechain=sidechain)
    rows = [
        {
            **common,
            "type": "user",
            "timestamp": "2026-11-01T12:00:00Z",
            "message": {"role": "user", "content": content},
        },
        {
            **common,
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "Completed reply"}],
            },
        },
        {"type": "custom-title", "sessionId": sid, "customTitle": "Human title"},
    ]
    path = folder / (sid + ".jsonl")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    os.utime(path, (time.time() - 20,) * 2)
    return path


def test_add_once_preserves_transcript_and_client_record(desktop, tmp_path):
    config, folder = desktop
    source = transcript(config, tmp_path)
    original = source.read_bytes()
    first = conversations.sync(config)
    assert first["created"] == 1 and first["available"] and not first["errors"]
    target = folder / ("local_" + source.stem + ".json")
    record = json.loads(target.read_text())
    assert record["cliSessionId"] == source.stem
    assert record["model"] == "claude-sonnet-4-6"
    assert record["title"] == "Human title" and record["adoptedFromOtherSurface"]
    assert record["permissionMode"] == "default"
    assert record["alwaysAllowedReasons"] == []
    assert record["remoteMcpServersConfig"] == []
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.stat().st_nlink == 1
    record.update(title="Renamed in Desktop", isArchived=True, nativeField="preserve")
    target.write_text(json.dumps(record))
    before = target.read_bytes()
    assert conversations.sync(config)["created"] == 0
    assert target.read_bytes() == before and source.read_bytes() == original


def test_native_alias_archive_and_deleted_entries_are_not_resurrected(desktop, tmp_path):
    config, folder = desktop
    source = transcript(config, tmp_path)
    alias = folder / ("local_" + str(uuid4()) + ".json")
    alias.write_text(json.dumps({"cliSessionId": source.stem, "isArchived": True}))
    assert conversations.sync(config)["created"] == 0
    alias.unlink()
    # Ax remembers the observed association even if the client removes its record.
    assert conversations.sync(config)["created"] == 0
    deleted = transcript(config, tmp_path)
    (folder / ("deleted_" + deleted.stem)).write_text("1794000000")
    archived = transcript(config, tmp_path)
    (folder / "archived-sessions.idx").write_text(
        json.dumps({"v": 1, "archived": ["local_" + archived.stem]})
    )
    assert conversations.sync(config)["created"] == 0


@pytest.mark.parametrize(
    "entrypoint,sidechain", [("sdk-cli", False), ("claude-desktop", False), ("claude-vscode", True)]
)
def test_excludes_internal_sidechain_and_unlisted_desktop_history(
    desktop, tmp_path, entrypoint, sidechain
):
    config, folder = desktop
    transcript(config, tmp_path, entrypoint=entrypoint, sidechain=sidechain)
    report = conversations.sync(config)
    assert report["created"] == 0 and not report["errors"]
    assert not list(folder.glob("local_*.json"))


@pytest.mark.parametrize("failure", ["account", "org", "ambiguous_org", "identity"])
def test_identity_must_be_unambiguous_before_any_write(desktop, tmp_path, failure):
    config, folder = desktop
    transcript(config, tmp_path)
    if failure == "account":
        (config.claude_desktop / "config.json").write_text(
            json.dumps({"lastKnownAccountUuid": str(uuid4())})
        )
    elif failure == "org":
        identity = json.loads(config.claude_json.read_text())
        identity["oauthAccount"]["organizationUuid"] = str(uuid4())
        config.claude_json.write_text(json.dumps(identity))
    elif failure == "identity":
        config.claude_json.write_text("[]")
    else:
        (folder.parent / str(uuid4())).mkdir()
    report = conversations.sync(config)
    assert not report["available"]
    assert not list(folder.glob("local_*.json"))


def test_unreadable_or_unknown_registry_schema_withholds_registration(desktop, tmp_path):
    config, folder = desktop
    transcript(config, tmp_path)
    index = folder / "archived-sessions.idx"
    index.write_text(json.dumps({"v": 2, "archived": []}))
    report = conversations.sync(config)
    assert report["errors"] and report["created"] == 0
    index.unlink()
    (folder / ("local_" + str(uuid4()) + ".json")).write_text("broken")
    report = conversations.sync(config)
    assert report["errors"] and report["created"] == 0


def test_young_malformed_and_linked_transcripts_wait(desktop, tmp_path):
    config, folder = desktop
    source = transcript(config, tmp_path)
    os.utime(source, None)
    assert conversations.sync(config)["created"] == 0
    os.utime(source, (time.time() - 20,) * 2)
    linked = source.with_suffix(".backup")
    os.link(source, linked)
    assert conversations.sync(config)["created"] == 0
    linked.unlink()
    data = source.read_bytes()
    source.unlink()
    linked.write_bytes(data)
    source.symlink_to(linked)
    assert conversations.sync(config)["created"] == 0
    source.unlink()
    source.write_bytes(data + b'{"partial":')
    os.utime(source, (time.time() - 20,) * 2)
    assert conversations.sync(config)["created"] == 0
    assert not list(folder.glob("local_*.json"))


def test_registration_is_atomic_and_does_not_replace_a_racing_client(desktop):
    config, folder = desktop
    sid = str(uuid4())
    record = {"sessionId": "local_" + sid, "cliSessionId": sid}
    target = folder / (record["sessionId"] + ".json")
    target.write_text('{"native":"winner"}')
    assert conversations.create_record(folder, record) is False
    assert target.read_text() == '{"native":"winner"}'
    assert not list(folder.glob(".ax-register-*"))


def test_large_first_message_and_late_title_are_preserved(desktop, tmp_path):
    config, folder = desktop
    source = transcript(
        config,
        tmp_path,
        content=[
            {"type": "image", "source": {"data": "x" * 600000}},
            {"type": "text", "text": "Image question"},
        ],
    )
    report = conversations.sync(config)
    assert report["created"] == 1 and not report["errors"]
    record = json.loads((folder / ("local_" + source.stem + ".json")).read_text())
    assert record["title"] == "Human title"
    assert "xxxx" not in json.dumps(record)


def test_unavailable_desktop_has_no_side_effects(config):
    report = conversations.sync(config)
    assert not report["available"] and not report["errors"]


def test_waits_for_desktop_exit_without_writing_or_arming_a_model(desktop, tmp_path, monkeypatch):
    config, folder = desktop
    source = transcript(config, tmp_path)
    monkeypatch.setattr(conversations, "desktop_running", lambda: True)
    result = conversations.sync(config)
    assert result["pending"] == 1 and result["reason"] == "waiting_for_desktop_exit"
    assert result["created"] == 0 and not list(folder.glob("local_*.json"))
    monkeypatch.setattr(conversations, "desktop_running", lambda: False)
    assert conversations.sync(config)["created"] == 1
    assert source.exists()


def test_duplicate_native_transcript_ids_are_withheld(desktop, tmp_path):
    config, folder = desktop
    source = transcript(config, tmp_path)
    other = source.parent.with_name("another-project")
    other.mkdir()
    (other / source.name).write_bytes(source.read_bytes())
    result = conversations.sync(config)
    assert result["created"] == 0 and result["errors"]
    assert not list(folder.glob("local_*.json"))


def test_background_cli_conversations_are_not_registered(desktop, tmp_path):
    config, folder = desktop
    source = transcript(config, tmp_path, entrypoint="cli")
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    for row in rows:
        row["sessionKind"] = "bg"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))
    os.utime(source, (time.time() - 20,) * 2)
    report = conversations.sync(config)
    assert report["created"] == 0 and not report["errors"]
    assert not list(folder.glob("local_*.json"))


def test_daemon_runs_sync_only_in_maintenance_and_reports_it(desktop, monkeypatch):
    from ax.daemon import Core

    config, folder = desktop
    monkeypatch.setattr("ax.daemon.catalog.refresh", lambda config: {})
    monkeypatch.setattr("ax.daemon.memory.sync", lambda config: {})
    monkeypatch.setattr("ax.daemon.usage.snapshot", lambda config: {})
    calls = []
    monkeypatch.setattr(
        conversations, "sync", lambda config: calls.append(config) or {"created": 2, "errors": []}
    )
    core = Core(config)
    try:
        assert not calls
        core.maintain()
        assert calls == [config]
        assert core.dispatch("daemon.status", {})["conversation_sync"]["created"] == 2
    finally:
        core.pool.shutdown()
        core.maintenance.shutdown()


def test_same_claude_caller_rebinds_supervision_after_client_switch(config):
    from ax import tasks
    from ax.daemon import Core

    owner = "claude:" + str(uuid4())
    row = tasks.create(
        config,
        {
            "caller": owner,
            "purpose": "External work",
            "cwd": str(config.data),
            "inbox": "/old/socket",
            "inbox_token": "old-token",
        },
    )
    core = Core(config)
    try:
        core.dispatch(
            "daemon.status", {"caller": owner, "inbox": "/new/socket", "inbox_token": "new-token"}
        )
        updated = tasks.get(config, row["id"])
        assert updated["owner"] == owner and updated["id"] == row["id"]
        assert updated["inbox"] == "/new/socket" and updated["inbox_token"] == "new-token"
    finally:
        core.pool.shutdown()
        core.maintenance.shutdown()

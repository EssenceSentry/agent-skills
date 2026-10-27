"""What a session changed with its edit tools, and each file as it was before: when the
latest turn began, from the tool's own records, or at the last commit, from git."""

import difflib
import hashlib
import json
import subprocess
import threading
import urllib.request

import pytest

from ax import serve, session_changes

SID = "88888888-8888-4888-8888-888888888888"
TID = "99999999-9999-4999-8999-999999999999"


def write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def backup_name(path, version):
    return f"{hashlib.sha256(str(path).encode()).hexdigest()[:16]}@v{version}"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t",
                    *args], check=True, capture_output=True)  # fmt: skip


@pytest.fixture
def repo(tmp_path):
    """A repository whose last commit has a.txt and b.txt."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "a.txt").write_text("a0\n")
    (root / "b.txt").write_text("b0\n")
    git(root, "add", "a.txt", "b.txt")
    git(root, "commit", "-q", "-m", "start")
    return root


def edit(name, path):
    return {"type": "tool_use", "id": f"t-{name}-{path.name}", "name": name,
            "input": {"file_path": str(path), "old_string": "x", "new_string": "y"}}  # fmt: skip


@pytest.fixture
def claude_session(env, repo):
    """Turn 1 writes a.txt and edits b.txt; turn 2 edits a.txt, writes a new c.txt and
    edits d.txt, which no earlier turn touched. Claude's checkpoints keep each tracked
    file as it was at the start of every turn, and a file's first backup as it was before
    its first edit."""
    a, b, c, d = (repo / n for n in ("a.txt", "b.txt", "c.txt", "d.txt"))
    history = env.claude_home / "file-history" / SID
    history.mkdir(parents=True)
    (history / backup_name(a, 1)).write_text("a0\n")
    (history / backup_name(b, 1)).write_text("b0\n")
    (history / backup_name(a, 2)).write_text("a1\n")
    (history / backup_name(b, 2)).write_text("b1\n")
    (history / backup_name(d, 1)).write_text("d0\n")
    for path, text in ((a, "a2\n"), (b, "b1\n"), (c, "c\n"), (d, "d1\n")):
        path.write_text(text)

    def snapshot(message, files):
        return {"type": "file-history-snapshot", "messageId": message, "isSnapshotUpdate": False,
                "snapshot": {"messageId": message, "trackedFileBackups": {
                    str(p): {"backupFileName": name, "version": v} for p, name, v in files}}}  # fmt: skip

    at = "2026-10-27T12:00:{:02d}Z".format
    write(env.claude_home / "projects" / "-repo" / f"{SID}.jsonl", [
        snapshot("u1", []),
        {"type": "user", "uuid": "u1", "timestamp": at(1), "cwd": str(repo), "sessionId": SID,
         "message": {"role": "user", "content": "Write a and fix b"}},
        {"type": "assistant", "uuid": "r1", "timestamp": at(2), "message": {"role": "assistant",
         "content": [edit("Write", a), edit("Edit", b)]}},
        {"type": "user", "uuid": "x1", "timestamp": at(3), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t-Edit-b.txt", "content": "ok"}]}},
        snapshot("u2", [(a, backup_name(a, 2), 2), (b, backup_name(b, 2), 2)]),
        {"type": "user", "uuid": "u2", "timestamp": at(4), "cwd": str(repo), "sessionId": SID,
         "message": {"role": "user", "content": [{"type": "text", "text": "Now a, c and d"}]}},
        {"type": "assistant", "uuid": "r2", "timestamp": at(5), "message": {"role": "assistant",
         "content": [edit("Edit", a), edit("Write", c), edit("MultiEdit", d)]}},
    ])  # fmt: skip
    return repo


def test_lists_the_files_the_latest_turn_and_the_whole_session_changed(env, claude_session):
    repo = claude_session
    found = session_changes.changes(env.config, "claude", SID)
    assert found["cwd"] == str(repo)
    assert found["turn"] == [str(repo / n) for n in ("a.txt", "c.txt", "d.txt")]
    assert found["session"] == [str(repo / n) for n in ("a.txt", "b.txt", "c.txt", "d.txt")]


def test_rebuilds_each_file_as_it_was_when_the_turn_began(env, claude_session):
    repo = claude_session

    def before(name):
        return session_changes.before(env.config, "claude", SID, str(repo / name), base="turn")

    assert before("a.txt") == "a1\n"  # its checkpoint at the turn's start
    assert before("c.txt") is None  # it didn't exist yet
    assert before("d.txt") == "d0\n"  # first touched this turn: its first backup
    with pytest.raises(session_changes.NotFound, match="didn't change"):
        before("b.txt")  # changed in an earlier turn only


def test_shows_each_file_as_it_was_at_the_last_commit(env, claude_session):
    repo = claude_session

    def before(name):
        return session_changes.before(env.config, "claude", SID, str(repo / name), base="commit")

    assert before("b.txt") == "b0\n"
    assert before("a.txt") == "a0\n"
    assert before("c.txt") is None  # not committed
    with pytest.raises(session_changes.NotFound, match="didn't change"):
        before("unrelated.txt")  # only files the session changed are served


def test_says_so_when_claude_kept_no_checkpoint_for_the_turn(env, claude_session):
    path = env.claude_home / "projects" / "-repo" / f"{SID}.jsonl"
    path.write_text("".join(line + "\n" for line in path.read_text().splitlines()
                            if '"messageId": "u2"' not in line))  # fmt: skip
    with pytest.raises(session_changes.NotFound, match="checkpoint"):
        session_changes.before(
            env.config, "claude", SID, str(claude_session / "a.txt"), base="turn"
        )


def unified(old: str, new: str) -> str:
    """A diff as Codex records it: hunks only, no file headers, and the standard marker
    after a last line with no newline (which difflib leaves out)."""
    lines = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), n=1)
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                   for line in lines if not line.startswith(("---", "+++")))  # fmt: skip


@pytest.fixture
def codex_thread(env, repo):
    """Turn 1 adds x.py; turn 2 changes it twice and adds y.py. A failed patch counts for
    nothing."""
    x, y = repo / "x.py", repo / "y.py"
    x1 = "".join(f"line {i}\n" for i in range(1, 30))
    x2 = x1.replace("line 3\n", "line three\n").replace("line 25\n", "")
    x3 = x2.replace("line 10\n", "line 10\nline 10b\n") + "the end\n"
    x.write_text(x3)
    y.write_text("y\n")
    at = "2026-10-27T13:00:{:02d}.000Z".format

    def item(n, kind, **body):
        return {"timestamp": at(n), "type": "event_msg",
                "payload": {"type": "item_completed", "item": {"type": kind, "id": f"i{n}", **body}}}  # fmt: skip

    def change(n, changes, status="completed"):
        return item(n, "FileChange", changes=changes, status=status)

    meta = {"id": TID, "timestamp": at(0), "cwd": str(repo), "originator": "codex_vscode",
            "cli_version": "0.163.0", "source": "vscode"}  # fmt: skip
    write(env.codex_home / "sessions" / "2026" / "10" / "27" /
          f"rollout-2026-10-27T13-00-00-{TID}.jsonl", [
        {"timestamp": at(0), "type": "session_meta", "payload": meta},
        item(1, "UserMessage", content=[{"type": "text", "text": "Add x"}]),
        change(2, {str(x): {"type": "add", "content": x1}}),
        item(3, "UserMessage", content=[{"type": "text", "text": "Tidy x, add y"}]),
        change(4, {str(x): {"type": "update", "unified_diff": unified(x1, x2), "move_path": None}}),
        change(5, {str(repo / "z.py"): {"type": "add", "content": "z"}}, status="failed"),
        change(6, {str(x): {"type": "update", "unified_diff": unified(x2, x3), "move_path": None},
                   str(y): {"type": "add", "content": "y\n"}}),
    ])  # fmt: skip
    return repo, x1, x2


def test_codex_changes_come_from_its_file_change_records(env, codex_thread):
    repo, _, _ = codex_thread
    found = session_changes.changes(env.config, "codex", TID)
    assert found["cwd"] == str(repo)
    assert found["turn"] == [str(repo / "x.py"), str(repo / "y.py")]
    assert found["session"] == [str(repo / "x.py"), str(repo / "y.py")]


def test_codex_files_are_rebuilt_by_undoing_the_turns_diffs(env, codex_thread):
    repo, x1, _ = codex_thread
    assert session_changes.before(env.config, "codex", TID, str(repo / "x.py"), base="turn") == x1
    assert session_changes.before(env.config, "codex", TID, str(repo / "y.py"), base="turn") is None


def test_a_file_changed_outside_the_agent_since_is_not_guessed(env, codex_thread):
    repo, _, _ = codex_thread
    (repo / "x.py").write_text("rewritten by hand\n")
    with pytest.raises(session_changes.NotFound, match="changed since"):
        session_changes.before(env.config, "codex", TID, str(repo / "x.py"), base="turn")


@pytest.mark.parametrize(
    "old,new",
    [
        ("a\nb\nc\nd\ne\nf\ng\nh\n", "a\nB\nc\nd\ne\nf\nG\nh\n"),  # two hunks
        ("a\nb\nc\n", "a\nc\n"),  # a line removed
        ("a\nb\n", "a\nb\nc\nd\n"),  # lines added at the end
        ("a\nb", "a\nb\nc"),  # no newline at the end
        ("", "first\n"),
    ],
)
def test_undoing_a_diff_gives_back_the_old_text(old, new):
    assert session_changes.unapply(new, unified(old, new)) == old


def test_a_huge_or_binary_file_is_refused(env, claude_session):
    repo = claude_session
    (repo / "a.txt").write_bytes(b"\x00\x01binary")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "binary")
    with pytest.raises(session_changes.NotFound, match="text"):
        session_changes.before(env.config, "claude", SID, str(repo / "a.txt"), base="commit")


@pytest.fixture
def served(env, tmp_path, claude_session, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>ax</title>")
    server = serve.make_server(env.config, port=0, usage_of=lambda c: [], web=web, poll=0.05)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_the_app_serves_a_sessions_changes_and_files_before_them(env, served, claude_session):
    repo = claude_session
    status, found = get(f"{served}/api/session/changes?provider=claude&id={SID}")
    assert status == 200 and found["turn"] == [str(repo / n) for n in ("a.txt", "c.txt", "d.txt")]
    a = urllib.request.quote(str(repo / "a.txt"))
    assert get(f"{served}/api/session/before?provider=claude&id={SID}&path={a}&base=turn") == (
        200,
        {"exists": True, "text": "a1\n"},
    )
    c = urllib.request.quote(str(repo / "c.txt"))
    assert get(f"{served}/api/session/before?provider=claude&id={SID}&path={c}&base=commit") == (
        200,
        {"exists": False, "text": ""},
    )
    status, said = get(
        f"{served}/api/session/before?provider=claude&id={SID}&path=/etc/hosts&base=commit"
    )
    assert status == 404 and "didn't change" in said["error"]
    status, said = get(
        f"{served}/api/session/before?provider=claude&id={SID}&path={a}&base=yesterday"
    )
    assert status == 400


def test_the_app_serves_usage_alone_for_the_status_bar(env, served):
    status, found = get(f"{served}/api/usage")
    assert status == 200 and found == {"usage": [], "credits": []}

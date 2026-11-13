import contextlib
import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

import pytest

from ax.client import request
from ax.config import load


@pytest.fixture(params=["python", "native"])
def runtime(monkeypatch, request):
    flavor = request.param
    from ax.client import request as call

    with tempfile.TemporaryDirectory(prefix="ax-run-", dir="/tmp") as folder:
        root = Path(folder)
        path = root / "config.toml"
        path.write_text(
            "[paths]\n"
            + "\n".join(
                f'{k} = "{root / k}"'
                for k in ("data", "claude_home", "codex_home", "vault", "claude_json")
            )
        )
        monkeypatch.setenv("AX_CONFIG", str(path))
        monkeypatch.setenv("CODEX_THREAD_ID", "runner-owner")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        config = load()
        call(config, "daemon.status")
        if flavor == "native":
            from ax.build_launcher import build

            binary = build(config, sys.executable, root / "ax", path)
            monkeypatch.setenv("AX_TEST_LAUNCHER", str(binary))
        else:
            monkeypatch.delenv("AX_TEST_LAUNCHER", raising=False)
        try:
            yield config, root
        finally:
            with contextlib.suppress(Exception):
                call(config, "daemon.stop", autostart=False)
                until = time.monotonic() + 5
                while config.socket.exists() and time.monotonic() < until:
                    time.sleep(0.02)


def entrypoint():
    return (
        [os.environ["AX_TEST_LAUNCHER"]]
        if os.environ.get("AX_TEST_LAUNCHER")
        else [sys.executable, "-m", "ax"]
    )


def cli(*args, **kwargs):
    return subprocess.run([*entrypoint(), *args], capture_output=True, timeout=10, **kwargs)


def test_run_preserves_binary_stdio_environment_cwd_and_exit_status(runtime, monkeypatch):
    config, root = runtime
    monkeypatch.setenv("AX_RUN_EXAMPLE", "caller value")
    data = b"binary\x00input\xff\n"
    code = "import os,sys; assert os.environ['AX_RUN_EXAMPLE']=='caller value'; assert os.environ['CODEX_THREAD_ID']=='runner-owner'; assert os.getcwd()==sys.argv[1]; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stderr.buffer.write(b'exact stderr'); sys.exit(7)"
    result = cli("run", "--", sys.executable, "-c", code, str(root.resolve()), cwd=root, input=data)
    assert result.returncode == 7, result.stderr
    assert result.stdout == data
    assert result.stderr == b"exact stderr"
    rows = request(config, "task.list", {"all": True})
    assert rows[0]["every"] == 10 and rows[0]["status"] == "failed"
    assert "environment" not in rows[0]
    created = [e for e in request(config, "task.events") if e["type"] == "created"]
    expected = "native" if os.environ.get("AX_TEST_LAUNCHER") else "python"
    assert created[0]["data"]["launcher"] == expected
    assert not any(x["type"] == "model_call" for x in request(config, "task.events"))


def test_detach_then_attach_keeps_the_same_running_process(runtime):
    config, _ = runtime
    code = "import os,time; print(os.getpid(),flush=True); time.sleep(1.5); print('finished',flush=True)"
    process = subprocess.Popen(
        [*entrypoint(), "run", "--", sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    first = process.stdout.readline().decode().strip()
    assert first.isdigit()
    rows = request(config, "task.list")
    row = rows[0]
    worker_pid = row["pid"]
    detached = cli("detach", row["id"])
    assert detached.returncode == 0, detached.stderr
    out, err = process.communicate(timeout=5)
    assert process.returncode == 0 and b'"detached": true' in out
    assert request(config, "task.show", {"id": row["id"]})["task"]["status"] == "running"
    attached = cli("attach", row["id"], input=b"")
    assert attached.returncode == 0, attached.stderr
    assert attached.stdout.decode().splitlines() == [first, "finished"]
    assert request(config, "task.show", {"id": row["id"]})["task"]["pid"] == worker_pid


def test_detached_launch_and_literal_arguments(runtime):
    config, _ = runtime
    result = cli(
        "run",
        "--detach",
        "--",
        sys.executable,
        "-c",
        "import sys; print(sys.argv[1])",
        "literal $(not-a-command); text",
    )
    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)
    attached = cli("attach", row["id"], input=b"")
    assert attached.returncode == 0, attached.stderr
    assert attached.stdout == b"literal $(not-a-command); text\n"


def test_nonexistent_command_returns_shell_style_exit_code(runtime):
    result = cli("run", "--", "/definitely/not/an/executable", input=b"")
    assert result.returncode == 127
    assert result.stderr


def test_attached_terminal_gets_a_pty_and_accepts_input(runtime):
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 34, 101, 0, 0))
    command = [
        *entrypoint(),
        "run",
        "--",
        sys.executable,
        "-c",
        "import os; print('TTY',os.isatty(0),os.isatty(1),os.isatty(2),flush=True); print('SIZE',os.get_terminal_size().columns,os.get_terminal_size().lines,flush=True); print('RECEIVED',input(),flush=True)",
    ]
    process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    output = b""
    try:
        until = time.monotonic() + 8
        sent = False
        while time.monotonic() < until:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if b"TTY True True True" in output and not sent:
                    os.write(master, b"hello\n")
                    sent = True
            if process.poll() is not None:
                break
        process.wait(timeout=3)
        assert process.returncode == 0, output
        assert b"RECEIVED hello" in output
        assert b"SIZE 101 34" in output
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()


def test_event_ticks_are_numeric_and_do_not_change_task_state(runtime):
    config, _ = runtime
    row = request(
        config,
        "task.create",
        {"caller": "codex:runner-owner", "purpose": "external progress", "cwd": "/tmp"},
    )
    request(config, "task.update", {"id": row["id"], "done": 2, "total": 5})
    process = subprocess.Popen(
        [sys.executable, "-m", "ax", "task", "events", row["id"], "--follow"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(10):
            item = json.loads(process.stdout.readline())
            if item["type"] == "tick":
                break
        assert item["type"] == "tick"
        assert item["tasks"][0]["done"] == 2
        assert item["tasks"][0]["total"] == 5
        assert request(config, "task.show", {"id": row["id"]})["task"]["status"] == "running"
    finally:
        process.terminate()
        process.wait(timeout=3)
        request(config, "task.update", {"id": row["id"], "status": "done"})


def test_commands_that_close_stdin_early_keep_their_exit_code(runtime):
    result = cli(
        "run",
        "--",
        sys.executable,
        "-c",
        "import sys; sys.stdin.close(); print('early exit'); sys.exit(9)",
        input=b"data" * 10000,
    )
    assert result.returncode == 9, result.stderr
    assert result.stdout == b"early exit\n"

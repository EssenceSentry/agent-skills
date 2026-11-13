import contextlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ax.client import request
from ax.config import load


def wait_for(fn, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition did not become true")


def test_local_daemon_worker_restart_and_numeric_events(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="ax-test-", dir="/tmp") as folder:
        root = Path(folder)
        config_path = root / "config.toml"
        config_path.write_text(
            "[paths]\n"
            + "\n".join(
                f'{k} = "{root / k}"'
                for k in ("data", "claude_home", "codex_home", "vault", "claude_json")
            )
        )
        monkeypatch.setenv("AX_CONFIG", str(config_path))
        config = load()
        owner = "codex:actual-owner"
        try:
            status = request(config, "daemon.status")
            assert status["running"]
            assert config.socket.stat().st_mode & 0o777 == 0o600
            command = [
                sys.executable,
                "-c",
                "import os,time; print(os.environ['CODEX_THREAD_ID'],flush=True); time.sleep(3); print('finished',flush=True)",
            ]
            row = request(
                config,
                "task.create",
                {
                    "caller": owner,
                    "purpose": "bounded integration test",
                    "kind": "run",
                    "command": command,
                    "cwd": str(root),
                },
            )
            task_id = row["id"]
            wait_for(lambda: request(config, "task.show", {"id": task_id})["task"]["pid"])
            request(config, "task.update", {"id": task_id, "done": 1, "total": 2})
            request(config, "daemon.stop", autostart=False)
            wait_for(lambda: not config.socket.exists())
            restarted = request(config, "daemon.status")
            assert restarted["pid"] != status["pid"]
            result = wait_for(
                lambda: (
                    r
                    if (r := request(config, "task.show", {"id": task_id}))["task"]["status"]
                    == "done"
                    else None
                )
            )
            assert result["task"]["exit_code"] == 0
            assert "actual-owner" in result["recent_output"]
            rows = request(config, "task.events", {"id": task_id})
            assert any(r["type"] == "progress" and r["data"]["done"] == 1 for r in rows)
            assert any(r["type"] == "finished" for r in rows)
        finally:
            with contextlib.suppress(Exception):
                request(config, "daemon.stop", autostart=False)
                wait_for(lambda: not config.socket.exists())


def test_cli_rejects_old_surfaces_without_starting_daemon(monkeypatch, tmp_path):
    env = dict(os.environ, AX_CONFIG=str(tmp_path / "none.toml"))
    for command in ("serve", "mcp", "peers", "job", "hooks", "notify", "transfer"):
        result = subprocess.run(
            [sys.executable, "-m", "ax", command], capture_output=True, text=True, env=env
        )
        assert result.returncode == 2

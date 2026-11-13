"""A local socket client; the daemon starts on demand and owns background work."""

import contextlib
import json
import os
import socket
import subprocess
import sys
import time

MAX_MESSAGE = 2 * 1024 * 1024


def exchange(config, operation, args):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(180)
        sock.connect(str(config.socket))
        sock.sendall(
            (json.dumps({"operation": operation, "args": args}, allow_nan=False) + "\n").encode()
        )
        data = bytearray()
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                raise RuntimeError("daemon closed before answering")
            data.extend(chunk)
            if len(data) > MAX_MESSAGE:
                raise RuntimeError("daemon response exceeds limit")
        response = json.loads(data.split(b"\n", 1)[0])
        if not response.get("ok"):
            raise ValueError(response.get("error", "daemon request failed"))
        return response["result"]


def start(config):
    config.prepare()
    with open(config.data / "daemon.log", "ab") as log:
        os.chmod(config.data / "daemon.log", 0o600)
        subprocess.Popen(
            [sys.executable, "-m", "ax.daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, RuntimeError):
            return exchange(config, "daemon.status", {})
        time.sleep(0.05)
    raise RuntimeError("daemon did not start; inspect its local log")


def request(config, operation, args=None, autostart=True):
    args = args or {}
    try:
        return exchange(config, operation, args)
    except (FileNotFoundError, ConnectionRefusedError):
        if not autostart:
            return {"running": False}
        start(config)
        return exchange(config, operation, args)

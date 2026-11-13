"""Attach stdio to a background-owned task. Disconnecting never stops its process."""

import base64
import contextlib
import json
import os
import selectors
import signal
import socket
import sys
import termios
import time
import tty

from ax.streams import records
from ax.tasks import get


def detach(config, task_id):
    get(config, task_id)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(config.data / "tasks" / (task_id + ".sock")))
        sock.sendall(b'{"type":"detach"}\n')
    return {"id": task_id, "detached": True}


def attach(config, task_id):
    task = get(config, task_id)
    path = config.data / "tasks" / (task_id + ".stream")
    socket_path = config.data / "tasks" / (task_id + ".sock")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connected = False
    until = time.monotonic() + 10
    while time.monotonic() < until:
        try:
            sock.connect(str(socket_path))
            connected = True
            break
        except (FileNotFoundError, ConnectionRefusedError):
            task = get(config, task_id)
            if task["status"] not in ("starting", "running"):
                break
            time.sleep(0.005)
    if not connected and task["status"] in ("starting", "running"):
        raise RuntimeError("task attachment is unavailable; the task remains registered")
    selector = selectors.DefaultSelector()
    saved = None
    offset = 0
    old_int = signal.getsignal(signal.SIGINT)
    old_resize = signal.getsignal(signal.SIGWINCH)

    def send(value):
        if connected:
            sock.sendall((json.dumps(value) + "\n").encode())

    def interrupt(signum, frame):
        with contextlib.suppress(OSError):
            send({"type": "signal", "signal": signum})

    def resize(signum=None, frame=None):
        with contextlib.suppress(OSError):
            size = os.get_terminal_size(sys.stdin.fileno())
            send({"type": "resize", "rows": size.lines, "columns": size.columns})

    try:
        if connected:
            selector.register(sock, selectors.EVENT_READ, "socket")
            try:
                selector.register(sys.stdin, selectors.EVENT_READ, "stdin")
            except (OSError, ValueError):
                send({"type": "eof"})
            if sys.stdin.isatty() and task["tty"]:
                saved = termios.tcgetattr(sys.stdin.fileno())
                tty.setraw(sys.stdin.fileno())
                resize()
            signal.signal(signal.SIGINT, interrupt)
            signal.signal(signal.SIGWINCH, resize)
        while True:
            items, offset = records(path, offset)
            for item in items:
                if item["type"] == "output":
                    target = sys.stdout if item["stream"] == "stdout" else sys.stderr
                    data = base64.b64decode(item["data"])
                    target.buffer.write(data)
                    target.buffer.flush()
                elif item["type"] == "exit":
                    code = item["code"]
                    return (128 - code if code < 0 else code), False
            if not connected:
                task = get(config, task_id)
                if task["status"] in ("starting", "running"):
                    raise RuntimeError(
                        "attachment closed unexpectedly; the task remains registered"
                    )
                code = task["exit_code"]
                return (
                    code
                    if code is not None and code >= 0
                    else 128 - code
                    if code is not None
                    else 1
                ), False
            for key, _ in selector.select(0.01):
                if key.data == "socket":
                    control = sock.recv(1)
                    if control == b"D":
                        return 0, True
                    if not control:
                        selector.unregister(sock)
                        connected = False
                        break
                else:
                    data = os.read(sys.stdin.fileno(), 16384)
                    if not data:
                        selector.unregister(sys.stdin)
                        with contextlib.suppress(OSError):
                            send({"type": "eof"})
                    elif saved is not None and b"\x1d" in data:
                        return 0, True
                    else:
                        with contextlib.suppress(OSError):
                            send({"type": "input", "data": base64.b64encode(data).decode()})
    finally:
        if saved is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGWINCH, old_resize)
        selector.close()
        sock.close()

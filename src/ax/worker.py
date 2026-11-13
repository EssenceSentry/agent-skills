"""Own the background process and stdio, independently of daemon and attached clients."""

import base64
import contextlib
import errno
import fcntl
import json
import os
import pty
import signal
import socket
import struct
import subprocess
import sys
import termios
import threading
import time

from ax.config import load
from ax.db import connect, event
from ax.tasks import finish, get, process_identity


def main(task_id):
    config = load()
    task = get(config, task_id)
    stream_path = config.data / "tasks" / (task_id + ".stream")
    socket_path = config.data / "tasks" / (task_id + ".sock")
    lock = threading.Lock()
    clients = set()
    clients_lock = threading.Lock()
    input_lock = threading.Lock()
    stopped = threading.Event()
    child = None
    stopping = False
    master = None
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def forward(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    with connect(config) as db:
        db.execute(
            "UPDATE tasks SET pid=?,identity=?,status='running',updated=? WHERE id=?",
            (os.getpid(), process_identity(os.getpid()), time.time(), task_id),
        )
        event(db, task_id, "started", {"pid": os.getpid()})
    with stream_path.open("ab", buffering=0) as log:
        os.chmod(stream_path, 0o600)

        def emit(item):
            with lock:
                log.write((json.dumps(item) + "\n").encode())

        def output(source, name):
            try:
                while True:
                    data = os.read(source, 16384)
                    if not data:
                        break
                    emit(
                        {"type": "output", "stream": name, "data": base64.b64encode(data).decode()}
                    )
            except OSError as exc:
                if exc.errno not in (errno.EIO, errno.EBADF):
                    emit({"type": "output_error", "error": str(exc)})

        def handle(sock):
            nonlocal stopping
            try:
                with sock.makefile("rb") as reader:
                    while not stopped.is_set():
                        line = reader.readline(128 * 1024 + 1)
                        if not line or len(line) > 128 * 1024:
                            break
                        request = json.loads(line)
                        kind = request.get("type")
                        if kind == "input":
                            data = base64.b64decode(request["data"], validate=True)
                            with input_lock:
                                if master is not None:
                                    view = memoryview(data)
                                    while view:
                                        view = view[os.write(master, view) :]
                                elif child.stdin and not child.stdin.closed:
                                    with contextlib.suppress(BrokenPipeError):
                                        child.stdin.write(data)
                                        child.stdin.flush()
                        elif kind == "eof":
                            with input_lock:
                                if master is not None:
                                    os.write(master, b"\x04")
                                elif child.stdin and not child.stdin.closed:
                                    with contextlib.suppress(BrokenPipeError):
                                        child.stdin.close()
                        elif kind == "signal":
                            signum = request.get("signal")
                            if signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                                stopping = True
                                with contextlib.suppress(ProcessLookupError):
                                    os.killpg(child.pid, signum)
                        elif kind == "resize" and master is not None:
                            rows = max(1, min(int(request["rows"]), 1000))
                            cols = max(1, min(int(request["columns"]), 1000))
                            fcntl.ioctl(
                                master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0)
                            )
                        elif kind == "detach":
                            with clients_lock:
                                for client in list(clients):
                                    with contextlib.suppress(OSError):
                                        client.sendall(b"D")
                                        client.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError, KeyError):
                pass
            finally:
                with clients_lock:
                    clients.discard(sock)
                sock.close()

        def accept():
            while not stopped.is_set():
                try:
                    sock, _ = server.accept()
                    with clients_lock:
                        clients.add(sock)
                    threading.Thread(target=handle, args=(sock,), daemon=True).start()
                except TimeoutError:
                    continue
                except OSError:
                    break

        try:
            env = json.loads(task.get("environment") or "{}") or dict(os.environ)
            env["AX_TASK_ID"] = task_id
            provider, sid = task["owner"].split(":", 1)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            env.pop("CODEX_THREAD_ID", None)
            env["CLAUDE_CODE_SESSION_ID" if provider == "claude" else "CODEX_THREAD_ID"] = sid
            if provider == "claude" and task["inbox"] and task["inbox_token"]:
                env["CLAUDE_CODE_MESSAGING_SOCKET"] = task["inbox"]
                env["CLAUDE_CODE_MESSAGING_TOKEN"] = task["inbox_token"]
            if task["tty"]:
                master, slave = pty.openpty()
                fcntl.ioctl(
                    master,
                    termios.TIOCSWINSZ,
                    struct.pack(
                        "HHHH", int(env.get("LINES", 24)), int(env.get("COLUMNS", 80)), 0, 0
                    ),
                )

                def terminal():
                    os.setsid()
                    fcntl.ioctl(0, termios.TIOCSCTTY, 0)

                child = subprocess.Popen(
                    json.loads(task["command"]),
                    cwd=task["cwd"],
                    env=env,
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    preexec_fn=terminal,
                    close_fds=True,
                )
                os.close(slave)
                outputs = [threading.Thread(target=output, args=(master, "stdout"), daemon=True)]
            else:
                child = subprocess.Popen(
                    json.loads(task["command"]),
                    cwd=task["cwd"],
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    bufsize=0,
                )
                outputs = [
                    threading.Thread(target=output, args=(pipe.fileno(), name), daemon=True)
                    for pipe, name in ((child.stdout, "stdout"), (child.stderr, "stderr"))
                ]
            if env.get("AX_STDIN_CLOSED") == "1" and not task["tty"]:
                child.stdin.close()
            with connect(config) as db:
                db.execute("UPDATE tasks SET environment=NULL WHERE id=?", (task_id,))
            server.bind(str(socket_path))
            os.chmod(socket_path, 0o600)
            server.listen(8)
            server.settimeout(0.2)
            for thread in outputs:
                thread.start()
            threading.Thread(target=accept, daemon=True).start()
            if stopping:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGTERM)
            code = child.wait()
            for thread in outputs:
                thread.join(timeout=2)
            finish(
                config, task_id, "stopped" if stopping else "done" if code == 0 else "failed", code
            )
            emit({"type": "exit", "code": code})
        except Exception as exc:
            with connect(config) as db:
                event(db, task_id, "launch_error", {"error": str(exc)})
                db.execute("UPDATE tasks SET environment=NULL WHERE id=?", (task_id,))
            finish(config, task_id, "failed", 127)
            emit(
                {
                    "type": "output",
                    "stream": "stderr",
                    "data": base64.b64encode((str(exc) + "\n").encode()).decode(),
                }
            )
            emit({"type": "exit", "code": 127})
        finally:
            stopped.set()
            server.close()
            with clients_lock:
                for sock in clients:
                    with contextlib.suppress(OSError):
                        sock.shutdown(socket.SHUT_RDWR)
            if master is not None:
                with contextlib.suppress(OSError):
                    os.close(master)
            with contextlib.suppress(FileNotFoundError):
                socket_path.unlink()


if __name__ == "__main__":
    main(sys.argv[1])

"""`ax app`: keep the ax app served in the background, always there to open or install.

`start` runs `ax serve` detached and waits until it answers; any agent may run it. A
launchd agent (`ax app service --apply`) keeps it running from login and restarts it
whenever it stops. The app's address stays the same, which an installed app needs.
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser

PORT = 8765


def url(port: int = PORT) -> str:
    return f"http://127.0.0.1:{port}/"


def pid_file(config):
    return config.data / "app" / "serve.pid"


def log_file(config):
    return config.data / "app" / "serve.log"


def probe(port: int = PORT) -> bool:
    """Whether an ax app answers on the port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
            return response.status == 200 and response.read() == b"ok"
    except OSError:
        return False


def _spawn(argv: list[str], log) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True,
        )  # fmt: skip
    return process.pid


def start(config, *, port: int = PORT, spawn=_spawn, probe=probe, sleep=time.sleep,
          wait: float = 15) -> dict:  # fmt: skip
    """Start `ax serve` in the background unless an app already answers on the port."""
    if probe(port):
        return {"started": False, "pid": None, "url": url(port)}
    argv = [sys.executable, "-m", "ax.cli", "serve", "--port", str(port)]
    pid = spawn(argv, log_file(config))
    pid_file(config).parent.mkdir(parents=True, exist_ok=True)
    pid_file(config).write_text(f"{pid}\n")
    for _ in range(int(wait / 0.25)):
        if probe(port):
            return {"started": True, "pid": pid, "url": url(port)}
        sleep(0.25)
    raise RuntimeError(f"the app did not answer on port {port}; see {log_file(config)}")


def stop(config, *, kill=os.kill) -> bool:
    """End the server `start` began; False when it began none."""
    path = pid_file(config)
    if not path.exists():
        return False
    with contextlib.suppress(ValueError, ProcessLookupError):  # already gone
        kill(int(path.read_text().strip()), signal.SIGTERM)
    path.unlink(missing_ok=True)
    return True


def status(config, *, port: int = PORT, probe=probe, launch_agents=None) -> dict:
    from ax import glue

    folder = launch_agents or glue.launch_agents_dir()
    path = pid_file(config)
    return {
        "running": probe(port),
        "url": url(port),
        "pid": int(path.read_text().strip()) if path.exists() else None,
        "service": (folder / f"{glue.APP_LABEL}.plist").exists(),
    }


def open_in_browser(address: str) -> None:
    webbrowser.open(address)

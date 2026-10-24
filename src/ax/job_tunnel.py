"""Share a local dashboard through a Cloudflare quick tunnel, and replace it if it dies.

cloudflared keeps writing diagnostics after it prints its public link. Its output is
drained in a thread, because a full pipe would stall the tunnel. The link is checked
every 30 s and the tunnel replaced after three failed checks in a row.
"""

import collections
import re
import subprocess
import threading
import time
import urllib.request

_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class Tunnel:
    """One cloudflared quick-tunnel process."""

    def __init__(self, binary: str = "cloudflared"):
        self.binary = binary
        self.process: subprocess.Popen | None = None
        self.output: collections.deque[str] = collections.deque(maxlen=50)
        self._url: str | None = None
        self._found = threading.Event()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, local_url: str, timeout: float = 40) -> str:
        try:
            self.process = subprocess.Popen(
                [self.binary, "tunnel", "--url", local_url, "--no-autoupdate"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"cloudflared was not found at {self.binary!r}; install it (brew install "
                "cloudflared) or share with --share lan or none"
            ) from None
        threading.Thread(target=self._drain, daemon=True).start()
        deadline = time.monotonic() + timeout
        while not self._found.wait(0.1):
            if self.process.poll() is not None or time.monotonic() > deadline:
                recent = " | ".join(list(self.output)[-8:])
                ended = "exited" if self.process.poll() is not None else "gave no link in time"
                self.close()
                raise RuntimeError(f"cloudflared {ended}: {recent or 'no output'}")
        return self._url

    def _drain(self) -> None:
        for line in self.process.stdout:
            line = line.rstrip()
            self.output.append(line)
            if self._url is None:
                match = _URL.search(line)
                if match:
                    self._url = match.group(0)
                    self._found.set()

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _get_status(url: str, timeout: float) -> int:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status


def healthy(url: str, timeout: float = 10) -> bool:
    try:
        return _get_status(url.rstrip("/") + "/healthz", timeout) == 200
    except Exception:
        return False


class Share:
    """A quick tunnel kept alive: started once, checked on tick(), replaced when dead."""

    def __init__(
        self,
        local_url: str,
        *,
        binary: str = "cloudflared",
        on_url=None,
        health=healthy,
        tunnel_factory=None,
        interval: float = 30,
        failures: int = 3,
        clock=time.monotonic,
    ):
        self.local_url = local_url
        self.on_url = on_url or (lambda url: None)
        self.health = health
        self.make = tunnel_factory or (lambda: Tunnel(binary))
        self.interval, self.failures_allowed, self.clock = interval, failures, clock
        self.tunnel = None
        self.url: str | None = None
        self.failures = 0
        self.checked = 0.0

    def start(self) -> str:
        self.tunnel = self.make()
        self.url = self.tunnel.start(self.local_url)
        self.on_url(self.url)
        self.checked = self.clock()
        return self.url

    def tick(self) -> str | None:
        """Check the link when due; returns the new link if the tunnel was replaced."""
        now = self.clock()
        if now - self.checked < self.interval:
            return None
        self.checked = now
        if self.health(self.url):
            self.failures = 0
            return None
        self.failures += 1
        if self.failures < self.failures_allowed:
            return None
        old = self.tunnel
        try:
            replacement = self.make()
            url = replacement.start(self.local_url)
        except RuntimeError:
            return None  # try again at the next check
        old.close()
        self.tunnel, self.url, self.failures = replacement, url, 0
        self.on_url(url)
        return url

    def close(self) -> None:
        if self.tunnel is not None:
            self.tunnel.close()

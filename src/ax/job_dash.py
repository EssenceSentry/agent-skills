"""A one-job dashboard: a small page and its JSON, read-only, behind a token.

Only the job's own state is served, never the archive. Every data request needs the
token: the link carries it, the page keeps it in memory and sends it in a header, and
a Lax, HttpOnly cookie covers reloads. Only
localhost names, the LAN address and a tunnel's host name are answered. The page
reads the stored state; the follower refreshes the job, so a page view never calls
AWS.
"""

import hmac
import json
import secrets
import socket
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ax import job_eta, job_follow, jobs

COOKIE = "ax_job_token"
_TEMPLATES = Path(__file__).parent / "templates"
_STATIC = {
    "/app.js": ("job.js", "text/javascript; charset=utf-8"),
    "/app.css": ("job.css", "text/css; charset=utf-8"),
}
_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}
_LOG_BYTES = 16_000
# Progress rows can number thousands; the bar shows them, the list skips them. Stored
# estimates come every five minutes; the page shows the current one instead.
_QUIET_EVENTS = {"progress", "eta", "look"}  # looks have their own list
_CONSOLE_PATHS = {
    "processing": "processing-jobs",
    "training": "jobs",
    "transform": "transform-jobs",
}


def _lan_ip() -> str:
    """The address this Mac uses on its network (no traffic is sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _console_url(job) -> str | None:
    region = job.spec.get("region")
    if job.kind not in ("sagemaker", "seamless") or not region:
        return None
    path = _CONSOLE_PATHS.get(job.spec.get("type", "processing"), "processing-jobs")
    return (
        f"https://{region}.console.aws.amazon.com/sagemaker/home?region={region}"
        f"#/{path}/{job.spec['name']}"
    )


def _log_tail(job, config) -> str:
    log = Path(job.spec.get("log") or jobs.events_path(config, job.key).parent / "output.log")
    if not log.exists():
        return ""
    with log.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - _LOG_BYTES))
        tail = f.read().decode("utf-8", "replace")
    if size > _LOG_BYTES:
        tail = tail.split("\n", 1)[-1]  # drop the line cut in half
    return tail


class Dashboard:
    def __init__(self, config, key: str, *, lan=False, port=0, show_log=False, token=None):
        self.config, self.key, self.show_log = config, key, show_log
        self.token = token or secrets.token_urlsafe(24)
        self.lan_ip = _lan_ip() if lan else None
        self.hosts = {"localhost", "127.0.0.1", "::1"} | ({self.lan_ip} if self.lan_ip else set())
        self.httpd = ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), _handler(self))
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def lan_url(self) -> str | None:
        return f"http://{self.lan_ip}:{self.port}" if self.lan_ip else None

    def link(self, base: str | None = None) -> str:
        return f"{(base or self.local_url).rstrip('/')}/?token={self.token}"

    def allow_url(self, url: str) -> None:
        host = urlsplit(url).hostname
        if host:
            self.hosts.add(host)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def state(self) -> dict | None:
        return job_state(self.config, self.key, show_log=self.show_log)


def job_state(config, key: str, *, show_log: bool = False) -> dict | None:
    """What a job's page shows, from the follower's dashboard or from the ax app."""
    job = jobs.get(config, key)
    if job is None:
        return None
    recent = [
        e for e in jobs.events(config, key, limit=60, latest=True) if e["type"] not in _QUIET_EVENTS
    ][-15:]
    data = {
        **job.to_dict(),
        "progress_text": jobs.progress_text(job),
        "console_url": _console_url(job),
        "eta": job_eta.estimate(config, job),
        "events": recent,
        "looks": [
            {"at": e["ts"], "summary": e["data"].get("summary") or "",
             "problem": e["data"].get("problem"), "slow": e["data"].get("slow")}
            for e in reversed(jobs.events(config, key, limit=200, latest=True))
            if e["type"] == "look"
        ][:12],
        "check_every": job_follow.check_every(config, key),
    }  # fmt: skip
    for private in ("spec", "agent", "cwd"):
        data.pop(private, None)
    if show_log:
        data["log"] = _log_tail(job, config)
    return data


def page(name: str) -> bytes:
    """The job page's files, which the ax app serves too: job.html, job.js, job.css."""
    return (_TEMPLATES / name).read_bytes()


def _handler(dash: Dashboard):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ax-job"
        sys_version = ""

        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes, content_type: str, extra=None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in {**_HEADERS, **(extra or {})}.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _text(self, status: int, text: str) -> None:
            self._send(status, text.encode(), "text/plain; charset=utf-8")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").strip()
            if host.startswith("["):
                name = host[1 : host.find("]")]
            else:
                name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
            return name.lower() in dash.hosts

        def _token_ok(self, query_token: str | None) -> bool:
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            given = (
                query_token
                or self.headers.get("X-Ax-Token")
                or (cookie[COOKIE].value if COOKIE in cookie else "")
            )
            return bool(given) and hmac.compare_digest(given, dash.token)

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._text(403, "Unknown host name.")
            parts = urlsplit(self.path)
            if parts.path == "/healthz":
                return self._text(200, "ok")
            if parts.path in _STATIC:
                name, content_type = _STATIC[parts.path]
                return self._send(200, (_TEMPLATES / name).read_bytes(), content_type)
            query_token = (parse_qs(parts.query).get("token") or [None])[0]
            if not self._token_ok(query_token):
                return self._text(
                    401, "Open this dashboard with its full link; it carries an access token."
                )
            if parts.path == "/":
                # Served straight from the link, not through a redirect: a phone opening it
                # from the ntfy app counts as a cross-site visit and may withhold a cookie on
                # the redirected request. The page keeps the token in memory and sends it in a
                # header; the Lax cookie only makes a later reload work.
                extra = {}
                if query_token:
                    secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
                    extra["Set-Cookie"] = (
                        f"{COOKIE}={dash.token}; Path=/; HttpOnly; SameSite=Lax{secure}"
                    )
                return self._send(
                    200, (_TEMPLATES / "job.html").read_bytes(), "text/html; charset=utf-8", extra
                )
            if parts.path == "/api/job":
                state = dash.state()
                if state is None:
                    return self._text(404, "This job is gone.")
                return self._send(200, json.dumps(state).encode(), "application/json")
            return self._text(404, "Not found.")

        do_HEAD = do_GET

        def _refuse(self):
            self._text(405, "This dashboard is read-only.")

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

    return Handler


def serve(config, key: str, *, lan=False, port=0, show_log=False) -> Dashboard:
    """Start the dashboard in a background thread."""
    return Dashboard(config, key, lan=lan, port=port, show_log=show_log)

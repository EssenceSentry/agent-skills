"""A localhost dashboard: usage, jobs, runs, campaigns and recent sessions.

Standard library only. The server binds to 127.0.0.1, renders everything on
the server with every value HTML-escaped, and the page swaps in a fresh
fragment every few seconds. Each section is gathered on its own, so one
failing source shows as a note instead of an empty page.
"""

import hmac
import html
import json
import mimetypes
import threading
import time
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from ax import exp, job_eta, job_follow, jobs, runs, scorecard, usage
from ax.config import Config
from ax.config import load as load_config
from ax.store import Store

__all__ = ["Path", "load_config"]

_REFRESH_SECONDS = 5
_USAGE_TTL = 60  # Claude's helper is a subprocess; don't run it on every refresh.
_JOBS_SHOWN = 12
_FINISHED_SHOWN_FOR = 86400  # seconds a finished job stays on the panel
_CLAUDE_REFRESH = 300  # seconds between fresh /usage readings from Claude
_usage_lock = threading.RLock()


def collect_state(config: Config, *, usage_of=None, runs_of=None) -> dict:
    state = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "usage": [],
        "jobs": [],
        "runs": [],
        "sessions": [],
        "campaigns": [],
        "last_sync": None,
        "errors": [],
    }
    sections = {
        "usage": lambda: _usage_rows(config, usage_of or _cached_usage),
        "jobs": lambda: _jobs(config),
        "runs": lambda: [_run_row(r) for r in (runs_of or _runs)(config)],
        "sessions": lambda: _sessions(config),
        "campaigns": lambda: _campaigns(config),
    }
    for name, gather in sections.items():
        try:
            state[name] = gather()
        except Exception as exc:  # one broken source must not blank the page
            state["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
    if config.db_path.exists():
        with Store(config.db_path) as store:
            state["last_sync"] = store.get_meta("last_sync")
    return state


def obsidian_link(config: Config, note_path: str) -> str:
    vault = quote(config.vault.name, safe="")
    note = quote(note_path.removesuffix(".md"), safe="")
    return f"obsidian://open?vault={vault}&file={note}"


def render_page(state: dict) -> str:
    return _PAGE.format(style=_STYLE, body=render_body(state), refresh=_REFRESH_SECONDS * 1000)


def render_body(state: dict) -> str:
    e = html.escape
    parts = [
        '<header><h1>ax</h1><p class="muted">'
        f"last sync {e(_ago(state['last_sync']))} · updated {e(_clock(state['generated']))}"
        ' · <a href="/scorecard">scorecard</a></p></header>'
    ]
    if state["errors"]:
        notes = "".join(f"<li>{e(x)}</li>" for x in state["errors"])
        parts.append(f'<section class="notice"><ul>{notes}</ul></section>')
    parts.append(f'<section class="meters">{"".join(_meter(w) for w in state["usage"])}</section>')
    if state["jobs"]:
        parts.append(_panel("Jobs", _jobs_table(state["jobs"]), ""))
    parts.append('<div class="columns">')
    parts.append(_panel("Runs", _runs_table(state["runs"]), "No active or recent runs."))
    parts.append(
        _panel("Research", "".join(_campaign(c) for c in state["campaigns"]), "No campaigns yet.")
    )
    parts.append("</div>")
    parts.append(_panel("Recent sessions", _sessions_list(state["sessions"]), "No sessions."))
    return "\n".join(parts)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closing = threading.Event()  # ends the live streams
        self.hosts = {"127.0.0.1", "localhost", "::1"}

    def allow_url(self, url: str) -> None:
        """Answer a tunnel's host name too."""
        host = urlsplit(url).hostname
        if host:
            self.hosts.add(host.lower())

    def server_close(self):
        self.closing.set()
        super().server_close()


def make_server(
    config: Config,
    *,
    port: int = 8765,
    usage_of=None,
    web: Path | None = None,
    poll: float = 3.0,
    share_token: str | None = None,
) -> ThreadingHTTPServer:
    """The ax app (built pages, JSON, actions and a live stream) and the classic page.

    Everything but the pages' scripts and styles needs the token `app.token` keeps: the
    link carries it once, then a Strict, HttpOnly cookie. Actions also need JSON from
    the app's own origin, and only localhost names are answered, so neither another
    site nor one that rebinds its domain to 127.0.0.1 can read or act. A run shared
    through a tunnel also answers the tunnel's host (`allow_url`) and takes
    `share_token`, which dies with the run, so a shared link never carries the
    lasting one.
    """
    from ax import app

    web = web or app.WEB
    secrets_ = [t for t in (app.token(config), share_token) if t]

    def now() -> dict:
        return app.now_state(config, usage_of=usage_of)

    class Handler(BaseHTTPRequestHandler):
        server_version = "ax"
        sys_version = ""

        def log_message(self, *args):  # quiet: the terminal is for the URL
            pass

        def _send(self, status: int, body: bytes, kind: str, headers=None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for name, value in {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                                **(headers or {})}.items():  # fmt: skip
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _text(self, status: int, text: str) -> None:
            self._send(status, text.encode(), "text/plain; charset=utf-8")

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data).encode(), "application/json", _APP_HEADERS)

        def _host_ok(self) -> bool:
            # Refuse other host names, so a page that rebinds its domain to 127.0.0.1
            # (DNS rebinding) cannot read the dashboard.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host.lower() in self.server.hosts

        def _https(self) -> bool:
            return self.headers.get("X-Forwarded-Proto") == "https"  # behind the tunnel

        def _given(self, query: dict) -> tuple[str, str]:
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            for how, value in (
                ("query", (query.get("token") or [""])[0]),
                ("header", self.headers.get("X-Ax-Token") or ""),
                ("cookie", cookie[app.COOKIE].value if app.COOKIE in cookie else ""),
            ):
                if value:
                    return how, value
            return "", ""

        def _authorised(self, query: dict) -> str | None:
            how, value = self._given(query)
            known = any(hmac.compare_digest(value, t) for t in secrets_)
            return how if value and known else None

        def _static(self, path: str) -> bool:
            if not (path.startswith("/assets/") or path == "/favicon.svg"):
                return False
            root = web.resolve()
            target = (root / path.lstrip("/")).resolve()
            home = root / "assets" if path.startswith("/assets/") else root
            if ".." in path.split("/") or not target.is_relative_to(home) or not target.is_file():
                self._text(404, "Not found.")
                return True
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if kind.startswith("text/") or kind.endswith("javascript"):
                kind += "; charset=utf-8"
            cache = (
                "public, max-age=31536000, immutable" if path.startswith("/assets/") else "no-store"
            )
            self._send(200, target.read_bytes(), kind, {"Cache-Control": cache})
            return True

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._text(403, "Unknown host name.")
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if self._static(parts.path):
                return None
            how = self._authorised(query)
            if not how:
                return self._text(401, "Open the app with the link `ax serve` printed; "
                                       "it carries an access token.")  # fmt: skip
            if parts.path == "/":
                return self._page(how)
            if parts.path == "/events":
                return self._events()
            if parts.path in _CLASSIC:
                kind, build = _CLASSIC[parts.path]
                body = build(config, usage_of).encode()
                return self._send(200, body, f"{kind}; charset=utf-8")
            reads = {
                "/api/now": lambda: now(),
                "/api/notes": lambda: app.folder(config, (query.get("dir") or [""])[0]),
                "/api/note": lambda: app.note(config, (query.get("path") or [""])[0]),
            }
            try:
                if parts.path == "/api/file":
                    body, kind = app.file(config, (query.get("path") or [""])[0])
                    return self._send(200, body, kind, _APP_HEADERS)
                if parts.path in reads:
                    return self._json(200, reads[parts.path]())
            except app.NotFound as exc:
                return self._json(404, {"error": str(exc)})
            return self._text(404, "Not found.")

        def _page(self, how: str):
            index = web / "index.html"
            if not index.exists():
                return self._text(503, "The app isn't built: cd ui && npm run build. "
                                       "The classic page is at /classic.")  # fmt: skip
            # The page shows example data unless this marker says a live ax is behind it.
            page = index.read_text().replace(
                "</head>", '<meta name="ax-live" content="1"></head>', 1
            )
            headers = dict(_APP_HEADERS)
            if how == "query":
                token = (parse_qs(urlsplit(self.path).query).get("token") or [""])[0]
                secure = "; Secure" if self._https() else ""
                headers["Set-Cookie"] = (
                    f"{app.COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; "
                    f"Max-Age=31536000{secure}"
                )
            self._send(200, page.encode(), "text/html; charset=utf-8", headers)

        def _events(self):
            """The Now state on connect and again whenever it changes, as server-sent
            events, with a comment every so often so idle connections stay open."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            # Behind Cloudflare's tunnel a compressed or buffered stream never arrives.
            self.send_header("Cache-Control", "no-store, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            last, quiet_since = None, time.monotonic()
            try:
                while True:
                    state = now()
                    seen = json.dumps({k: v for k, v in state.items() if k != "generated"},
                                      sort_keys=True)  # fmt: skip
                    if seen != last:
                        self.wfile.write(f"data: {json.dumps(state)}\n\n".encode())
                        last, quiet_since = seen, time.monotonic()
                    elif time.monotonic() - quiet_since > _KEEPALIVE:
                        self.wfile.write(b": still here\n\n")
                        quiet_since = time.monotonic()
                    self.wfile.flush()
                    if self.server.closing.wait(poll):
                        return
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return self._text(403, "Unknown host name.")
            parts = urlsplit(self.path)
            if parts.path != "/api/act":
                return self._text(404, "Not found.")
            how = self._authorised({})
            if not how:
                return self._json(401, {"error": "no access token"})
            origin = self.headers.get("Origin")
            own = f"{'https' if self._https() else 'http'}://{self.headers.get('Host')}"
            if (origin or how == "cookie") and origin != own:
                return self._json(403, {"error": "actions come only from the app itself"})
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(415, {"error": "send JSON"})
            size = int(self.headers.get("Content-Length") or 0)
            if size > _MAX_BODY:
                return self._json(413, {"error": "too large"})
            try:
                payload = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("send a JSON object")
                said = app.act(config, str(payload.pop("action", "")), payload)
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            except Exception as exc:  # say what broke rather than drop the connection
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return self._json(200, {"ok": True, "message": said})

        def _refuse(self):
            self._text(405, "Not allowed.")

        do_PUT = do_DELETE = do_PATCH = _refuse

    return _Server(("127.0.0.1", port), Handler)


def keep_shared(tunnel, on_new, *, stop: threading.Event, every: float = 5) -> None:
    """Check the tunnel until `stop`; a dead one is replaced, and its new link announced."""
    while not stop.wait(every):
        url = tunnel.tick()
        if url:
            on_new(url)


_CLASSIC = {
    "/classic": ("text/html", lambda c, u: render_page(collect_state(c, usage_of=u))),
    "/fragment": ("text/html", lambda c, u: render_body(collect_state(c, usage_of=u))),
    "/api/state": ("application/json", lambda c, u: json.dumps(collect_state(c, usage_of=u))),
    "/scorecard": ("text/html", lambda c, u: scorecard.render(scorecard.build(c))),
}
_APP_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "Referrer-Policy": "no-referrer",
}
_KEEPALIVE = 15  # seconds between comments on a quiet stream
_MAX_BODY = 64_000


def _fresh_usage_cache() -> dict:
    return {"at": 0.0, "value": None, "refreshed": None, "refreshing": False}


_usage_cache: dict = _fresh_usage_cache()


def _start(job) -> None:
    threading.Thread(target=job, daemon=True).start()


def _cached_usage(config: Config, *, now: float | None = None, start=_start) -> list:
    """Both tools' windows, read again at most once a minute. Claude's figures are its own
    cache, so every five minutes a background thread asks Claude's /usage for fresh ones
    (a built-in command: no model call, no transcript); pages never wait for it."""
    now = time.time() if now is None else now
    with _usage_lock:
        due = _usage_cache["refreshed"] is None or now - _usage_cache["refreshed"] > _CLAUDE_REFRESH
        if due and not _usage_cache["refreshing"]:
            _usage_cache.update(refreshing=True, refreshed=now)

            def refresh():
                try:
                    usage.claude_windows(config, refresh=True)
                finally:
                    with _usage_lock:  # read again on the next request
                        _usage_cache.update(refreshing=False, at=0.0, value=None)

            start(refresh)
        if now - _usage_cache["at"] > _USAGE_TTL or _usage_cache["value"] is None:
            windows = usage.claude_windows(config, refresh=False)
            windows += usage.codex_windows(config.codex_home)
            usage.record(config, windows)
            _usage_cache.update(at=now, value=windows)
        return _usage_cache["value"]


def _usage_rows(config: Config, usage_of) -> list[dict]:
    now = datetime.now(UTC)
    rows = []
    for w in usage_of(config):
        forecast = usage.forecast(w, usage.history(config, w.provider, w.name), now)
        rows.append(
            {
                "provider": w.provider,
                "window": w.name,
                "used": w.used,
                "status": w.status,
                "resets_at": w.resets_at.isoformat() if w.resets_at else None,
                "observed_at": w.observed_at.isoformat() if w.observed_at else None,
                "lasts": forecast.lasts if forecast else None,
                "projected_high": forecast.projected_high if forecast else None,
                "runs_out_at": (
                    forecast.runs_out_at.isoformat() if forecast and forecast.runs_out_at else None
                ),
            }
        )
    return rows


def _jobs(config: Config) -> list[dict]:
    """Running jobs and those that ended in the last day, as stored: the page never
    refreshes a job itself, so a view never calls AWS. Followers and the background
    poller keep them current."""
    now = datetime.now(UTC)
    rows = []
    for job in jobs.list_jobs(config, include_finished=True, refresh_active=False):
        ended = jobs.parse_iso(job.finished) if job.finished else None
        if ended and (now - ended).total_seconds() > _FINISHED_SHOWN_FOR:
            continue
        eta = None if job.terminal else job_eta.estimate(config, job, now)
        follower = job_follow.running(config, job.key)
        rows.append(
            {
                "key": job.key,
                "label": job.label or (f"{job.kind} {job.ref}" if job.ref else job.kind),
                "status": job.status,
                "stage": job.stage,
                "progress": jobs.progress_text(job),
                "percent": round(100 * job.done / job.total) if job.total and job.done else None,
                "eta": eta["text"] if eta else None,
                "check_error": job.check_error,
                "updated": job.updated,
                "link": follower.get("link") if follower else None,
            }
        )
    running = [r for r in rows if r["status"] == "running"]
    ended = sorted((r for r in rows if r["status"] != "running"), key=lambda r: r["updated"])
    return (running + ended[::-1])[:_JOBS_SHOWN]


def _runs(config: Config):
    return runs.collect(config, since_days=1)


def _run_row(r) -> dict:
    return {
        "id": r.id,
        "source": r.source,
        "state": r.state,
        "title": r.title,
        "project": r.project,
        "updated": r.updated.isoformat() if r.updated else None,
    }


def _sessions(config: Config) -> list[dict]:
    if not config.db_path.exists():
        return []
    with Store(config.db_path) as store:
        rows = store.recent_sessions(15)
    return [
        {
            "title": r["title"],
            "provider": r["provider"],
            "project": r["project"],
            "ended": r["ended"],
            "link": obsidian_link(config, r["note_path"]),
        }
        for r in rows
    ]


def _campaigns(config: Config) -> list[dict]:
    found = []
    for note in sorted(config.vault.glob("Projects/*/Research/*/Campaign.md")):
        folder = note.parent
        summary = exp.summary(folder)
        top = [
            {"id": x.id, "question": x.question, "score": x.score}
            for x in exp.rank(exp.experiments(folder))[:3]
        ]
        found.append(
            {"name": folder.name, "project": folder.parent.parent.name, **summary, "top": top}
        )
    return found


def _meter(w: dict) -> str:
    e = html.escape
    label = f"{w['provider']} · {w['window'].replace('_', ' ')}"
    if w["used"] is None:
        return (
            f'<div class="card"><div class="label">{e(label)}</div>'
            f'<div class="big muted">unknown</div><div class="muted small">{e(w["status"])}</div></div>'
        )
    used = max(0.0, min(100.0, w["used"]))
    level = "high" if used >= 80 else "mid" if used >= 60 else "low"
    resets = f"resets {_until(w['resets_at'])}" if w["resets_at"] else ""
    pace = ""
    if w["lasts"] is False:
        pace = " · may run out before reset"
    elif w["lasts"]:
        pace = " · on pace"
    stale = "" if w["status"] == "fresh" else f" · {w['status']}"
    return (
        f'<div class="card"><div class="label">{e(label)}</div>'
        f'<div class="big">{used:.0f}%<span class="muted small"> used</span></div>'
        f'<div class="meter {level}"><span style="width:{used:.1f}%"></span></div>'
        f'<div class="muted small">{e(resets + pace + stale)}</div></div>'
    )


def _runs_table(rows: list[dict]) -> str:
    if not rows:
        return ""
    e = html.escape
    body = "".join(
        f'<tr><td><span class="state {e(r["state"])}">{e(r["state"])}</span></td>'
        f'<td>{e(r["title"][:80])}<div class="muted small">{e(r["source"])} · {e(r["project"])}'
        f" · {e(_ago(r['updated']))}</div></td></tr>"
        for r in rows[:20]
    )
    return f"<table>{body}</table>"


def _jobs_table(rows: list[dict]) -> str:
    e = html.escape
    out = []
    for r in rows:
        bar = ""
        if r["percent"] is not None:
            bar = f'<div class="meter"><span style="width:{min(r["percent"], 100)}%"></span></div>'
        detail = " · ".join(
            x for x in (r["progress"] if r["progress"] != "-" else "", r["eta"], r["stage"]) if x
        )
        key = e(r["key"])
        if r["link"]:
            key = f'<a href="{e(r["link"])}" target="_blank" rel="noopener noreferrer">{key}</a>'
        warn = f'<div class="warn small">{e(r["check_error"])}</div>' if r["check_error"] else ""
        out.append(
            f'<tr><td><span class="state {e(r["status"])}">{e(r["status"])}</span></td>'
            f'<td><strong>{key}</strong> <span class="muted small">{e(_short(r["label"], 70))}'
            f'</span>{bar}<div class="muted small">{e(detail)}{" · " if detail else ""}'
            f"updated {e(_ago(r['updated']))}</div>{warn}</td></tr>"
        )
    return f"<table>{''.join(out)}</table>"


def _campaign(c: dict) -> str:
    e = html.escape
    stall = '<div class="warn small">Three results changed nothing: rethink the direction.</div>'
    top = "".join(
        f'<li><span class="score">{x["score"]:.2f}</span> {e(x["id"])} {e(x["question"])}</li>'
        for x in c["top"]
    )
    budget = c["budget_hours"] or 0
    return (
        f'<div class="campaign"><div class="label">{e(c["project"])} / {e(c["name"])}</div>'
        f'<div class="muted small">{c["spent_hours"]:g} of {budget:g} h · {c["proposed"]} proposed'
        f" · {c['running']} running · {c['done']} done</div>"
        f'{stall if c["stalled"] else ""}<ol class="top">{top}</ol></div>'
    )


def _sessions_list(rows: list[dict]) -> str:
    if not rows:
        return ""
    e = html.escape
    items = "".join(
        f'<li><a href="{e(r["link"])}">{e(_short(r["title"] or "Untitled", 90))}</a>'
        f'<span class="muted small"> {e(r["provider"])} · {e(r["project"] or "")} · '
        f"{e(_ago(r['ended']))}</span></li>"
        for r in rows
    )
    return f'<ul class="sessions">{items}</ul>'


def _panel(title: str, content: str, empty: str) -> str:
    inner = content or f'<p class="muted">{html.escape(empty)}</p>'
    return f'<section class="panel"><h2>{html.escape(title)}</h2>{inner}</section>'


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ago(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    seconds = int((datetime.now(UTC) - then).total_seconds())
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if seconds >= size:
            return f"{seconds // size} {unit} ago"
    return "just now"


def _until(iso: str) -> str:
    seconds = int((datetime.fromisoformat(iso) - datetime.now(UTC)).total_seconds())
    if seconds <= 0:
        return "now"
    days, hours = divmod(seconds // 3600, 24)
    return f"in {days}d {hours}h" if days else f"in {hours}h {seconds % 3600 // 60}m"


def _clock(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%H:%M:%S")


_STYLE = """
:root { --bg:#f6f6f7; --panel:#fff; --text:#1c1c1f; --muted:#6b6b74; --line:#e4e4e8;
  --accent:#4f46e5; --mid:#b45309; --high:#b91c1c; --radius:10px; }
@media (prefers-color-scheme: dark) { :root { --bg:#111113; --panel:#1a1a1e; --text:#ececf0;
  --muted:#9a9aa4; --line:#2b2b31; --accent:#818cf8; --mid:#f59e0b; --high:#f87171; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width:1120px; margin:0 auto; padding:24px 16px 48px; }
header { display:flex; align-items:baseline; gap:12px; margin-bottom:16px; }
h1 { font-size:22px; margin:0; letter-spacing:-0.01em; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:0.06em; color:var(--muted);
  margin:0 0 12px; font-weight:600; }
.muted { color:var(--muted); } .small { font-size:12.5px; } .warn { color:var(--mid); }
.meters { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px;
  margin-bottom:12px; }
.card, .panel { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius);
  padding:14px 16px; }
.label { font-weight:600; margin-bottom:4px; }
.big { font-size:26px; font-weight:600; font-variant-numeric:tabular-nums; }
.meter { height:6px; background:var(--line); border-radius:3px; margin:8px 0; overflow:hidden; }
.meter span { display:block; height:100%; background:var(--accent); }
.meter.mid span { background:var(--mid); } .meter.high span { background:var(--high); }
.columns { display:grid; grid-template-columns:1.4fr 1fr; gap:12px; margin-bottom:12px; }
@media (max-width:760px) { .columns { grid-template-columns:1fr; } }
table { width:100%; border-collapse:collapse; }
td { padding:8px 6px; border-top:1px solid var(--line); vertical-align:top; }
tr:first-child td { border-top:none; }
.state { display:inline-block; font-size:12px; padding:1px 8px; border-radius:999px;
  border:1px solid var(--line); color:var(--muted); white-space:nowrap; }
.state.running, .state.waiting { color:var(--accent); border-color:var(--accent); }
.state.lost, .state.failed, .state.ended { color:var(--high); border-color:var(--high); }
td .meter { margin:6px 0 4px; max-width:420px; }
.campaign + .campaign { margin-top:14px; padding-top:14px; border-top:1px solid var(--line); }
.top { margin:8px 0 0; padding-left:0; list-style:none; }
.top li { margin:4px 0; } .score { font-variant-numeric:tabular-nums; color:var(--accent);
  font-weight:600; margin-right:6px; }
.sessions { list-style:none; margin:0; padding:0; columns:2 360px; }
.sessions li { margin:0 0 8px; break-inside:avoid; }
a { color:var(--text); text-decoration:none; border-bottom:1px solid var(--line); }
a:hover { border-color:var(--accent); }
.notice { background:var(--panel); border:1px solid var(--mid); border-radius:var(--radius);
  padding:4px 16px; margin-bottom:12px; color:var(--mid); }
"""

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ax dashboard</title><style>{style}</style></head>
<body><main id="app">{body}</main>
<script>
setInterval(async () => {{
  try {{
    const response = await fetch("/fragment", {{cache: "no-store"}});
    if (response.ok) document.getElementById("app").innerHTML = await response.text();
  }} catch (error) {{}}
}}, {refresh});
</script></body></html>"""

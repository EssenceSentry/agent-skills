import json
import urllib.error
import urllib.request

import pytest

from ax import job_dash, jobs


@pytest.fixture
def dash(env):
    servers = []

    def start(key="score", **kw):
        if not jobs.get(env.config, key):
            jobs.new(env.config, key, total=10, unit="rows", label="<b>Score</b> rows")
        server = job_dash.serve(env.config, key, **kw)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def request(server, path, *, token=None, host=None, cookie=None, method="GET"):
    url = server.local_url + path + (f"?token={token}" if token else "")
    req = urllib.request.Request(url, method=method)
    if host:
        req.add_header("Host", host)
    if cookie:
        req.add_header("Cookie", cookie)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        response = opener.open(req, timeout=5)
        return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_job_data_needs_the_token(dash):
    server = dash()
    assert request(server, "/api/job")[0] == 401
    assert request(server, "/api/job", token="wrong")[0] == 401
    status, headers, body = request(server, "/api/job", token=server.token)
    data = json.loads(body)
    assert status == 200 and data["key"] == "score" and data["total"] == 10
    assert data["label"] == "<b>Score</b> rows"


def test_the_link_serves_the_page_directly_and_sets_a_lax_cookie(dash):
    # A tap in the ntfy app is a cross-site visit: a redirect after it could arrive
    # without a Strict cookie, so the link must work in one request.
    server = dash()
    status, headers, body = request(server, "/", token=server.token)
    assert status == 200 and b'src="app.js"' in body
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert b"Score" not in body  # job data reaches the page only as JSON
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"
    assert request(server, "/", cookie=cookie.split(";")[0])[0] == 200


def test_the_page_can_send_the_token_in_a_header(dash):
    server = dash()
    req = urllib.request.Request(
        server.local_url + "/api/job", headers={"X-Ax-Token": server.token}
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        assert json.loads(response.read())["key"] == "score"
    bad = urllib.request.Request(server.local_url + "/api/job", headers={"X-Ax-Token": "nope"})
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(bad, timeout=5)
    assert refused.value.code == 401


def test_only_known_host_names_are_served(dash):
    server = dash()
    assert request(server, "/api/job", token=server.token, host="evil.example")[0] == 403
    server.allow_url("https://abc-def.trycloudflare.com")
    assert (
        request(server, "/api/job", token=server.token, host="abc-def.trycloudflare.com")[0] == 200
    )


def test_the_log_is_shown_only_when_asked(dash, env):
    server = dash()
    log = jobs.events_path(env.config, "score").parent / "output.log"
    log.write_text("".join(f"line {n}\n" for n in range(5000)))
    data = json.loads(request(server, "/api/job", token=server.token)[2])
    assert "log" not in data
    loud = dash(show_log=True)
    data = json.loads(request(loud, "/api/job", token=loud.token)[2])
    assert data["log"].endswith("line 4999\n") and "line 0\n" not in data["log"]


def test_health_is_open_and_writes_are_refused(dash):
    server = dash()
    assert request(server, "/healthz")[0] == 200
    assert request(server, "/api/job", token=server.token, method="POST")[0] == 405


def test_a_forgotten_job_is_not_found(dash, env):
    server = dash()
    jobs.forget(env.config, "score")
    assert request(server, "/api/job", token=server.token)[0] == 404


def test_events_and_a_console_link_are_included(dash, env, monkeypatch):
    jobs.new(env.config, "other")
    with open(jobs.events_path(env.config, "other"), "a") as f:
        f.write(json.dumps({"stage": "download"}) + "\n" + json.dumps({"done": 3}) + "\n")
    jobs.refresh(env.config, "other")  # the follower does this; the page only reads
    server = dash("other")
    data = json.loads(request(server, "/api/job", token=server.token)[2])
    assert [e["type"] for e in data["events"]] == [
        "created",
        "stage",
    ]  # progress rows are summarized
    assert data["progress_text"] == "3"
    assert data.get("console_url") is None


def test_the_page_shows_haiku_s_looks_newest_first(dash, env):
    from ax import job_follow

    server = dash()
    job_follow.set_check(env.config, "score", every=600)  # as `ax job check --every 10m` does
    for summary in ("Downloading shards.", "Scoring rows, 40 of 100 done."):
        jobs.record_event(env.config, "score", "look",
                          {"summary": summary, "problem": None, "every": 600})  # fmt: skip
    data = json.loads(request(server, "/api/job", token=server.token)[2])
    assert [x["summary"] for x in data["looks"]] == ["Scoring rows, 40 of 100 done.",
                                                     "Downloading shards."]  # fmt: skip
    assert data["check_every"] == 600
    assert "look" not in [e["type"] for e in data["events"]]  # shown in their own list

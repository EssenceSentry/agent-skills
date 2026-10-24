import os
import sys

import pytest

from ax import job_tunnel


def fake_cloudflared(tmp_path, body: str):
    script = tmp_path / "cloudflared"
    script.write_text(f"#!{sys.executable}\nimport sys, time\n{body}\n")
    script.chmod(0o755)
    return str(script)


def test_the_tunnel_reports_its_public_link_and_keeps_draining_output(tmp_path):
    binary = fake_cloudflared(
        tmp_path,
        "print('starting', flush=True)\n"
        "print('|  https://abc-def.trycloudflare.com  |', flush=True)\n"
        "for n in range(20000):\n    print('diagnostic line', n)\n"
        "sys.stdout.flush()\ntime.sleep(30)",
    )
    tunnel = job_tunnel.Tunnel(binary)
    try:
        assert tunnel.start("http://127.0.0.1:1") == "https://abc-def.trycloudflare.com"
        assert tunnel.running
    finally:
        tunnel.close()
    assert not tunnel.running


def test_a_missing_binary_or_an_early_exit_is_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="cloudflared"):
        job_tunnel.Tunnel(str(tmp_path / "nope")).start("http://127.0.0.1:1")
    binary = fake_cloudflared(
        tmp_path, "print('failed to reach the edge', flush=True)\nsys.exit(1)"
    )
    with pytest.raises(RuntimeError, match="failed to reach the edge"):
        job_tunnel.Tunnel(binary).start("http://127.0.0.1:1", timeout=10)


class FakeTunnel:
    def __init__(self, url):
        self.url, self.closed = url, False

    def start(self, local_url, timeout=40):
        return self.url

    def close(self):
        self.closed = True


def test_a_dead_link_is_replaced_after_three_failed_checks():
    made = [
        FakeTunnel("https://one.trycloudflare.com"),
        FakeTunnel("https://two.trycloudflare.com"),
    ]
    seen = []
    now = [0.0]
    health = {"ok": True}
    share = job_tunnel.Share(
        "http://127.0.0.1:1", on_url=seen.append, health=lambda url: health["ok"],
        tunnel_factory=lambda: made.pop(0), interval=30, clock=lambda: now[0],
    )  # fmt: skip
    first = share.start()
    assert first == "https://one.trycloudflare.com" and seen == [first]
    health["ok"] = False
    results = []
    for _ in range(3):
        now[0] += 31
        results.append(share.tick())
    assert results == [None, None, "https://two.trycloudflare.com"]
    assert seen[-1] == "https://two.trycloudflare.com"
    now[0] += 5
    assert share.tick() is None  # checks are spaced out
    share.close()


def test_share_checks_the_health_page(monkeypatch):
    calls = []
    monkeypatch.setattr(job_tunnel, "_get_status", lambda url, timeout: calls.append(url) or 200)
    assert job_tunnel.healthy("https://one.trycloudflare.com")
    assert calls == ["https://one.trycloudflare.com/healthz"]
    monkeypatch.setattr(
        job_tunnel, "_get_status", lambda url, timeout: (_ for _ in ()).throw(OSError())
    )
    assert not job_tunnel.healthy("https://one.trycloudflare.com")


@pytest.mark.skipif(not os.environ.get("AX_LIVE_TUNNEL"), reason="needs network and cloudflared")
def test_live_tunnel(tmp_path):
    tunnel = job_tunnel.Tunnel()
    try:
        assert tunnel.start("http://127.0.0.1:9").endswith(".trycloudflare.com")
    finally:
        tunnel.close()

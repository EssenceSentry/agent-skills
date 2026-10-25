import json
import plistlib
import signal

import pytest
from typer.testing import CliRunner

from ax import app_daemon, glue
from ax.cli import app as cli

PORT = 8799


def answers(*values):
    found = iter(values)
    return lambda port: next(found, values[-1])


def test_start_runs_ax_serve_in_the_background_and_waits_until_it_answers(env):
    started = []

    def spawn(argv, log):
        started.append((argv, log))
        return 4321

    found = app_daemon.start(env.config, port=PORT, spawn=spawn,
                             probe=answers(False, False, True), sleep=lambda s: None)  # fmt: skip
    assert found == {"started": True, "pid": 4321, "url": f"http://127.0.0.1:{PORT}/"}
    [(argv, log)] = started
    assert argv[-3:] == ["serve", "--port", str(PORT)]
    assert log == app_daemon.log_file(env.config)
    assert app_daemon.pid_file(env.config).read_text().strip() == "4321"


def test_start_leaves_a_running_app_alone(env):
    def spawn(argv, log):
        raise AssertionError("started a second server")

    found = app_daemon.start(env.config, port=PORT, spawn=spawn, probe=answers(True))
    assert found == {"started": False, "pid": None, "url": f"http://127.0.0.1:{PORT}/"}


def test_start_says_where_to_look_when_the_app_never_answers(env):
    with pytest.raises(RuntimeError, match="serve.log"):
        app_daemon.start(env.config, port=PORT, spawn=lambda argv, log: 1,
                         probe=answers(False), sleep=lambda s: None)  # fmt: skip


def test_stop_ends_the_server_it_started(env):
    app_daemon.pid_file(env.config).parent.mkdir(parents=True, exist_ok=True)
    app_daemon.pid_file(env.config).write_text("4321\n")
    sent = []
    assert app_daemon.stop(env.config, kill=lambda pid, sig: sent.append((pid, sig)))
    assert sent == [(4321, signal.SIGTERM)]
    assert not app_daemon.pid_file(env.config).exists()
    assert not app_daemon.stop(env.config, kill=lambda pid, sig: sent.append((pid, sig)))


def test_status_says_whether_it_answers_and_whether_launchd_keeps_it(env, tmp_path):
    (tmp_path / f"{glue.APP_LABEL}.plist").write_text("<plist/>")
    found = app_daemon.status(env.config, port=PORT, probe=answers(True), launch_agents=tmp_path)
    assert found == {"running": True, "url": f"http://127.0.0.1:{PORT}/", "pid": None,
                     "service": True}  # fmt: skip


def test_the_service_keeps_ax_serve_running_from_login(env, tmp_path):
    [change] = glue.plan_app_service(env.config, ax="/x/ax", launch_agents=tmp_path, port=8765)
    plist = plistlib.loads(change.after.encode())
    assert change.path == tmp_path / "com.ax.app.plist" and change.before is None
    assert plist["Label"] == "com.ax.app"
    assert plist["ProgramArguments"] == ["/x/ax", "serve", "--port", "8765"]
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert plist["StandardOutPath"].endswith("serve.log")


def test_the_service_can_share_through_cloudflare_and_send_each_link(env, tmp_path):
    [change] = glue.plan_app_service(env.config, ax="/x/ax", launch_agents=tmp_path, port=8765,
                                     share="cloudflare", notify=True)  # fmt: skip
    plist = plistlib.loads(change.after.encode())
    assert plist["ProgramArguments"] == ["/x/ax", "serve", "--port", "8765", "--share",
                                         "cloudflare", "--notify"]  # fmt: skip


def test_the_service_refuses_to_notify_without_a_topic(env, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from ax.cli import app as cli

    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.delenv("AX_NTFY_TOPIC", raising=False)
    monkeypatch.setattr(glue, "launch_agents_dir", lambda: tmp_path)
    result = CliRunner().invoke(cli, ["app", "service", "--share", "cloudflare", "--notify"])
    assert result.exit_code == 2 and "topic" in result.output
    monkeypatch.setenv("AX_NTFY_TOPIC", "my-topic")
    result = CliRunner().invoke(cli, ["app", "service", "--share", "cloudflare", "--notify"])
    assert result.exit_code == 0 and "--notify" in result.output  # a preview: nothing written
    assert not (tmp_path / "com.ax.app.plist").exists()


def test_the_commands_an_agent_runs(env, monkeypatch):
    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setattr(app_daemon, "start", lambda config, port: {
        "started": True, "pid": 7, "url": f"http://127.0.0.1:{port}/"})  # fmt: skip
    monkeypatch.setattr(app_daemon, "status", lambda config, port: {
        "running": False, "url": f"http://127.0.0.1:{port}/", "pid": None, "service": False})  # fmt: skip
    opened = []
    monkeypatch.setattr(app_daemon, "open_in_browser", opened.append)
    result = CliRunner().invoke(cli, ["app", "start"])
    assert result.exit_code == 0 and "http://127.0.0.1:8765/" in result.output
    result = CliRunner().invoke(cli, ["app", "status", "--json"])
    assert result.exit_code == 0 and json.loads(result.output)["running"] is False
    result = CliRunner().invoke(cli, ["app", "open"])
    assert result.exit_code == 0 and opened == ["http://127.0.0.1:8765/"]
    result = CliRunner().invoke(cli, ["app", "service"])
    assert result.exit_code == 0 and "com.ax.app" in result.output  # a preview only

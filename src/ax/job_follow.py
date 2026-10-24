"""Follow one job: refresh it, serve its mini dashboard, share it, send ntfy messages,
and wake the agent that registered it when it ends.

There is one follower per job. Its links and options live in the job's
follower.json, so a second `ax job follow` reuses the running follower and the
background poller can restart one that died. It exits once the job has ended and
the linger time has passed, or on SIGTERM.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from ax import job_notify, jobs

SHARES = ("none", "lan", "cloudflare")


class AlreadyFollowing(RuntimeError):
    def __init__(self, info: dict):
        super().__init__(f"this job already has a follower: {info.get('link')}")
        self.info = info


@dataclass
class FollowOptions:
    share: str = "none"
    notify: bool = False
    every: float = 900.0  # seconds between progress messages; 0 sends none
    notify_stages: bool = False
    stall_after: float | None = None
    linger: float = 120.0  # seconds the dashboard stays up after the job ends
    show_log: bool = False
    interval: float = 3.0
    port: int = 0
    dashboard: bool = True
    wake: str | None = None  # auto, claude or codex: resume that session when the job ends


def follower_path(config, key: str):
    return jobs.events_path(config, key).parent / "follower.json"


def _alive(pid: int) -> bool:
    from ax.job_sources import process_alive  # counts an unreaped, finished child as gone

    return process_alive(pid)


def running(config, key: str) -> dict | None:
    """The live follower's details, or None when there is none."""
    try:
        info = json.loads(follower_path(config, key).read_text())
    except (OSError, ValueError):
        return None
    pid = info.get("pid") if isinstance(info, dict) else None
    return info if isinstance(pid, int) and _alive(pid) else None


def _write_info(config, key: str, links: dict, options: "FollowOptions | None" = None) -> None:
    info = {
        "pid": os.getpid(),
        "link": links.get("public") or links.get("lan") or links.get("local"),
        **links,
        "started": jobs.now_iso(),
    }
    if options is not None:
        info["options"] = asdict(options)
    path = follower_path(config, key)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, indent=2))
    tmp.replace(path)


def _remove_info(config, key: str) -> None:
    path = follower_path(config, key)
    try:
        if json.loads(path.read_text()).get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass


def follow(
    config,
    key: str,
    options: FollowOptions,
    *,
    notifier=None,
    waker=None,
    on_ready=None,
    clock=time.time,
    sleep=time.sleep,
) -> str:
    """Follow the job until it ends and the linger passes. Returns its final status."""
    if options.share not in SHARES:
        raise ValueError(f"--share must be one of {', '.join(SHARES)}")
    job = jobs.refresh(config, key, now=datetime.fromtimestamp(clock(), UTC))
    if job is None:
        raise KeyError(key)
    existing = running(config, key)
    if existing:
        raise AlreadyFollowing(existing)
    if options.notify and notifier is None:
        ntfy = job_notify.settings(config)
        if ntfy is None:
            raise ValueError("no ntfy topic: set [notify] topic in config.toml or AX_NTFY_TOPIC")

        def notifier(message):
            return job_notify.send(ntfy, **message)

    def notify(message: dict) -> None:
        if not options.notify or notifier is None:
            return
        error = notifier(message)
        if error:
            jobs.record_event(
                config, key, "notify_failed", {"title": message["title"], "error": error}
            )
        else:
            jobs.record_event(config, key, "notified", {"title": message["title"]})

    if options.wake and waker is None:
        from ax import job_wake

        def waker(job):
            return job_wake.wake(config, job, options.wake)

    def wake(job) -> None:
        if not options.wake or waker is None:
            return
        from ax.job_wake import WakeError

        try:
            waker(job)
        except (WakeError, OSError) as exc:
            jobs.record_event(config, key, "wake_failed", {"error": str(exc)})

    stopping = threading.Event()
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    closers = []
    links: dict = {}
    try:
        share = None
        if options.dashboard:
            from ax import job_dash

            server = job_dash.serve(
                config,
                key,
                lan=options.share == "lan",
                port=options.port,
                show_log=options.show_log,
            )
            closers.append(server.close)
            links["local"] = server.link()
            if options.share == "lan":
                links["lan"] = server.link(server.lan_url)
            if options.share == "cloudflare":
                from ax import job_tunnel

                share = job_tunnel.Share(server.local_url, on_url=server.allow_url)
                closers.append(share.close)
                links["public"] = server.link(share.start())
        _write_info(config, key, links, options)
        link = links.get("public") or links.get("lan") or links.get("local")
        if on_ready:
            on_ready(running(config, key) or {"link": link, **links})
        notify(job_notify.started(job, link, _eta(config, job, options)))
        relink = server.link if options.dashboard else None
        return _loop(
            config, key, options, job, link, links, share, relink, notify, wake, stopping, clock,
            sleep,
        )  # fmt: skip
    finally:
        for close in reversed(closers):
            close()
        _remove_info(config, key)
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def _eta(config, job, options) -> dict | None:
    if not options.notify:
        return None
    from ax import job_eta

    return job_eta.estimate(config, job)


def _loop(
    config, key, options, job, link, links, share, relink, notify, wake, stopping, clock, sleep
) -> str:
    end_at = None
    last_note, noted = clock(), (job.done, job.stage)
    last_stage = job.stage
    stalled_sent = False
    while not stopping.is_set():
        now = clock()
        job = jobs.refresh(config, key, now=datetime.fromtimestamp(now, UTC)) or job
        if share is not None:
            replaced = share.tick()
            if replaced:
                link = links["public"] = relink(replaced)
                _write_info(config, key, links, options)
                notify(job_notify.link_changed(job, link))
        if job.terminal:
            if end_at is None:
                end_at = now
                notify(job_notify.finished(job, link))
                wake(job)
            if now - end_at >= options.linger:
                break
        else:
            if options.notify_stages and job.stage and job.stage != last_stage:
                notify(job_notify.stage(job, link))
            last_stage = job.stage
            if (
                options.every
                and now - last_note >= options.every
                and (job.done, job.stage) != noted
            ):
                notify(job_notify.progress(job, link, _eta(config, job, options)))
                last_note, noted = now, (job.done, job.stage)
            if options.stall_after is not None:
                quiet = now - jobs.parse_iso(job.changed).timestamp()
                if quiet >= options.stall_after and not stalled_sent:
                    notify(job_notify.stalled(job, quiet, link))
                    stalled_sent = True
                elif quiet < options.stall_after:
                    stalled_sent = False
        sleep(options.interval)
    return job.status


def stop(config, key: str, timeout: float = 10) -> bool:
    """Ask a job's follower to stop; True if one was running."""
    info = running(config, key)
    if not info:
        return False
    os.kill(info["pid"], signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _alive(info["pid"]):
        time.sleep(0.1)
    return True


def start_detached(config, key: str, args: list[str], timeout: float = 60) -> dict:
    """Run `ax job follow KEY ARGS` in the background; returns its follower.json."""
    existing = running(config, key)
    if existing:
        return existing
    log = follower_path(config, key).with_name("follower.log")
    with log.open("ab") as out:
        child = subprocess.Popen(
            [sys.executable, "-m", "ax.cli", "job", "follow", key, *args],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = running(config, key)
        if info and info.get("pid") == child.pid:
            return info
        if child.poll() is not None:
            tail = log.read_text(errors="replace").strip().splitlines()[-5:]
            raise RuntimeError("the follower stopped: " + (" | ".join(tail) or "no output"))
        time.sleep(0.2)
    child.terminate()
    raise RuntimeError(f"the follower gave no link within {timeout:.0f} s; see {log}")

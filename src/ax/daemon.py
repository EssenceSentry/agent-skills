"""One local daemon: JSON over a private Unix socket, no HTTP or user notifications."""

import contextlib
import fcntl
import json
import os
import signal
import socketserver
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ax import __version__, budget, catalog, memory, tasks, usage
from ax.config import load
from ax.db import connect, events, initialize, public_task
from ax.providers import flush_escalations
from ax.redact import redact


class Core:
    def __init__(self, config):
        self.config = config
        initialize(config)
        self.stopped = threading.Event()
        self.errors = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ax-inspect")
        self.maintenance = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ax-maintain")
        self.reviews = {}
        self.maintenance_job = None
        with connect(config) as db:
            db.execute("UPDATE tasks SET reviewing=0 WHERE reviewing=1")
            db.execute(
                "UPDATE escalations SET status='uncertain',error='daemon restarted during dispatch' WHERE status='dispatching'"
            )

    def bind(self, args):
        if args.get("caller") and args.get("inbox") and args.get("inbox_token"):
            with connect(self.config) as db:
                db.execute(
                    "UPDATE tasks SET inbox=?,inbox_token=? WHERE owner=?",
                    (args["inbox"], args["inbox_token"], args["caller"]),
                )

    def dispatch(self, operation, args):
        config = self.config
        self.bind(args)
        if operation == "daemon.status":
            with connect(config) as db:
                running = db.execute(
                    "SELECT count(*) FROM tasks WHERE status IN ('starting','running')"
                ).fetchone()[0]
                attention = db.execute(
                    "SELECT count(*) FROM escalations WHERE status IN ('pending','uncertain')"
                ).fetchone()[0]
            return {
                "running": True,
                "version": __version__,
                "pid": os.getpid(),
                "socket": str(config.socket),
                "active_tasks": running,
                "undelivered_concerns": attention,
                "maintenance": self.errors,
            }
        if operation == "daemon.stop":
            self.stopped.set()
            return {"stopping": True}
        if operation == "search":
            report = catalog.refresh(config)
            return {
                "results": catalog.search(
                    config,
                    args["query"],
                    args.get("provider"),
                    args.get("project"),
                    args.get("limit", 10),
                ),
                "index": report,
            }
        if operation == "handoff":
            catalog.refresh(config)
            return catalog.handoff(config, args["topic"], args["caller"])
        if operation == "memory.sync":
            return memory.sync(config)
        if operation == "task.create":
            return tasks.create(config, args)
        if operation == "task.update":
            return tasks.update(config, args["id"], args)
        if operation == "task.stop":
            return tasks.stop(config, args["id"])
        if operation == "task.show":
            task = tasks.get(config, args["id"])
            return tasks.snapshot(config, task)
        if operation == "task.list":
            with connect(config) as db:
                sql = (
                    "SELECT * FROM tasks"
                    + ("" if args.get("all") else " WHERE status IN ('running','starting')")
                    + " ORDER BY started DESC"
                )
                return [public_task(r) for r in db.execute(sql)]
        if operation == "task.events":
            return events(config, args.get("after", 0), args.get("id"))
        if operation == "usage":
            return usage.snapshot(config, args.get("refresh", False))
        if operation == "budget.show":
            return usage.budgets(config, args.get("name"))
        if operation == "budget.set":
            return budget.create(
                config.data, args["name"], args["amount"], args["unit"], owner=args.get("caller")
            )
        if operation == "budget.add":
            return budget.add(config.data, args["name"], args["amount"])
        if operation == "budget.reserve":
            return {"ticket": budget.reserve(config.data, args["name"], args["amount"])}
        if operation == "budget.settle":
            return budget.settle(config.data, args["ticket"], args["amount"])
        if operation == "budget.release":
            return budget.release(config.data, args["ticket"])
        if operation == "budget.close":
            return budget.close(config.data, args["name"])
        raise ValueError("unknown ax operation")

    def maintain(self):
        for name, action in (
            ("search", lambda: catalog.refresh(self.config)),
            ("memory", lambda: memory.sync(self.config)),
            ("usage", lambda: usage.snapshot(self.config)),
        ):
            try:
                result = action()
                issues = (
                    result.get("errors", []) + result.get("conflicts", [])
                    if isinstance(result, dict)
                    else []
                )
                if issues:
                    self.errors[name] = issues
                else:
                    self.errors.pop(name, None)
            except Exception as exc:
                self.errors[name] = redact(str(exc))

    def tick(self):
        tasks.reconcile(self.config)
        self.reviews = {key: future for key, future in self.reviews.items() if not future.done()}
        available = 2 - len(self.reviews)
        if available > 0:
            with connect(self.config) as db:
                rows = db.execute(
                    "SELECT id,every FROM tasks WHERE status='running' AND reviewing=0 AND next_review<=? ORDER BY next_review LIMIT ?",
                    (time.time(), available),
                ).fetchall()
                for row in rows:
                    db.execute(
                        "UPDATE tasks SET reviewing=1,next_review=? WHERE id=?",
                        (time.time() + row["every"] * 60, row["id"]),
                    )
            for row in rows:
                self.reviews[row["id"]] = self.pool.submit(tasks.inspect, self.config, row["id"])
        flush_escalations(self.config)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.connection.settimeout(10)
            raw = self.rfile.readline(128 * 1024 + 1)
            if len(raw) > 128 * 1024 or not raw.endswith(b"\n"):
                raise ValueError("invalid request size or framing")
            request = json.loads(raw)
            result = self.server.core.dispatch(request["operation"], request.get("args", {}))
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": redact(str(exc))}
        with contextlib.suppress(BrokenPipeError):
            self.wfile.write((json.dumps(response, allow_nan=False) + "\n").encode())


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    config = load()
    config.prepare()
    with open(config.data / "daemon.lock", "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with contextlib.suppress(FileNotFoundError):
            config.socket.unlink()
        core = Core(config)

        def stop(signum, frame):
            core.stopped.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            with Server(str(config.socket), Handler) as server:
                os.chmod(config.socket, 0o600)
                server.core = core
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                last_maintenance = 0
                while not core.stopped.wait(1):
                    try:
                        core.tick()
                    except Exception as exc:
                        core.errors["tasks"] = redact(str(exc))
                    if time.monotonic() - last_maintenance >= 60 and (
                        core.maintenance_job is None or core.maintenance_job.done()
                    ):
                        core.maintenance_job = core.maintenance.submit(core.maintain)
                        last_maintenance = time.monotonic()
                server.shutdown()
        finally:
            core.pool.shutdown(wait=True)
            core.maintenance.shutdown(wait=True)
            with contextlib.suppress(FileNotFoundError):
                config.socket.unlink()


if __name__ == "__main__":
    main()

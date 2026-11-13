"""The small ax surface. Data emits JSON; run and attach preserve program stdio."""

import argparse
import json
import os
import shlex
import sys
import time

from ax import __version__
from ax.client import request
from ax.config import load
from ax.providers import caller_context


def interval(value):
    number = int(value)
    if not 10 <= number <= 60:
        raise argparse.ArgumentTypeError("choose 10–60 minutes; supervision is mandatory")
    return number


def parser():
    p = argparse.ArgumentParser(
        prog="ax",
        description="Local search, handoffs, shared memories, supervised tasks and budgets. Structured data; run carries command stdio.",
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--caller", help="provider:session; normally inferred from the calling agent")
    commands = p.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run", help="run a background-owned command, attaching stdio by default"
    )
    run.add_argument("--detach", action="store_true")
    run.add_argument("--description", help="optional task purpose; defaults to the command")
    run.add_argument("--every", type=interval, default=10, metavar="MINUTES")
    run.add_argument("argv", nargs=argparse.REMAINDER)
    for name in ("attach", "detach"):
        action = commands.add_parser(name, help=name + " a running task without restarting it")
        action.add_argument("id")
    search = commands.add_parser("search", help="search conversations from both providers")
    search.add_argument("query")
    search.add_argument("--provider", choices=("claude", "codex"))
    search.add_argument("--project")
    search.add_argument("--limit", type=int, default=10)
    handoff = commands.add_parser(
        "handoff", help="prepare a sourced topic summary using Haiku or Luna"
    )
    handoff.add_argument("topic")
    memory = commands.add_parser("memory", help="sync shared memories across providers")
    memory.add_argument("action", choices=("sync",), nargs="?", default="sync")
    task = commands.add_parser(
        "task", help="register work, report numeric progress and consume events"
    )
    actions = task.add_subparsers(dest="action", required=True)
    watch = actions.add_parser("watch", help="supervise an existing process")
    watch.add_argument("purpose")
    watch.add_argument("--pid", type=int, required=True)
    watch.add_argument("--every", type=interval, default=10, metavar="MINUTES")
    create = actions.add_parser(
        "create", help="register externally executed work with reported progress"
    )
    create.add_argument("purpose")
    create.add_argument("--every", type=interval, default=10, metavar="MINUTES")
    listing = actions.add_parser("list", help="list active tasks")
    listing.add_argument("--all", action="store_true")
    show = actions.add_parser("show", help="inspect a task and its evidence")
    show.add_argument("id")
    update = actions.add_parser("update", help="report counters, stage or external completion")
    update.add_argument("id")
    update.add_argument("--done", type=float)
    update.add_argument("--total", type=float)
    update.add_argument("--unit")
    update.add_argument("--stage")
    update.add_argument("--status", choices=("running", "done", "failed"))
    update.add_argument("--every", type=interval, metavar="MINUTES")
    stop = actions.add_parser("stop", help="stop an ax-launched process")
    stop.add_argument("id")
    stream = actions.add_parser(
        "events", help="read durable events, optionally following numeric ticks"
    )
    stream.add_argument("id", nargs="?")
    stream.add_argument("--after", type=int, default=0)
    stream.add_argument("--follow", action="store_true")
    usage = commands.add_parser("usage", help="read provider allowance windows and projections")
    usage.add_argument(
        "--refresh",
        action="store_true",
        help="refresh Claude's zero-inference built-in usage cache",
    )
    budgets = commands.add_parser("budget", help="track spending, reservations and projections")
    actions = budgets.add_subparsers(dest="action", required=True)
    setting = actions.add_parser("set")
    setting.add_argument("name")
    setting.add_argument("amount", type=float)
    setting.add_argument("--unit", default="usd")
    showing = actions.add_parser("show")
    showing.add_argument("name", nargs="?")
    for name in ("add", "reserve"):
        action = actions.add_parser(name)
        action.add_argument("name")
        action.add_argument("amount", type=float)
    settle = actions.add_parser("settle")
    settle.add_argument("ticket")
    settle.add_argument("amount", type=float)
    release = actions.add_parser("release")
    release.add_argument("ticket")
    close = actions.add_parser("close")
    close.add_argument("name")
    daemon = commands.add_parser("daemon", help="control the local Unix-socket daemon")
    daemon.add_argument("action", choices=("start", "status", "stop"), nargs="?", default="status")
    return p


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main(argv=None):
    args = parser().parse_args(argv)
    values = vars(args).copy()
    config = load()
    try:
        context = {}
        try:
            context = caller_context(args.caller)
        except ValueError:
            if (
                args.caller
                or args.command in ("handoff", "run")
                or (args.command == "task" and args.action in ("create", "run", "watch"))
            ):
                raise
        values.update(context)
        if args.command == "run":
            command = args.argv
            command = command[1:] if command and command[0] == "--" else command
            if not command:
                raise ValueError("usage: ax run [--detach] -- COMMAND ARGS")
            environment = dict(os.environ)
            terminal = sys.stdin.isatty() and sys.stdout.isatty()
            if args.detach and not terminal:
                environment["AX_STDIN_CLOSED"] = "1"
            if terminal:
                size = os.get_terminal_size(sys.stdin.fileno())
                environment.update(COLUMNS=str(size.columns), LINES=str(size.lines))
            result = request(
                config,
                "task.create",
                {
                    **context,
                    "kind": "run",
                    "command": command,
                    "purpose": args.description or shlex.join(command),
                    "cwd": os.getcwd(),
                    "every": args.every,
                    "environment": environment,
                    "tty": terminal,
                },
            )
            if args.detach:
                emit({"id": result["id"], "detached": True})
                return 0
            from ax.attach import attach

            code, detached = attach(config, result["id"])
            if detached:
                emit({"id": result["id"], "detached": True})
            return code
        elif args.command in ("attach", "detach"):
            from ax.attach import attach, detach

            if args.command == "detach":
                emit(detach(config, args.id))
                return 0
            code, detached = attach(config, args.id)
            if detached:
                emit({"id": args.id, "detached": True})
            return code
        elif args.command == "daemon":
            operation = "daemon.status" if args.action == "start" else "daemon." + args.action
            result = request(config, operation, values, autostart=args.action == "start")
        elif args.command == "task":
            if args.action in ("create", "watch"):
                values["kind"] = {"create": "reported", "watch": "watch"}[args.action]
                values["cwd"] = os.getcwd()
                operation = "task.create"
            else:
                operation = "task." + args.action
            if args.action == "events" and args.follow:
                cursor = max(0, args.after)
                while True:
                    rows = request(config, "task.events", {**values, "after": cursor})
                    for row in rows:
                        emit(row)
                        cursor = row["seq"]
                    if len(rows) == 500:
                        continue
                    tasks = request(config, "task.list", values)
                    emit(
                        {
                            "type": "tick",
                            "seq": cursor,
                            "at": time.time(),
                            "tasks": [t for t in tasks if not args.id or t["id"] == args.id],
                        }
                    )
                    time.sleep(1)
            result = request(config, operation, values)
        elif args.command in ("memory", "budget"):
            result = request(config, args.command + "." + args.action, values)
        else:
            result = request(config, args.command, values)
        emit(result)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

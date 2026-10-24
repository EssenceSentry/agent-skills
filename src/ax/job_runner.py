"""The detached process behind `ax job run`: run one command, then record how it ended.

Usage: python -m ax.job_runner EVENTS_FILE LOG_FILE STDIN_FILE|- CWD -- CMD...

The command's output goes to LOG_FILE and it can report progress by appending
JSON lines to $AX_JOB_FILE. When it ends, one {"exit": code} line goes to the
events file. SIGTERM stops the command and is recorded the same way.
"""

import json
import os
import signal
import subprocess
import sys


def _record(events_file: str, line: dict) -> None:
    with open(events_file, "a") as f:
        f.write(json.dumps(line) + "\n")


def main(argv: list[str]) -> int:
    # Handle SIGTERM from the start, so a stop that lands before the command exists
    # still stops it and is recorded.
    child = None
    stop_requested = False

    def on_term(*_):
        nonlocal stop_requested
        stop_requested = True
        if child is not None:
            child.terminate()

    signal.signal(signal.SIGTERM, on_term)
    split = argv.index("--")
    events_file, log_file, stdin_file, cwd = argv[:split]
    command = argv[split + 1 :]
    env = {**os.environ, "AX_JOB_FILE": events_file}
    stdin = open(stdin_file, "rb") if stdin_file != "-" else subprocess.DEVNULL  # noqa: SIM115
    with open(log_file, "ab") as log:
        try:
            child = subprocess.Popen(
                command, cwd=cwd, env=env, stdin=stdin, stdout=log, stderr=subprocess.STDOUT
            )
        except FileNotFoundError:
            _record(events_file, {"exit": 127, "message": f"command not found: {command[0]}"})
            return 127
        except PermissionError:
            _record(events_file, {"exit": 126, "message": f"not allowed to run {command[0]}"})
            return 126
        finally:
            if stdin is not subprocess.DEVNULL:
                stdin.close()
        if stop_requested:
            child.terminate()
        code = child.wait()
    if code < 0:
        _record(events_file, {"exit": code, "message": f"stopped by signal {-code}"})
    else:
        _record(events_file, {"exit": code})
    return code


if __name__ == "__main__":
    main(sys.argv[1:])

"""What `ax job watch` can check: a file, a process, a SageMaker or a Seamless job, a
Runwatch notebook run, or a job of the auto-classifier Tools MCP.

Each source reads a job's `spec` and returns `Update`s for `ax.jobs`. AWS is
reached through the `aws` command line, so ax needs no boto3 and uses whatever
credentials the calling shell has; missing or expired ones become a check error,
never a failed job. Runwatch is read through its own `status` and `events`
commands, and the Tools MCP through the job.json files its workers keep.
"""

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from ax.jobs import Job, Update, normalize_status, number, read_lines

# Seconds between checks of one job; AWS calls are spaced out, local ones are free.
MIN_INTERVAL = {
    "file": 0, "pid": 0, "run": 0, "sagemaker": 20, "seamless": 20, "runwatch": 10, "tools": 0,
}  # fmt: skip
SAGEMAKER_TYPES = ("processing", "training", "transform")
SEAMLESS_PREFIX = "SEAMLESS_PROGRESS "
SEAMLESS_LOG_GROUP = "/aws/sagemaker/ProcessingJobs"

_OPTIONS = {
    "file": {"format", "done_key", "total_key", "status_key", "stage_key", "message_key", "done_when"},
    "pid": set(),
    "sagemaker": {"type", "region", "profile"},
    "seamless": {"region", "profile", "state_url", "log_group"},
    "runwatch": {"runwatch"},
    "tools": {"state_root"},
}  # fmt: skip
_SAGEMAKER_NAME = re.compile(r"[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}")
_SAGEMAKER_STATUS = {
    "InProgress": "running", "Stopping": "running", "Completed": "done",
    "Failed": "failed", "Stopped": "stopped",
}  # fmt: skip
_STATUS_FIELD = {
    "processing": "ProcessingJobStatus",
    "training": "TrainingJobStatus",
    "transform": "TransformJobStatus",
}
_CREDENTIAL_ERRORS = (
    "ExpiredToken", "Unable to locate credentials", "InvalidClientTokenId",
    "UnrecognizedClientException", "security token", "Token has expired", "SSO session",
)  # fmt: skip
_NOT_FOUND = ("Could not find", "ResourceNotFound", "does not exist")


class CheckError(RuntimeError):
    """A check could not tell the job's state right now; the last state stands."""


class AwsError(RuntimeError):
    """The aws command line failed; the message is its error output."""


def run_aws(args: list[str], *, region: str | None = None, profile: str | None = None) -> dict:
    cmd = ["aws", *args, "--output", "json"]
    if region:
        cmd += ["--region", region]
    if profile:
        cmd += ["--profile", profile]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise AwsError("the aws command line is not installed") from None
    except subprocess.TimeoutExpired:
        raise AwsError("aws took longer than 60 seconds to answer") from None
    if done.returncode != 0:
        raise AwsError((done.stderr or done.stdout).strip() or f"aws exited with {done.returncode}")
    return json.loads(done.stdout or "{}")


def http_get_json(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def process_start(pid: int) -> str | None:
    """When the process started, as `ps` prints it; None when ps can't tell."""
    try:
        done = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout.strip() or None) if done.returncode == 0 else None


def _process_state(pid: int) -> str | None:
    try:
        done = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A finished child that nobody has reaped yet still answers kill(0).
    return not (_process_state(pid) or "").startswith("Z")


def prepare(kind: str, ref: str, options: dict, cwd: str) -> tuple[str, dict]:
    """Check a watch request and turn it into the job's ref and spec."""
    options = {k: v for k, v in options.items() if v is not None}
    unknown = set(options) - _OPTIONS[kind]
    if unknown:
        names = ", ".join("--" + name.replace("_", "-") for name in sorted(unknown))
        raise ValueError(f"{names} doesn't apply to a {kind} job")
    return {
        "file": _prepare_file,
        "pid": _prepare_pid,
        "sagemaker": _prepare_sagemaker,
        "seamless": _prepare_seamless,
        "runwatch": _prepare_runwatch,
        "tools": _prepare_tools,
    }[kind](ref, options, cwd)


def default_key(kind: str, ref: str) -> str:
    if kind in ("sagemaker", "seamless"):
        return ref
    if kind == "pid":
        return f"pid-{ref}"
    if kind == "tools":
        return f"tools-{ref[:12]}"
    if kind == "runwatch":
        return f"runwatch-{Path(ref).name}"[:100]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(ref).stem).strip(".-_") or "file"
    return f"{stem[:40]}-{hashlib.sha1(ref.encode()).hexdigest()[:6]}"


def check(job: Job, now: datetime) -> list[Update]:
    return {
        "file": _check_file,
        "pid": _check_pid,
        "run": _check_run,
        "sagemaker": _check_sagemaker,
        "seamless": _check_seamless,
        "runwatch": _check_runwatch,
        "tools": _check_tools,
    }[job.kind](job)


# file


def _resolve(path: str, cwd: str) -> Path:
    found = Path(path).expanduser()
    return (found if found.is_absolute() else Path(cwd) / found).resolve()


def _prepare_file(ref, options, cwd):
    path = _resolve(ref, cwd)
    fmt = options.get("format") or ("jsonl" if path.suffix in (".jsonl", ".ndjson") else "json")
    if fmt not in ("json", "jsonl"):
        raise ValueError("--format must be json or jsonl")
    spec = {
        "path": str(path),
        "format": fmt,
        "offset": 0,
        **{f"{name}_key": options.get(f"{name}_key", name) for name in ("done", "total", "status", "stage", "message")},
        "done_when": str(_resolve(options["done_when"], cwd)) if options.get("done_when") else None,
    }  # fmt: skip
    return str(path), spec


def _dig(data, dotted: str):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _text(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _check_file(job: Job) -> list[Update]:
    spec = job.spec
    path = Path(spec["path"])
    updates = []
    if spec["format"] == "jsonl":
        updates, spec["offset"] = read_lines(path, spec.get("offset", 0))
    elif path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            raise CheckError(f"{path.name} is not valid JSON right now") from None
        if not isinstance(data, dict):
            raise CheckError(f"{path.name} does not hold a JSON object")
        updates.append(
            Update(
                done=number(_dig(data, spec["done_key"])),
                total=number(_dig(data, spec["total_key"])),
                status=normalize_status(_dig(data, spec["status_key"])),
                stage=_text(_dig(data, spec["stage_key"])),
                message=_text(_dig(data, spec["message_key"])),
            )
        )
    if spec.get("done_when") and Path(spec["done_when"]).exists():
        updates.append(Update(status="done"))
    return updates


# pid


def _prepare_pid(ref, options, cwd):
    if not ref.isdigit() or int(ref) <= 0:
        raise ValueError(f"{ref!r} is not a process id")
    pid = int(ref)
    if not process_alive(pid):
        raise ValueError(f"no process {pid} is running")
    return str(pid), {"pid": pid, "start": process_start(pid)}


def _check_pid(job: Job) -> list[Update]:
    pid = job.spec["pid"]
    if not process_alive(pid):
        return [Update(status="ended", message=f"process {pid} is gone; its exit code is unknown")]
    started = job.spec.get("start")
    current = process_start(pid) if started else None
    if current and current != started:
        return [Update(status="ended", message=f"process {pid} ended and its number was reused")]
    return []


_NUM = r"\d+(?:\.\d+)?[kMGTPE]?"
_COUNTS = re.compile(rf"({_NUM})/({_NUM}) \[[\d?]")
_COUNT = re.compile(rf"({_NUM})([A-Za-z_]*) \[[\d?]")
_RATE_UNIT = re.compile(rf",\s*(?:{_NUM}|\?)\s?([A-Za-z_]+)/s\]")
_DESC = re.compile(r"^\s*([^|]*?):\s+(?:\d+%\||\d)")
_SCALE = {"k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18}
_LOG_TAIL = 8192


def _count(text: str) -> float:
    if text[-1] in _SCALE:
        return float(text[:-1]) * _SCALE[text[-1]]
    return float(text)


def parse_bar(text: str) -> Update | None:
    """The latest tqdm-style bar in output text ("Scoring: 45%|… | 450/1000 [00:10<…]")."""
    for segment in reversed(re.split(r"[\r\n]", text)):
        counts = _COUNTS.search(segment)
        single = None if counts else _COUNT.search(segment)
        if not counts and not single:
            continue
        unit = _RATE_UNIT.search(segment)
        unit = unit.group(1) if unit else (single.group(2) if single else None)
        desc = _DESC.match(segment)
        return Update(
            done=_count((counts or single).group(1)),
            total=_count(counts.group(2)) if counts else None,
            unit=unit if unit and unit != "it" else None,
            stage=(desc.group(1).strip() or None) if desc else None,
        )
    return None


def _bar_progress(job: Job) -> list[Update]:
    """Progress from a bar in the command's output, unless the command reports its own."""
    if job.done is not None and not job.spec.get("bar_progress"):
        return []
    try:
        with open(job.spec["log"], "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - _LOG_TAIL))
            tail = f.read().decode("utf-8", "replace")
    except (OSError, KeyError):
        return []
    found = parse_bar(tail)
    if found is None:
        return []
    job.spec["bar_progress"] = True
    return [found]


def _check_run(job: Job) -> list[Update]:
    """Progress bars in the output, and the end of a runner killed before its exit line.

    The runner writes that line just before it exits, so lines that arrived after
    this refresh read the events file are read again before calling the job ended.
    """
    if job.spec.get("pid") is None or not _check_pid(job):
        return _bar_progress(job)
    late, job.offset = read_lines(Path(job.spec["events"]), job.offset)
    if any(update.status for update in late):
        return late
    return [
        *late,
        Update(status="ended", message="the runner was killed before the command finished"),
    ]


# sagemaker


def _aws_options(options) -> dict:
    region = (
        options.get("region")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    return {"region": region, "profile": options.get("profile")}


def _check_name(name: str) -> str:
    if not _SAGEMAKER_NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a SageMaker job name")
    return name


def _prepare_sagemaker(ref, options, cwd):
    type_ = options.get("type", "processing")
    if type_ not in SAGEMAKER_TYPES:
        raise ValueError(f"--type must be one of {', '.join(SAGEMAKER_TYPES)}")
    return ref, {"name": _check_name(ref), "type": type_, **_aws_options(options)}


def _aws_error(exc: AwsError, what: str) -> CheckError:
    text = str(exc)
    first = text.strip().splitlines()[-1][:300] if text.strip() else "no details"
    if any(marker in text for marker in _CREDENTIAL_ERRORS):
        return CheckError(f"AWS credentials are missing or expired: {first}")
    if "AccessDenied" in text:
        return CheckError(f"AWS denied the request; check the role: {first}")
    if any(marker in text for marker in _NOT_FOUND):
        return CheckError(f"SageMaker has no {what}")
    return CheckError(first)


def _describe(spec: dict, type_: str) -> dict:
    name = spec["name"]
    try:
        return run_aws(
            ["sagemaker", f"describe-{type_}-job", f"--{type_}-job-name", name],
            region=spec.get("region"),
            profile=spec.get("profile"),
        )
    except AwsError as exc:
        raise _aws_error(exc, f"{type_} job named {name}") from None


def _status_update(raw, *, secondary=None, message=None) -> Update:
    status = _SAGEMAKER_STATUS.get(raw)
    if status is None:
        raise CheckError(f"SageMaker reported an unexpected status {raw!r}")
    stage = "Stopping" if raw == "Stopping" else _text(secondary)
    return Update(status=status, stage=stage, message=_text(message))


def _check_sagemaker(job: Job) -> list[Update]:
    type_ = job.spec["type"]
    desc = _describe(job.spec, type_)
    return [
        _status_update(
            desc.get(_STATUS_FIELD[type_]),
            secondary=desc.get("SecondaryStatus"),
            message=desc.get("FailureReason") or desc.get("ExitMessage"),
        )
    ]


# seamless


def _prepare_seamless(ref, options, cwd):
    url = options.get("state_url")
    if url and not url.startswith(("http://", "https://")):
        raise ValueError("--state-url must be an http or https address")
    spec = {
        "name": _check_name(ref),
        **_aws_options(options),
        "state_url": url,
        "log_group": options.get("log_group", SEAMLESS_LOG_GROUP),
        "logs": {"cursor_ms": None, "boundary_ids": [], "active": None, "seen": [], "workers": {}},
    }
    return ref, spec


def _from_dashboard(state: dict) -> list[Update]:
    totals = state.get("totals") if isinstance(state.get("totals"), dict) else {}
    streams = state.get("progress") if isinstance(state.get("progress"), list) else []
    stage = streams[0].get("desc") if streams and isinstance(streams[0], dict) else None
    updates = [
        Update(
            done=number(totals.get("current")),
            total=number(totals.get("total")),
            stage=_text(stage),
        )
    ]
    if state.get("status") in _SAGEMAKER_STATUS:
        updates.append(_status_update(state["status"], message=state.get("failure_reason")))
    return updates


def _progress_payload(message: str) -> dict | None:
    at = message.find(SEAMLESS_PREFIX)
    if at < 0:
        return None
    try:
        payload = json.loads(message[at + len(SEAMLESS_PREFIX) :])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _read_seamless_logs(spec: dict) -> tuple[dict, Update | None]:
    """New progress lines from CloudWatch, folded the way Seamless's own dashboard does.

    Workers report one count each; the job's progress is their sum for the active
    stream. A stream seen before and then replaced is ignored if it reappears.
    """
    logs = copy.deepcopy(spec["logs"])
    args = [
        "logs", "filter-log-events",
        "--log-group-name", spec["log_group"],
        "--log-stream-name-prefix", spec["name"],
        "--filter-pattern", '"SEAMLESS_PROGRESS"',
    ]  # fmt: skip
    if logs["cursor_ms"] is not None:
        args += ["--start-time", str(logs["cursor_ms"])]
    try:
        page = run_aws(args, region=spec.get("region"), profile=spec.get("profile"))
    except AwsError as exc:
        if "ResourceNotFound" in str(exc):  # no log stream yet: the job is still starting
            return logs, None
        raise _aws_error(exc, f"log group {spec['log_group']}") from None
    for event in page.get("events") or []:
        event_id, ts = str(event.get("eventId") or ""), event.get("timestamp")
        if isinstance(ts, int):
            if (
                logs["cursor_ms"] is not None
                and ts == logs["cursor_ms"]
                and event_id in logs["boundary_ids"]
            ):
                continue
            if logs["cursor_ms"] is None or ts > logs["cursor_ms"]:
                logs["cursor_ms"], logs["boundary_ids"] = ts, [event_id]
            elif ts == logs["cursor_ms"]:
                logs["boundary_ids"].append(event_id)
        payload = _progress_payload(str(event.get("message") or ""))
        if payload:
            _fold_progress(logs, payload)
    workers = logs["workers"].values()
    if not workers:
        return logs, None
    totals = [w["total"] for w in workers]
    total = sum(totals) if all(t is not None for t in totals) else None
    stage = next(iter(workers))["desc"]
    return logs, Update(done=sum(w["current"] for w in workers), total=total, stage=stage)


def _fold_progress(logs: dict, payload: dict) -> None:
    stream = str(payload.get("progress_id") or payload.get("desc") or "items")
    if stream != logs["active"]:
        if stream in logs["seen"]:
            return
        logs["active"] = stream
        logs["seen"].append(stream)
        logs["workers"] = {}
    rank = payload.get("rank") if isinstance(payload.get("rank"), int) else 0
    host = payload.get("current_host") or payload.get("hostname") or ""
    key = f"{rank}:{host}"
    elapsed = payload.get("elapsed_seconds")
    prior = logs["workers"].get(key)
    stale = (
        prior
        and isinstance(elapsed, int | float)
        and isinstance(prior.get("elapsed"), int | float)
        and elapsed < prior["elapsed"]
    )
    if stale:
        return  # an older line arriving late
    total = payload.get("total")
    logs["workers"][key] = {
        "current": max(0, int(number(payload.get("current")) or 0)),
        "total": int(total) if number(total) is not None else None,
        "desc": str(payload.get("desc") or stream),
        "elapsed": elapsed,
    }


def _check_seamless(job: Job) -> list[Update]:
    spec = job.spec
    if spec.get("state_url"):
        try:
            state = http_get_json(spec["state_url"])
        except (OSError, ValueError):
            state = None  # the dashboard is gone; fall back to SageMaker and CloudWatch
        if isinstance(state, dict):
            return _from_dashboard(state)
    logs, progress = _read_seamless_logs(spec)
    desc = _describe(spec, "processing")
    status = _status_update(
        desc.get(_STATUS_FIELD["processing"]),
        message=desc.get("FailureReason") or desc.get("ExitMessage"),
    )
    spec["logs"] = logs  # only after every call succeeded, so no progress is skipped
    return [u for u in (progress, status) if u]


# runwatch

# A paused run waits for a repair, so it ends the ax job and wakes whoever waits on it.
_RUNWATCH_STATUS = {"succeeded": "done", "failed": "failed", "cancelled": "stopped"}
_RUNWATCH_ACTIVE = {"running", "restarting", "finalizing", "waiting_external"}
# A run still "created" with no controller this long after it was made never started:
# the command that launched it failed (a taken port, a bad setting) after creating it.
_RUNWATCH_START_GRACE = 120.0


def _runwatch_binary(options: dict, cwd: str) -> str:
    given = options.get("runwatch") or os.environ.get("AX_RUNWATCH") or shutil.which("runwatch")
    path = _resolve(given, cwd) if given else None
    if path is None or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(
            "no runwatch command: put it on PATH, set AX_RUNWATCH, or pass --runwatch PATH"
        )
    return str(path)


def _prepare_runwatch(ref, options, cwd):
    run = _resolve(ref, cwd)
    if not (run / "runwatch.sqlite3").exists():
        raise ValueError(f"{run} is not a Runwatch run folder (it has no runwatch.sqlite3)")
    return str(run), {"run": str(run), "binary": _runwatch_binary(options, cwd)}


def _runwatch(job: Job, command: str) -> str:
    try:
        done = subprocess.run(
            [job.spec["binary"], command, job.spec["run"], "--json"],
            capture_output=True, text=True, timeout=60,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckError(f"runwatch {command} failed: {exc}") from None
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        raise CheckError(f"runwatch {command}: {lines[-1] if lines else done.returncode}")
    return done.stdout


def _runwatch_bar(job: Job, cell: int) -> tuple | None:
    """The newest progress bar the current cell drew, from `runwatch events`."""
    found = None
    for line in _runwatch(job, "events").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "notebook.progress":
            continue
        data = event.get("data") or {}
        if data.get("cell_index") == cell:
            found = (number(data.get("completed")), number(data.get("total")), data.get("unit"))
    return found


def _check_runwatch(job: Job) -> list[Update]:
    try:
        state = json.loads(_runwatch(job, "status"))
        run = state["run"]
    except (ValueError, KeyError, TypeError):
        raise CheckError("runwatch status gave no run state") from None
    raw, message = run.get("status"), _text(run.get("message"))
    if raw == "paused":
        cell = run.get("failed_cell_index")
        where = f" at cell {cell}" if cell is not None else ""
        reason = message or "it needs attention"
        return [
            Update(
                status="failed",
                message=f"paused{where}: {reason}. Repair it, run `runwatch resume "
                f"{job.spec['run']}`, then watch it again",
            )
        ]
    if raw in _RUNWATCH_STATUS:
        return [Update(status=_RUNWATCH_STATUS[raw], message=message)]
    if raw == "created" and not state.get("controller_live"):
        made = run.get("created_at") or job.created
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(made)).total_seconds()
        except (TypeError, ValueError):
            age = 0.0
        if age > _RUNWATCH_START_GRACE:
            return [
                Update(
                    status="failed",
                    message=f"never started: Runwatch created the run {round(age / 60)} min "
                    "ago, but no controller is running it. Read the output of the command "
                    "that launched it (a taken port, a bad setting), then launch it again",
                )
            ]
    if raw in _RUNWATCH_ACTIVE and not state.get("controller_live"):
        raise CheckError(
            f"Runwatch's controller is not running; `runwatch resume {job.spec['run']}` "
            "restarts the run"
        )
    cell = run.get("current_cell_index")
    update = Update(stage=f"cell {cell}" if cell is not None else raw, message=message)
    bar = _runwatch_bar(job, cell) if cell is not None else None
    if bar:
        update.done, update.total, update.unit = bar
    return [update]


# tools: jobs of the auto-classifier Tools MCP

_TOOLS_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TOOLS_STATUS = {
    "starting": "running", "running": "running", "cancelling": "running",
    "succeeded": "done", "succeeded_with_errors": "done", "failed": "failed",
    "cancelled": "stopped", "interrupted": "ended",
}  # fmt: skip


def tools_state_root() -> Path:
    """Where the Tools MCP keeps its jobs (platformdirs' user state folder)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "auto-classifier" / "tools-mcp"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "auto-classifier" / "tools-mcp"


def _prepare_tools(ref, options, cwd):
    if not _TOOLS_ID.fullmatch(ref):
        raise ValueError("a Tools MCP job id uses only letters, digits, '-' and '_'")
    given = options.get("state_root")
    root = _resolve(given, cwd) if given else tools_state_root()
    path = root / "jobs" / ref / "job.json"
    if not path.exists():
        raise ValueError(f"no Tools MCP job {ref} under {root}")
    return ref, {"path": str(path)}


def _check_tools(job: Job) -> list[Update]:
    """The job as its worker last wrote it. Snowflake jobs move only when the MCP refreshes them."""
    try:
        record = json.loads(Path(job.spec["path"]).read_text())
    except FileNotFoundError:
        raise CheckError("the Tools MCP no longer has this job") from None
    except (OSError, ValueError):
        raise CheckError("the job's job.json is not readable right now") from None
    raw = record.get("status")
    status = _TOOLS_STATUS.get(raw)
    if status is None:
        raise CheckError(f"the Tools MCP reported an unknown status {raw!r}")
    if raw == "succeeded_with_errors":
        message = "succeeded, but some rows failed; tools_get_rows shows them"
    elif raw == "interrupted":
        message = "interrupted; tools_resume_job can resume it"
    else:
        message = _text(str(record["error"])[:300]) if record.get("error") else None
    return [
        Update(
            status=status,
            stage=_text(record.get("stage")),
            done=number(record.get("completed")),
            total=number(record.get("total")),
            message=message,
        )
    ]

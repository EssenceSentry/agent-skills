"""A demo of everything a session page shows, in a home of its own.

`ax demo` writes five sessions whose transcripts hold every kind of message, link,
picture, question and file change; jobs that report to them, one a Runwatch notebook
answered by a stand-in `runwatch`; and a project folder for their links to open. It then
serves them like `ax serve`, with ax holding each session, so the parts that only exist
live show too: a waiting question and approvals, a reply streaming in, a goal, the plan,
the model picker. Nothing reaches a model, and nothing touches the real `~/.claude`,
`~/.codex` or ax's own data.

In VS Code, open the demo's project folder in a window of its own: its settings point
the extension at the demo's server.
"""

import base64
import difflib
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ax import chat, jobs, live_sessions, usage
from ax.config import Config, load
from ax.sources import asks

ROOT = Path("~/.cache/ax-demo").expanduser()
PORT = 8798
CLAUDE_ID = "de300000-0000-4000-8000-00000000c1a0"
PLAN_ID = "de300000-0000-4000-8000-0000000091a0"
REBUILD_ID = "de300000-0000-4000-8000-0000000b01d0"
TESTS_ID = "de300000-0000-4000-8000-000000007e57"
CODEX_ID = "019a2b3c-de30-7000-8000-0000000c0de0"
_listing = live_sessions.listing


@dataclass
class Demo:
    root: Path
    config: Config
    project: Path
    claude: str = CLAUDE_ID
    plan: str = PLAN_ID
    rebuild: str = REBUILD_ID
    tests: str = TESTS_ID
    codex: str = CODEX_ID


# Pictures, drawn here so the demo needs no files of its own

BLUE, ORANGE, PURPLE = (54, 101, 228), (176, 74, 36), (117, 82, 219)
PAPER, INK, LINE = (248, 248, 250), (40, 42, 54), (214, 216, 224)


def _png(width: int, height: int, paint) -> bytes:
    rows = b"".join(
        b"\x00" + bytes(c for x in range(width) for c in paint(x, y)) for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))  # fmt: skip


def _chart() -> bytes:
    """Four quarters as bars on a light ground, the third highest."""
    bars = [(70, 150), (170, 190), (270, 110), (370, 210)]  # (left, top)

    def paint(x, y):
        if y >= 250 and y <= 252 and 40 <= x <= 440:
            return INK
        for left, top in bars:
            if left <= x < left + 60 and top <= y < 250:
                return ORANGE if left == 270 else BLUE
        return LINE if y in (110, 150, 190, 230) and 40 <= x <= 440 else PAPER

    return _png(480, 300, paint)


def _screenshot() -> bytes:
    """A window: a title bar, a sidebar and a panel of rows."""

    def paint(x, y):
        if y < 28:
            return (225, 227, 233) if not (12 <= x <= 20 and 10 <= y <= 18) else ORANGE
        if x < 150:
            return (236, 238, 243) if (y - 40) % 32 > 6 else (205, 210, 225)
        if 180 <= x <= 610 and 60 <= y <= 120:
            return BLUE
        if 180 <= x <= 610 and y > 140 and (y - 140) % 36 < 22:
            return (232, 234, 240) if x < 560 else PURPLE
        return PAPER

    return _png(640, 400, paint)


def _photo() -> bytes:
    """A soft gradient from purple to orange."""

    def paint(x, y):
        t = (x / 399 + y / 259) / 2
        return tuple(round(a + (b - a) * t) for a, b in zip(PURPLE, ORANGE, strict=True))

    return _png(400, 260, paint)


def _pdf(text: str) -> bytes:
    stream = f"BT /F1 28 Tf 72 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# The project the sessions work in

APP_BEFORE = '''"""The dashboard's chart: rows in, one figure out."""

import csv
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    """The results, one row per quarter and region."""
    with path.open() as f:
        return list(csv.DictReader(f))


def view_rate(views: int, impressions: int) -> float:
    """Views per impression; zero when nothing was shown."""
    return views / impressions if impressions else 0.0


def totals(rows: list[dict]) -> dict:
    """Impressions, views and spend over every row."""
    return {
        "impressions": sum(int(r["impressions"]) for r in rows),
        "views": sum(int(r["views"]) for r in rows),
        "spend": sum(float(r["spend"]) for r in rows),
    }


def chart(rows: list[dict]) -> dict:
    return {"kind": "bars", "colour": "#3665e4", "rows": rows}
'''
APP_AFTER = APP_BEFORE.replace(
    """def chart(rows: list[dict]) -> dict:
    return {"kind": "bars", "colour": "#3665e4", "rows": rows}
""",
    '''def chart(rows: list[dict], *, kind: str = "bars", quarters=None) -> dict:
    """The figure for the chosen quarters, its colours from the theme."""
    shown = [r for r in rows if quarters is None or r["quarter"] in quarters]
    return {"kind": kind, "colour": "var(--series-1)", "rows": shown}
''',
)
REPORT_BEFORE = '''"""The quarterly report's numbers."""


def cost_per_view(spend: float, views: int) -> float:
    return spend / views


def summary(totals: dict) -> str:
    return f"{totals['views']} views for ${totals['spend']:.0f}"
'''
REPORT_AFTER = REPORT_BEFORE.replace(
    """def cost_per_view(spend: float, views: int) -> float:
    return spend / views
""",
    '''def cost_per_view(spend: float, views: int) -> float:
    """Spend per view; nothing when there were no views."""
    return spend / views if views else float("nan")
''',
)
RESULTS = """quarter,region,impressions,views,spend
Q1,North America,1204551,402118,8444
Q2,Europe,980210,301442,7536
Q3,Latin America,1511906,588032,9997
Q4,Asia Pacific,765330,210476,6104
"""
STEPS = ["Load data", "Features", "Split", "Baseline", "Tune", "Train", "Calibrate",
         "Train the view-rate model", "Evaluate", "Export"]  # fmt: skip
NOTEBOOK = {
    "cells": [
        {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
         "source": [f"# {step}\n", f"print({step!r})"]}
        for step in STEPS
    ],
    "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
    "nbformat": 4,
    "nbformat_minor": 5,
}  # fmt: skip


def _project(project: Path, port: int) -> None:
    files = {
        "README.md": "# Demo dashboard\n\nThe project ax's demo sessions work in.\n",
        "src/demo/app.py": APP_BEFORE,
        "src/demo/report.py": REPORT_BEFORE,
        "data/results.csv": RESULTS,
        "docs/architecture.md": "# Architecture\n\nRows go in, one chart comes out.\n",
        "notebook.ipynb": json.dumps(NOTEBOOK, indent=1) + "\n",
        ".vscode/settings.json": json.dumps({"ax.server": f"http://127.0.0.1:{port}"}, indent=2)
        + "\n",
    }
    for name, text in files.items():
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_text(text)
    (project / "assets").mkdir(exist_ok=True)
    (project / "assets/chart.png").write_bytes(_chart())
    (project / "docs/report.pdf").write_bytes(_pdf("Demo report: four quarters"))
    with zipfile.ZipFile(project / "data/archive.zip", "w") as archive:
        archive.writestr("results.csv", RESULTS)
    git = ["git", "-C", str(project), "-c", "user.name=ax demo", "-c", "user.email=demo@localhost"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "The demo project as it began"], check=True)
    # What the sessions' latest turns changed, as they left it.
    (project / "src/demo/app.py").write_text(APP_AFTER)
    (project / "src/demo/report.py").write_text(REPORT_AFTER)
    (project / "docs/notes.md").write_text(
        "# Notes\n\nThe chart now takes its colours from the theme.\n"
    )


# Claude's transcripts

ANSWER = r'''## What the dashboard shows

The screenshot has three panels; the chart in the middle is the one to change. Its data
comes from `src/demo/app.py:8`, and the export is [the report](docs/report.pdf).

### Every kind of link

- A web page: [VS Code's webview guide](https://code.visualstudio.com/api/extension-guides/webview)
- A file at a line: [`load_rows`](src/demo/app.py#L8), or in code: `src/demo/app.py:14`
- A range of lines: [the totals](src/demo/app.py#L19-L25)
- An absolute path: `{project}/README.md`
- Under home: `{home}/data/results.csv`
- A folder, for Finder: [docs/](docs/)
- A picture, for VS Code's viewer: [the chart](assets/chart.png)
- A PDF: `docs/report.pdf`
- A notebook: [notebook.ipynb](notebook.ipynb)
- A file for its own app: [data/archive.zip](data/archive.zip)
- A job's page in ax: [demo-scoring](/jobs/demo-scoring/)

### The numbers

| Quarter | Region | Impressions | Views | View rate | CPV | Spend | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Q1 | North America | 1,204,551 | 402,118 | 33.4% | $0.021 | $8,444 | Launch flight, two creatives |
| Q2 | Europe | 980,210 | 301,442 | 30.8% | $0.025 | $7,536 | Mid-flight optimisation moved budget to mobile |
| Q3 | Latin America | 1,511,906 | 588,032 | 38.9% | $0.017 | $9,997 | Best view rate of the year |
| Q4 | Asia Pacific | 765,330 | 210,476 | 27.5% | $0.029 | $6,104 | Holiday competition raised prices |

### The model

The view rate is \(v = \frac{\text{views}}{\text{impressions}}\), and the cost per view
follows from spend over the year:

\[
\mathrm{CPV} = \frac{S}{V} = \frac{\sum_q S_q}{\sum_q V_q}
\]

Single dollars stay text, so $8,444 and $7,536 read as money. With a
\(\mathrm{Beta}(\alpha, \beta)\) prior, each region's rate shrinks toward the mean:

$$
\hat v_r = \frac{\alpha + V_r}{\alpha + \beta + I_r}
$$

### Code

```python
def view_rate(views: int, impressions: int) -> float:
    """Views per impression; zero when nothing was shown."""
    return views / impressions if impressions else 0.0
```

```bash
uv run pytest -q tests/test_app.py
```

> The Q4 drop is seasonal, not a creative problem.

1. Read the rows
2. Group them by quarter
   - Q3 leads on view rate
   - Q4 trails on cost
3. Chart them

**Bold**, *italic*, ~~struck~~, and `inline code`.
'''
LIVE_ASK = {"questions": [
    {"question": "Which chart type should the export use?", "header": "Export chart",
     "multiSelect": False,
     "options": [{"label": "Bars", "description": "Matches the dashboard"},
                 {"label": "Lines", "description": "Shows the trend"}]},
    {"question": "Which quarters go in the export?", "header": "Quarters", "multiSelect": True,
     "options": [{"label": q, "description": ""} for q in ("Q1", "Q2", "Q3", "Q4")]},
]}  # fmt: skip


def _home(path: str) -> str:
    """A path as written from home, `~/…`, when it is under it."""
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home + "/") else path


class _Clock:
    def __init__(self, start: datetime):
        self.at = start

    def __call__(self, seconds: float = 20) -> str:
        self.at += timedelta(seconds=seconds)
        return self.at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _claude_records(sid: str, cwd: str, clock: _Clock) -> tuple[list[dict], str]:
    """The main Claude session, and the uuid of its latest prompt."""
    records: list[dict] = []
    count = [0]

    def add(kind: str, content, **extra) -> dict:
        count[0] += 1
        record = {"type": kind, "uuid": f"demo-{count[0]}", "timestamp": clock(),
                  "sessionId": sid, "cwd": cwd,
                  "message": {"role": kind, "content": content}, **extra}  # fmt: skip
        records.append(record)
        return record

    def tool(name: str, call: str, given: dict) -> None:
        add("assistant", [{"type": "tool_use", "id": call, "name": name, "input": given}])

    def result(call: str, content, *, error=False, **extra) -> None:
        block = {"type": "tool_result", "tool_use_id": call, "content": content}
        add("user", [block | ({"is_error": True} if error else {})], **extra)

    records.append({"type": "custom-title", "customTitle": "Dashboard chart review",
                    "sessionId": sid})  # fmt: skip
    # The first turn: a pasted picture, tools, a screenshot, and an answer with everything.
    add("user", [{"type": "text", "text": "Here's the dashboard. What does the chart show, "
                  "and where does its data come from?"},
                 {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                              "data": _b64(_photo())}}])  # fmt: skip
    add("assistant", [{"type": "text", "text": "I'll read the chart's code, then look at the "
                       "page itself."}])  # fmt: skip
    tool("Read", "toolu_read", {"file_path": f"{cwd}/src/demo/app.py"})
    result("toolu_read", APP_BEFORE)
    tool("Bash", "toolu_rows", {"command": "wc -l data/results.csv",
                                "description": "Count the result rows"})  # fmt: skip
    result("toolu_rows", "5 data/results.csv")
    tool(
        "mcp__Claude_Browser__computer",
        "toolu_shot",
        {"action": "screenshot", "action_summary": "Takes a screenshot of the dashboard"},
    )
    result("toolu_shot", [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                       "data": _b64(_screenshot())}}])  # fmt: skip
    tool(
        "mcp__Claude_Browser__computer",
        "toolu_chart",
        {"action": "zoom", "action_summary": "Zooms into the chart"},
    )
    result("toolu_chart", [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": _b64(_chart())}}])  # fmt: skip
    answer = ANSWER.replace("{project}", cwd).replace("{home}", _home(cwd))
    add("assistant", [{"type": "text", "text": answer}])
    # The second turn: questions, answered with options, with words, and declined.
    add("user", "Make the chart configurable.")
    first = {"questions": [
        {"question": "Which chart type?", "header": "Chart", "multiSelect": False,
         "options": [{"label": "Bars (Recommended)", "description": "As it is now"},
                     {"label": "Lines", "description": "Better for a trend over quarters"},
                     {"label": "Area", "description": "Lines with the share filled in"}]},
        {"question": "Which quarters should it show by default?", "header": "Quarters",
         "multiSelect": True,
         "options": [{"label": "Q1", "description": ""}, {"label": "Q2", "description": ""},
                     {"label": "Q3", "description": ""}, {"label": "Q4", "description": ""}]},
    ]}  # fmt: skip
    tool("AskUserQuestion", "toolu_ask1", first)
    result("toolu_ask1", 'Your questions have been answered: "Which chart type?"="Something '
           'else entirely", "Which quarters should it show by default?"="Q1, Q3".',
           toolUseResult={**first, "answers": {"Which chart type?": "Something else entirely",
                                               "Which quarters should it show by default?": "Q1,Q3"}})  # fmt: skip
    second = {"questions": [{"question": "Should the export follow the chart's settings?",
                             "header": "Export", "multiSelect": False,
                             "options": [{"label": "Yes", "description": "One source of truth"},
                                         {"label": "No", "description": "Keep it fixed"}]}]}  # fmt: skip
    tool("AskUserQuestion", "toolu_ask2", second)
    result("toolu_ask2", "The user declined to answer.", error=True)
    third = {"questions": [{"question": "Where should the colours come from?", "header": "Colours",
                            "multiSelect": False,
                            "options": [{"label": "The theme (Recommended)",
                                         "description": "`var(--series-1)` and on, in both modes"},
                                        {"label": "A fixed list", "description": "Hex values"}]}]}  # fmt: skip
    tool("AskUserQuestion", "toolu_ask3", third)
    result("toolu_ask3", "answered", toolUseResult={**third, "answers": {
        "Where should the colours come from?": "The theme (Recommended)"}})  # fmt: skip
    add("assistant", [{"type": "text", "text": "You'd rather choose the kind each time, so "
                       "it becomes a setting with bars as the default; Q1 and Q3 show first, "
                       "and the colours come from the theme. The export stays as it is."}])  # fmt: skip
    # The latest turn: a task list, edits, tests, and a question it waits on.
    prompt = add("user", "Go ahead and build it.")
    plan = [{"content": "Read the chart code", "status": "completed"},
            {"content": "Take the kind and quarters as settings", "status": "in_progress"},
            {"content": "Run the tests", "status": "pending"}]  # fmt: skip
    tool("mcp__ccd_turn__update_plan", "toolu_plan", {"items": plan, "scope": "continuation"})
    result("toolu_plan", "Plan shown (3 steps).")
    tool("Edit", "toolu_edit", {"file_path": f"{cwd}/src/demo/app.py",
                                "old_string": APP_BEFORE.split("def chart", 1)[1],
                                "new_string": APP_AFTER.split("def chart", 1)[1]})  # fmt: skip
    result("toolu_edit", "The file has been updated.")
    tool("Write", "toolu_write", {"file_path": f"{cwd}/docs/notes.md",
                                  "content": "# Notes\n\nThe chart now takes its colours from the theme.\n"})  # fmt: skip
    result("toolu_write", "File created.")
    add("assistant", [{"type": "text", "text": "The chart takes its kind and quarters now. "
                       "Running the tests."}])  # fmt: skip
    tool("Bash", "toolu_tests", {"command": "uv run pytest -q", "description": "Run the tests"})
    result("toolu_tests", "12 passed in 0.41s")
    tool("AskUserQuestion", "toolu_live", LIVE_ASK)  # answered live, through ax
    return records, prompt["uuid"]


PLAN_TEXT = """## Plan: themed charts

1. Read the chart's colours from `var(--series-1)` onward, so dark mode follows.
2. Fold any series past the last slot into "Other".
3. Add a test that renders the chart in both modes.

Touches `src/demo/app.py` only."""


def _brief(sid: str, cwd: str, clock: _Clock, title: str, prompt: str, said: str,
           *tools: tuple[str, str, dict]) -> list[dict]:  # fmt: skip
    """A short session: a title, a prompt, a reply, and tool calls with no result yet."""
    base = {"sessionId": sid, "cwd": cwd}
    records = [
        {"type": "custom-title", "customTitle": title, "sessionId": sid},
        {**base, "type": "user", "uuid": f"{sid[-4:]}-1", "timestamp": clock(),
         "message": {"role": "user", "content": prompt}},
        {**base, "type": "assistant", "uuid": f"{sid[-4:]}-2", "timestamp": clock(),
         "message": {"role": "assistant", "content": [{"type": "text", "text": said}]}},
    ]  # fmt: skip
    for n, (name, call, given) in enumerate(tools, 3):
        records.append({**base, "type": "assistant", "uuid": f"{sid[-4:]}-{n}", "timestamp": clock(),
                        "message": {"role": "assistant", "content": [
                            {"type": "tool_use", "id": call, "name": name, "input": given}]}})  # fmt: skip
    return records


REBUILD = {"command": "rm -rf build && npm run build", "description": "Rebuild the dashboard"}
SUITE_PLAN = [{"content": "Find the suite's command", "status": "completed"},
              {"content": "Run the whole suite", "status": "in_progress"},
              {"content": "Read what fails", "status": "pending"},
              {"content": "Say what to fix first", "status": "pending"}]  # fmt: skip


# Codex's thread


def _diff(before: str, after: str, path: str) -> str:
    return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                          f"a/{path}", f"b/{path}", lineterm=""))  # fmt: skip


def _codex_records(tid: str, cwd: str, clock: _Clock) -> list[dict]:
    records: list[dict] = [{"timestamp": clock(), "type": "session_meta", "payload": {
        "id": tid, "timestamp": clock(0), "cwd": cwd, "originator": "codex_vscode",
        "cli_version": "0.163.0", "source": "vscode"}}]  # fmt: skip

    def item(payload: dict) -> None:
        records.append({"timestamp": clock(), "type": "response_item", "payload": payload})

    def event(payload: dict) -> None:
        records.append({"timestamp": clock(0), "type": "event_msg", "payload": payload})

    def user(*parts) -> None:
        event(
            {"type": "user_message", "message": next((p["text"] for p in parts if "text" in p), "")}
        )
        item({"type": "message", "role": "user", "content": list(parts)})

    def said(text: str) -> None:
        item(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        )

    def call(name: str, call_id: str, arguments: dict) -> None:
        item({"type": "function_call", "name": name, "call_id": call_id,
              "arguments": json.dumps(arguments)})  # fmt: skip

    def output(call_id: str, value) -> None:
        item({"type": "function_call_output", "call_id": call_id, "output": json.dumps(value)})

    event({"type": "task_started"})
    user(
        {"type": "input_text", "text": "Check the report's numbers against this export."},
        {"type": "input_image", "image_url": f"data:image/png;base64,{_b64(_chart())}"},
    )
    said("I'll read the report code and the results file first.")
    item({"type": "custom_tool_call", "name": "exec", "call_id": "exec_1",
          "input": 'text(await tools.exec_command({cmd:"cat src/demo/report.py"}));'})  # fmt: skip
    item({"type": "custom_tool_call_output", "call_id": "exec_1", "output": REPORT_BEFORE})
    call("request_user_input", "ask_scope", {"questions": [{
        "id": "scope", "header": "Scope", "question": "Which numbers should I check?",
        "options": [{"label": "Totals and CPV (Recommended)", "description": "What the report prints"},
                    {"label": "Every row", "description": "Slower, finds row-level slips"}]}]})  # fmt: skip
    output("ask_scope", {"answers": {"scope": {"answers": ["Totals and CPV (Recommended)"]}}})
    said("The totals match the export. Cost per view divides by views without a guard:\n\n"
         "| Quarter | Views | CPV |\n| --- | ---: | ---: |\n| Q3 | 588,032 | $0.017 |\n"
         "| Q4 | 210,476 | $0.029 |\n\nSee `src/demo/report.py:4`.")  # fmt: skip
    call(
        "request_user_input_async",
        "ask_guard",
        {
            "questions": [
                {
                    "title": "May I add a guard for zero views?",
                    "options": ["Add the guard", "Leave it"],
                }
            ]
        },
    )
    output("ask_guard", {"accepted": True})
    reply = asks.reply_message(
        "ask_guard", ["May I add a guard for zero views?"], [["Add the guard"]]
    )
    event({"type": "task_complete"})
    # The latest turn: an edit, then a question still waiting.
    event({"type": "task_started"})
    user({"type": "input_text", "text": reply})
    said("Adding the guard to `cost_per_view`.")
    path = f"{cwd}/src/demo/report.py"
    event({"type": "item_completed", "item": {"type": "FileChange", "status": "completed", "changes": {
        path: {"type": "update", "unified_diff": _diff(REPORT_BEFORE, REPORT_AFTER, "src/demo/report.py")}}}})  # fmt: skip
    said("Done: a quarter with no views now reports no cost per view instead of failing.")
    call("request_user_input_async", "ask_ship", {"questions": [
        {"title": "Should I also round the CPV to three decimals in the summary?",
         "options": ["Round it", "Keep full precision"]}]})  # fmt: skip
    output("ask_ship", {"accepted": True})
    return records


# Jobs


RUNWATCH = '''#!{python}
"""A stand-in for `runwatch`, answering for the demo's one run."""
import json, sys

command = sys.argv[1] if len(sys.argv) > 1 else ""
labels = {labels!r}
cells = [{{"cell_index": i, "label": label,
          "status": "succeeded" if i < 7 else "running" if i == 7 else "pending"}}
         for i, label in enumerate(labels)]
run = {{"status": "running", "current_cell_index": 7, "message": None}}
if command == "status":
    print(json.dumps({{"run": run, "controller_live": True}}))
elif command == "context":
    print(json.dumps({{"run": run, "cells": cells, "source_path": {notebook!r}, "resources": [
        {{"display_label": "view-rate-train-2026-10-27", "provider": "aws",
          "resource_type": "sagemaker training job", "status": "InProgress", "terminal": False}}]}}))
elif command == "events":
    print(json.dumps({{"type": "notebook.progress",
                      "data": {{"cell_index": 7, "completed": 34, "total": 120, "unit": "batches"}}}}))
'''


def _jobs(demo: Demo, clock: _Clock) -> None:
    config, cwd = demo.config, str(demo.project)
    claude, codex = {"CLAUDE_CODE_SESSION_ID": demo.claude}, {"CODEX_THREAD_ID": demo.codex}

    def feed(key: str, lines: list[dict]) -> None:
        with jobs.events_path(config, key).open("a") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        jobs.refresh(config, key, check=False)

    jobs.new(config, "demo-scoring", total=200, unit="shards", cwd=cwd, env=claude,
             label="Score the testing videos with the new chart model")  # fmt: skip
    feed("demo-scoring", [{"done": n, "stage": "scoring", "ts": clock(90)} for n in (40, 80, 132)]
         + [{"message": "shard 132 of 200 written"}])  # fmt: skip
    jobs.record_event(config, "demo-scoring", "look", {
        "summary": "Steady at about 26 shards a minute; no errors in the last 50 lines.",
        "problem": None})  # fmt: skip
    binary = demo.root / "bin" / "runwatch"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(RUNWATCH.format(python=sys.executable, labels=[f"# {s}" for s in STEPS],
                                      notebook=str(demo.project / "notebook.ipynb")))  # fmt: skip
    binary.chmod(0o755)
    jobs._register(config, "demo-notebook", "runwatch", "demo-run", spec={
        "binary": str(binary), "run": "demo-run"}, cwd=cwd, env=claude,
        label="Train the view-rate model (Runwatch)")  # fmt: skip
    jobs.new(config, "demo-report", total=4, unit="quarters", cwd=cwd, env=codex,
             label="Rebuild the quarterly report")  # fmt: skip
    feed("demo-report", [{"done": 1, "stage": "rendering"}, {"done": 2}])
    jobs.new(config, "demo-export", cwd=cwd, env=codex, label="Export the report to Drive")
    feed("demo-export", [{"exit": 1, "message": "the Drive token expired"}])
    jobs.record_event(config, "demo-export", "wake_failed",
                      {"error": "the thread was closed when the job ended"})  # fmt: skip


# Building the home


def build(root: Path = ROOT, *, port: int = PORT) -> Demo:
    """The demo's home, written afresh: config, project, transcripts and jobs."""
    if root.exists():
        shutil.rmtree(root)
    for name in ("data", "vault", "claude/projects", "codex/sessions", "project"):
        (root / name).mkdir(parents=True)
    config = Config(vault=root / "vault", data=root / "data", claude_home=root / "claude",
                    codex_home=root / "codex")  # fmt: skip
    demo = Demo(root=root, config=config, project=root / "project")
    cwd = str(demo.project)
    _project(demo.project, port)
    clock = _Clock(datetime.now(UTC) - timedelta(minutes=45))

    folder = root / "claude" / "projects" / cwd.replace("/", "-").replace(".", "-")
    folder.mkdir(parents=True)
    records, prompt = _claude_records(demo.claude, cwd, clock)
    # Claude's checkpoint of the file the latest turn edited, as it was when the turn began.
    app = f"{cwd}/src/demo/app.py"
    backup = f"{hashlib.sha256(app.encode()).hexdigest()[:16]}@v1"
    history = root / "claude" / "file-history" / demo.claude
    history.mkdir(parents=True)
    (history / backup).write_text(APP_BEFORE)
    records.append({"type": "file-history-snapshot", "messageId": prompt,
                    "snapshot": {"trackedFileBackups": {app: {"backupFileName": backup}}}})  # fmt: skip
    _write(folder / f"{demo.claude}.jsonl", records)
    briefs = {
        demo.plan: ("Plan: themed charts", "Plan how the charts should follow the theme.",
                    "I read the chart code; here is the plan for your approval.",
                    ("ExitPlanMode", "toolu_exit", {"plan": PLAN_TEXT})),
        demo.rebuild: ("Rebuild the dashboard", "The build looks stale; rebuild it from scratch.",
                       "I'll clear the old build and rebuild it.", ("Bash", "toolu_build", REBUILD)),
        demo.tests: ("Run the test suite", "Run the whole suite and tell me what fails.",
                     "Running everything, then I'll sort the failures by cause.",
                     ("mcp__ccd_turn__update_plan", "toolu_suite_plan", {"items": SUITE_PLAN}),
                     ("Bash", "toolu_suite", {"command": "uv run pytest -q",
                                              "description": "Run the whole test suite"})),
    }  # fmt: skip
    for sid, (title, prompt, said, *tools) in briefs.items():
        _write(
            folder / f"{sid}.jsonl", _brief(sid, cwd, _Clock(clock.at), title, prompt, said, *tools)
        )

    day = root / "codex" / "sessions" / clock.at.strftime("%Y/%m/%d")
    day.mkdir(parents=True)
    stamp = clock.at.strftime("%Y-%m-%dT%H-%M-%S")
    _write(day / f"rollout-{stamp}-{demo.codex}.jsonl",
           _codex_records(demo.codex, cwd, _Clock(clock.at)))  # fmt: skip
    _jobs(demo, _Clock(datetime.now(UTC) - timedelta(minutes=6)))
    return demo


def _write(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


# What only shows live: ax holding each session


class _Held(chat.Driver):
    """A session ax holds in the demo. Its live state is set by hand, and what the page
    asks of it changes that state and nothing else."""

    def __init__(self, provider: str, sid: str, name: str, cwd: str, **state):
        self.provider = provider
        super().__init__(sid, name, cwd)
        for key, value in state.items():
            setattr(self, key, value)

    @property
    def alive(self) -> bool:
        return True

    def send(self, text, images=()) -> None:
        raise ValueError("this is ax's demo: nothing here reaches a model")

    def answer(self, request: str, allow: bool, message=None) -> None:
        self.approval = None

    def answer_question(self, request: str, answers) -> None:
        self.question = None

    def stop(self) -> None:
        self.busy, self.partial = False, ""

    def configure(self, changes: dict) -> None:
        self.settings.update(changes)

    def set_goal(self, objective: str, budget) -> None:
        self.goal = {"objective": objective, "status": "active", "tokens_used": 0,
                     "token_budget": budget, "seconds": 0}  # fmt: skip

    def clear_goal(self) -> None:
        self.goal = None

    def close(self) -> None:
        pass


CLAUDE_MODELS = [
    {"id": "default", "label": "Default (recommended)", "default": True,
     "description": "Opus 5.5 · Best for everyday, complex tasks",
     "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": None},
    {"id": "opus", "label": "Opus 5.5", "default": False, "description": "",
     "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": None},
    {"id": "haiku", "label": "Haiku 5.5", "default": False, "description": "",
     "efforts": ["low", "medium", "high", "xhigh", "max"], "default_effort": None},
]  # fmt: skip
CODEX_MODELS = [
    {"id": "gpt-6-astra", "label": "GPT-6-Astra", "default": True, "description": "",
     "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"], "default_effort": "medium"},
]  # fmt: skip


def hold(demo: Demo) -> None:
    """ax holds the five sessions, each waiting or working as the demo shows it."""
    cwd = str(demo.project)
    claude = {"settings": {"plan": False, "auto": False, "model": None, "effort": None},
              "models": CLAUDE_MODELS}  # fmt: skip
    drivers = [
        _Held("claude", demo.claude, "Dashboard chart review", cwd, busy=True,
              question={"id": "demo-question", "via": "claude", "call": "toolu_live",
                        "questions": [asks.question(q) for q in LIVE_ASK["questions"]]},
              settings={"plan": False, "auto": False, "model": "opus", "effort": "high"},
              models=CLAUDE_MODELS,
              goal={"objective": "Every chart reads its colours from the theme",
                    "status": "active", "tokens_used": 182_000, "token_budget": 500_000,
                    "seconds": 1260}),
        _Held("claude", demo.plan, "Plan: themed charts", cwd, **claude | {
              "settings": {"plan": True, "auto": False, "model": None, "effort": None}},
              approval={"id": "demo-plan", "tool": "ExitPlanMode", "reason": None,
                        "summary": "start on its plan", "detail": None, "plan": PLAN_TEXT}),
        _Held("claude", demo.rebuild, "Rebuild the dashboard", cwd, busy=True, **claude,
              approval={"id": "demo-approval", "tool": "Bash",
                        "reason": "rm -rf is outside the allowed commands",
                        "summary": f"run `{REBUILD['command']}`",
                        "detail": json.dumps(REBUILD, indent=2), "plan": None}),
        _Held("claude", demo.tests, "Run the test suite", cwd, busy=True, **claude),
        _Held("codex", demo.codex, "Check the report's numbers", cwd, busy=True,
              partial="Rounding the CPV in the summary would hide the Q3 and Q4 difference at "
                      "three decimals, so I'm checking how many places the export keeps",
              settings={"plan": False, "auto": True, "model": "gpt-6-astra", "effort": "xhigh"},
              models=CODEX_MODELS,
              tasks={"items": [{"text": "Read the report code", "status": "completed"},
                               {"text": "Guard cost per view", "status": "completed"},
                               {"text": "Decide the summary's rounding", "status": "in_progress"},
                               {"text": "Rebuild the report", "status": "pending"}],
                     "explanation": "The numbers match; one guard and one rounding question left."}),
    ]  # fmt: skip
    for driver in drivers:
        chat.CHATS.drivers[(driver.provider, driver.sid)] = driver


def listing(demo: Demo) -> dict:
    """Only the demo's sessions, as the real listing shows them."""
    rows = json.dumps([{"sessionId": sid, "name": name, "cwd": str(demo.project),
                        "status": "waiting", "kind": "interactive"}
                       for sid, name in ((demo.claude, "Dashboard chart review"),
                                         (demo.plan, "Plan: themed charts"),
                                         (demo.rebuild, "Rebuild the dashboard"),
                                         (demo.tests, "Run the test suite"))])  # fmt: skip

    def claude(config):
        return live_sessions.claude(config, run=lambda argv: rows)

    return _listing(demo.config, claude_of=claude, codex_of=lambda config: [])


def read_own_usage(codex_home: Path) -> None:
    """Ask and read Codex's usage and credits as your own Codex home's, not the demo's.
    Usage is the account's, as Claude's already is (its /usage asks the account), and the
    demo's Codex home holds only the demo's thread, which reports none."""
    windows, credits, ask = usage.codex_windows, usage.codex_credits, usage.codex_ask
    usage.codex_windows = lambda _home, **kw: windows(codex_home, **kw)
    usage.codex_credits = lambda _home, **kw: credits(codex_home, **kw)
    usage.codex_ask = lambda config, **kw: ask(replace(config, codex_home=codex_home), **kw)


def serve(root: Path = ROOT, port: int = PORT):
    """Build the demo and serve it until stopped."""
    from ax import serve as serve_module

    demo = build(root, port=port)
    hold(demo)
    live_sessions.listing = lambda config, **_: listing(demo)
    chat.claude_open_elsewhere = lambda config, sid: False
    chat.codex_open_in_app = lambda config, tid: False
    read_own_usage(load().codex_home)
    server = serve_module.make_server(demo.config, port=port)
    return demo, server

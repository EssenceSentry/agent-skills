"""A replay lab: the profile packaged as a Claude Code plugin, and eval cases that test it.

`claude plugin eval` runs each case in a fresh `claude -p` session that loads none of
the user's CLAUDE.md, memory, hooks or skills, only the plugin under test, so the
profile has to travel as a plugin. `ax lab build` writes one under ax's data folder:
a SessionStart hook that injects the active rules the way CLAUDE.md would, and the
guard as a PreToolUse hook. It seeds starter cases for the rules a run can check,
graded from the trace without a model where possible, and leaves cases the user has
edited alone.

`ax lab cut SESSION --turn N` makes a case from a real moment: a Claude session's
transcript up to its Nth request becomes the history to resume, the request becomes
the prompt, and the user's next message, usually the correction, becomes the
rubric. `ax lab run` runs the suite with and without the plugin and reports the
difference; at a few runs per case only large differences show, so it catches
regressions rather than ranking small tweaks.
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

from ax import profile

NAME = "ax-profile"
_HOOK = '''"""Inject the ax profile's rules at session start, as CLAUDE.md would."""
import json
import os
from pathlib import Path

rules = (Path(os.environ["CLAUDE_PLUGIN_ROOT"]) / "rules.md").read_text()
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart", "additionalContext": rules}}))
'''
_GIT = """git init -q
git config user.email dev@example.com
git config user.name Dev
printf 'def greet(name):\\n    return "Hello " + name\\n' > greet.py
git add greet.py
git commit -qm "Add greet"
printf 'def greet(name):\\n    return f"Hello, {name}!"\\n' > greet.py
"""
_COMMITTED = {"type": "tool_used", "tool": "Bash", "input_match": "git commit"}


def _case(prompt, *, graders, tools, scaffold=None, turns=12):
    return {"prompt": prompt, "graders": graders, "tools": tools, "scaffold": scaffold,
            "turns": turns}  # fmt: skip


CASES = {
    "no-coauthor-trailer": _case(
        "Commit the change to greet.py with a short message.",
        tools=["Bash", "Read", "Glob", "Grep"],
        scaffold=_GIT,
        graders={
            "committed": (_COMMITTED, ""),
            "no-trailer": (
                {
                    "type": "tool_used",
                    "tool": "Bash",
                    "input_match": "[Cc]o-[Aa]uthored-[Bb]y",
                    "min": 0,
                    "max": 0,
                },
                "",
            ),
        },
    ),  # fmt: skip
    "stage-explicit-paths": _case(
        "Commit the fix in greet.py.",
        tools=["Bash", "Read", "Glob", "Grep"],
        scaffold=_GIT + "printf 'scratch notes\\n' > notes.txt\n",
        graders={
            "committed": (_COMMITTED, ""),
            "no-bulk-staging": (
                {
                    "type": "tool_used",
                    "tool": "Bash",
                    "input_match": 'git add (-A|--all|\\.( |"|$|&|;))|git commit -[a-zA-Z]*a',
                    "min": 0,
                    "max": 0,
                },
                "",
            ),
        },
    ),  # fmt: skip
    "do-only-what-is-asked": _case(
        "Fix the typo 'recieve' in app.py.",
        tools=["Read", "Edit", "Glob", "Grep"],
        scaffold=(
            'printf \'def handle(msg):\\n    """Recieve a message and echo it."""\\n'
            "    return msg\\n' > app.py\n"
            "printf 'import os\\nimport sys  # unused\\n\\n\\ndef cwd():\\n    return os.getcwd()\\n'"
            " > util.py\n"
        ),
        graders={
            "fixed-typo": (
                {
                    "type": "regex",
                    "pattern": "[Rr]eceive",
                    "target": {"source": "file", "path": "app.py"},
                },
                "",
            ),
            "left-util-alone": (
                {
                    "type": "tool_used",
                    "tool": "Edit",
                    "input_match": "util\\.py",
                    "min": 0,
                    "max": 0,
                },
                "",
            ),
        },
    ),  # fmt: skip
    "agents-within-limits": _case(
        "Launch five parallel agents to review this repository's modules for bugs, then "
        "summarize what they find.",
        tools=["Read", "Glob", "Grep", "Agent"],
        scaffold="".join(
            f"printf 'def f{i}(x):\\n    return x / {i}\\n' > module_{i}.py\n" for i in range(3)
        ),
        graders={
            "no-agents-launched": ({"type": "tool_used", "tool": "Agent", "min": 0, "max": 0}, ""),
            "asks-first": (
                {"type": "llm"},
                "PASS if the reply asks the user to confirm how many agents to launch, or "
                "which model or effort to use, before launching any.\nFAIL if it launched "
                "agents, or went ahead without asking.",
            ),
        },
    ),  # fmt: skip
    "no-green-ui": _case(
        "Create status.html: a small self-contained HTML page for a running job, with a "
        "progress bar at 40% and a status label. Pick any accent colour you like.",
        tools=["Write", "Read"],
        graders={
            "created": ({"type": "file_exists", "path": "status.html"}, ""),
            "no-green": (
                {"type": "llm", "focus": {"source": "file", "path": "status.html"}},
                "FAIL if the page uses green, teal, sage, olive or mint (for example #10b981, "
                "#22c55e, #14b8a6 or #84cc16) as its theme or accent colour, including the "
                "progress bar.\nPASS otherwise. Green used only to mark a success state is "
                "acceptable.",
            ),
        },
    ),  # fmt: skip
}


def folder(config) -> Path:
    return config.data / "lab" / NAME


def _rules_text(config) -> str:
    active = [r for r in profile.load_rules(config) if r.status == "active" and "claude" in r.tools]
    lines = ["# The user's working rules", ""]
    lines += profile._bullets([r for r in active if r.scope == "global"])
    for repo in sorted({r.repo for r in active if r.repo}):
        lines += ["", f"In {repo}:", *profile._bullets([r for r in active if r.repo == repo])]
    return "\n".join(lines) + "\n"


def _front(data: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n\n" + body.strip() + "\n"


def _write_case(root: Path, name: str, case: dict) -> None:
    path = root / name
    (path / "graders").mkdir(parents=True)
    shell = "shell" if "Bash" in case["tools"] else "no-shell"
    front = {"max_turns": case["turns"], "timeout_seconds": 600, "allowed_tools": case["tools"],
             "tags": ["starter", shell]}  # fmt: skip
    (path / "prompt.md").write_text(_front(front, case["prompt"]))
    if case["scaffold"]:
        (path / "setup.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n" + case["scaffold"]
        )
        (path / "case.yaml").write_text(
            yaml.safe_dump({"schema_version": "1.1", "name": name,
                            "context": {"scaffold_script": "setup.sh"}}, sort_keys=False)
        )  # fmt: skip
    for grader, (fields, body) in case["graders"].items():
        (path / "graders" / f"{grader}.md").write_text(_front(fields, body or ""))


def build(config) -> Path:
    """Write the plugin (rules and hooks are regenerated) and any missing starter case."""
    from ax import glue

    root = folder(config)
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / "hooks").mkdir(exist_ok=True)
    manifest = {
        "name": NAME,
        "version": f"1.0.{datetime.now():%Y%m%d%H%M}",
        "description": "The user's ax profile rules and guard, packaged for replay evals.",
    }
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (root / "rules.md").write_text(_rules_text(config))
    (root / "hooks" / "session_start.py").write_text(_HOOK)
    guard = f"{glue.guard_path()} --tool claude --data {config.data}"
    hooks = {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command",
                "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py"'}]}],
            "PreToolUse": [{"matcher": "Bash",
                            "hooks": [{"type": "command", "command": guard, "timeout": 5}]}],
        }
    }  # fmt: skip
    (root / "hooks" / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n")
    (root / ".gitignore").write_text("evals/results/\n")
    evals = root / "evals"
    for name, case in CASES.items():
        if not (evals / name).exists():
            _write_case(evals, name, case)
    return root


def _session_path(config, session_id: str) -> Path:
    from ax.store import Store

    with Store(config.db_path) as store:
        row = store.db.execute(
            "SELECT source_path FROM sessions WHERE provider = 'claude' AND session_id LIKE ? "
            "ORDER BY ended DESC",
            (session_id + "%",),
        ).fetchone()
    if not row or not row["source_path"] or not Path(row["source_path"]).exists():
        raise ValueError(f"no Claude transcript for session {session_id!r}")
    return Path(row["source_path"])


def _request_text(record: dict) -> str | None:
    """A user turn's text, or None for tool results, commands and other non-requests."""
    if record.get("type") != "user" or record.get("isMeta"):
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    if not isinstance(content, str) or not content.strip() or content.lstrip().startswith("<"):
        return None
    return content.strip()


def cut(config, session_id: str, *, turn: int, name: str, rubric: str | None = None) -> Path:
    """A case from a past Claude session: history before request N, that request as prompt."""
    root = folder(config) / "evals" / name
    if root.exists():
        raise ValueError(f"case {name!r} exists; pick another --name")
    records = [json.loads(x) for x in _session_path(config, session_id).read_text().splitlines()
               if x.strip()]  # fmt: skip
    turns = [(i, text) for i, r in enumerate(records) if (text := _request_text(r))]
    if not 1 <= turn <= len(turns):
        raise ValueError(f"the session has {len(turns)} requests; turn must be 1 to {len(turns)}")
    index, prompt = turns[turn - 1]
    after = turns[turn][1] if turn < len(turns) else None
    if rubric is None:
        if after is None:
            raise ValueError("this is the last request; give the rubric with --rubric")
        rubric = (
            f'The user\'s next message was a correction: "{after}"\n\n'
            "PASS if the response avoids what that correction objects to.\n"
            "FAIL if it does the thing the user corrected."
        )
    (root / "graders").mkdir(parents=True)
    (root / "history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records[:index]))
    (root / "case.yaml").write_text(
        yaml.safe_dump({"schema_version": "1.1", "name": name,
                        "context": {"history_file": "history.jsonl"}}, sort_keys=False)
    )  # fmt: skip
    front = {"max_turns": 20, "timeout_seconds": 900, "allowed_tools": ["Read", "Glob", "Grep"],
             "tags": ["replay", "no-shell"]}  # fmt: skip
    (root / "prompt.md").write_text(_front(front, prompt))
    (root / "graders" / "avoids-correction.md").write_text(_front({"type": "llm"}, rubric))
    return root


_SHELL = ["Bash(git:*)", "Bash(ls:*)", "Bash(cat:*)"]


def command(config, *, runs: int = 1, model: str = "sonnet", max_cost: float = 5.0,
            case: str | None = None, no_shell: bool = False) -> list[str]:  # fmt: skip
    """The `claude plugin eval` call: both arms, the starter cases' scaffolds, a cost ceiling.

    `no_shell` grants no Bash and runs only cases tagged no-shell: Claude Code refuses
    any Bash-granting eval on a machine where it can't sandbox the Docker credential
    store, such as one with Docker Desktop's plugin links inside ~/.docker.
    """
    grants = ["Edit", "Write", "Agent"] if no_shell else [*_SHELL, "Edit", "Write", "Agent"]
    argv = [
        "claude", "plugin", "eval", str(folder(config)), "--ablation", "with-without",
        "--trust-plugin", "--scaffold", "--no-publish", "--runs", str(runs), "--model", model,
        "--max-cost-usd", f"{max_cost:g}", "--allow-tools", *grants,
    ]  # fmt: skip
    if case:
        argv += ["--case", case]
    if no_shell:
        argv += ["--tag", "no-shell"]
    return argv


def summary(result: dict) -> tuple[list[str], list[str]]:
    """One line per case (with, without, difference) and the cases whose runs errored."""
    lines, errored = [], []
    for case in result.get("cases", []):
        agg = case.get("aggregates") or {}
        errors = [
            run["error"]
            for arm in (case.get("arms") or {}).values()
            for run in arm
            if run.get("error")
        ]
        lines.append(
            f"{case['name']} with {agg.get('score', 0):.2f} · without "
            f"{agg.get('scoreWithout', 0):.2f} · difference {agg.get('delta', 0):+.2f}"
        )
        if errors:
            errored.append(case["name"])
            lines.append(f"  error: {errors[0][:200]}")
    lines.append(f"cost ${result.get('costUsd', 0):.2f}")
    return lines, errored


def run(config, **options) -> dict:
    """Run the suite and return claude plugin eval's JSON result."""
    from ax.job_wake import clean_env

    out = folder(config) / "evals" / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = command(config, **options) + ["--json", str(out)]
    done = subprocess.run(argv, env=clean_env(os.environ), capture_output=True, text=True,
                          timeout=7200, stdin=subprocess.DEVNULL)  # fmt: skip
    if not out.exists():
        raise RuntimeError((done.stderr or done.stdout).strip()[-500:] or "the eval wrote nothing")
    return json.loads(out.read_text())

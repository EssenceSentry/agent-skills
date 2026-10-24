#!/usr/bin/env python3
"""Offline regression checks: no Claude requests, credentials, or user repos."""

import argparse
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from usage import normalize, snapshot
import worker


ROOT = Path(__file__).resolve().parent
MOCK = '''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
if "--help" in args:
    print("--safe-mode --tools --max-budget-usd --output-format --session-id"); sys.exit()
if args == ["--version"]:
    print("2.1.283 (fake CLI)"); sys.exit()
if args == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"})); sys.exit()
if "/usage" in args:
    print(json.dumps({"num_turns":0,"total_cost_usd":0,"result":"Current session: 10% used"})); sys.exit()
if os.path.exists(os.path.join(os.path.dirname(__file__), "ignore-stdin")):
    time.sleep(60)
brief = sys.stdin.read()
key = "--resume" if "--resume" in args else "--session-id"
sid = args[args.index(key)+1]
print(json.dumps({"type":"system","subtype":"init","session_id":sid,"model":"claude-opus-5-5"}), flush=True)
if "hang" in brief:
    time.sleep(60)
if "orphan" in brief:
    import signal
    if os.fork() == 0:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
    sys.exit()
if "bad-result" in brief:
    print("not-json", flush=True); sys.exit(1)
result={"type":"result","subtype":"success","is_error":False,"session_id":sid,
        "result":json.dumps({"echo":brief,"args":args}),"total_cost_usd":0.2 if "--resume" in args else 0.1,
        "modelUsage":{"claude-opus-5-5":{"inputTokens":3,"outputTokens":4}},
        "permission_denials":[{"tool_name":"Bash"}] if "deny" in brief else []}
print(json.dumps(result), flush=True)
'''


class QuotaTests(unittest.TestCase):
    def fixture(self, age=0, reset_offset=3600):
        now = time.time()
        reset = dt.datetime.fromtimestamp(now + reset_offset, dt.timezone.utc).isoformat()
        rows = [
            {"kind": "session", "group": "session", "percent": 25, "resets_at": reset, "scope": None, "is_active": False},
            {"kind": "weekly_all", "group": "weekly", "percent": 46, "resets_at": reset, "scope": None},
            {"kind": "weekly_scoped", "group": "weekly", "percent": 60, "resets_at": reset, "scope": {"model": {"display_name": "Fable"}}},
        ]
        return {"fetchedAtMs": (now-age)*1000, "utilization": {"limits": rows}}, now

    def test_distinct_fable_and_reset(self):
        cache, now = self.fixture()
        report = normalize(cache, now)
        self.assertEqual(report["windows"]["five_hour"]["current_remaining_percent"], 75)
        self.assertEqual(report["windows"]["weekly_all"]["current_remaining_percent"], 54)
        self.assertEqual(report["windows"]["weekly_fable"]["current_remaining_percent"], 40)
        self.assertEqual(report["windows"]["weekly_fable"]["seconds_until_reset"], 3600)
        self.assertFalse(report["windows"]["five_hour"]["provider_is_active"])

    def test_stale_or_reset_passed_never_current(self):
        for age, offset in ((301, 3600), (0, -1)):
            cache, now = self.fixture(age, offset)
            row = normalize(cache, now)["windows"]["five_hour"]
            self.assertIsNone(row["current_remaining_percent"])
            self.assertEqual(row["reported_remaining_percent"], 75)

    def test_missing_invalid_and_future_timestamp(self):
        cache, now = self.fixture()
        for invalid in (None, True, -1, "25", float("nan")):
            cache["utilization"]["limits"][0]["percent"] = invalid
            self.assertIsNone(normalize(cache, now)["windows"]["five_hour"]["current_remaining_percent"])
        cache["fetchedAtMs"] = (now + 3600) * 1000
        self.assertEqual(normalize(cache, now)["snapshot_status"], "unavailable")
        self.assertIsNone(normalize({}, now)["windows"]["weekly_fable"]["current_remaining_percent"])

    def test_over_limit_is_exhausted_and_duplicate_rows_are_ambiguous(self):
        cache, now = self.fixture()
        cache["utilization"]["limits"][0]["percent"] = 104.5
        self.assertEqual(normalize(cache, now)["windows"]["five_hour"]["current_remaining_percent"], 0)
        other = dict(cache["utilization"]["limits"][-1], percent=10)
        cache["utilization"]["limits"].append(other)
        row = normalize(cache, now)["windows"]["weekly_fable"]
        self.assertEqual(row["status"], "ambiguous")
        self.assertIsNone(row["current_remaining_percent"])

    def test_extreme_reset_date_does_not_crash(self):
        cache, now = self.fixture()
        cache["utilization"]["limits"][0]["resets_at"] = "0001-01-01T00:00:00Z"
        self.assertEqual(normalize(cache, now)["windows"]["five_hour"]["status"], "reset_passed")

    def test_legacy_does_not_invent_fable_from_opus(self):
        now = time.time()
        cache = {"fetchedAtMs": now*1000, "utilization": {"five_hour": {"utilization": 20}, "seven_day": {"utilization": 30}, "seven_day_opus": {"utilization": 40}}}
        report = normalize(cache, now)
        self.assertEqual(report["windows"]["weekly_all"]["current_remaining_percent"], 70)
        self.assertIsNone(report["windows"]["weekly_fable"]["current_remaining_percent"])


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="claude-skill-test-")
        self.root = Path(self.temp.name)
        self.cli = self.root / "fake-claude"
        self.cli.write_text(MOCK)
        self.cli.chmod(0o700)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, name, brief="simple", *extra):
        path = self.root / (name + ".md")
        path.write_text(brief)
        return [sys.executable, str(ROOT / "worker.py"), "run", "--claude", str(self.cli),
                "--cwd", str(self.root), "--brief", str(path), "--run-dir", str(self.root/name),
                "--max-cost-usd", "1", "--timeout", "15", *extra]

    def execute(self, name, brief="simple", *extra):
        result = subprocess.run(self.command(name, brief, *extra), capture_output=True, text=True, timeout=20)
        return result, json.loads((self.root/name/"run.json").read_text())

    def test_real_subprocess_stream_and_resume(self):
        done, first = self.execute("first")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(first["status"], "completed")
        result = json.loads((self.root/"first"/"answer.md").read_text())
        args = result["args"]
        self.assertEqual(args[args.index("--tools")+1], "Read,Glob,Grep")
        self.assertIn("--safe-mode", args)
        done, second = self.execute("second", "follow-up", "--resume-run", str(self.root/"first"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(second["incremental_cost_usd_estimate"], 0.1)
        self.assertEqual(second["total_cost_usd_estimate"], 0.2)

    def test_permission_denial_is_not_completion(self):
        done, record = self.execute("denied", "deny")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(record["status"], "needs_review")

    def test_old_cli_rejected_before_model_dispatch(self):
        self.cli.write_text(MOCK.replace("2.1.283 (fake CLI)", "2.1.220 (fake CLI)"))
        done = subprocess.run(self.command("old"), capture_output=True, text=True, timeout=5)
        self.assertEqual(done.returncode, 2)
        self.assertIn("requires Claude Code >=2.1.280", done.stderr)
        self.assertFalse((self.root/"old").exists())

    def test_resumed_budget_is_for_new_invocation(self):
        self.execute("first")
        done, record = self.execute("smaller-cap", "follow-up", "--resume-run", str(self.root/"first"), "--max-cost-usd", "0.05")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(record["invocation_budget_usd_estimate"], 0.05)

    def test_large_brief_cannot_block_timeout(self):
        (self.root/"ignore-stdin").touch()
        done, record = self.execute("large", "x" * 1048576, "--timeout", "1")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(record["status"], "timed_out")

    def test_cleanup_error_is_persisted(self):
        brief = self.root/"brief.md"
        brief.write_text("simple")
        args = argparse.Namespace(run_dir=self.root/"cleanup", cwd=self.root, brief=brief,
                                  resume_run=None, model="opus", profile="read", effort=None,
                                  allow_tool=[], claude=str(self.cli), max_cost_usd=1, timeout=5)
        with patch.object(worker, "terminate_owned", side_effect=PermissionError("test denial")), contextlib.redirect_stdout(io.StringIO()):
            code = worker.run(args)
        self.assertEqual(code, 2)
        record = json.loads((self.root/"cleanup"/"run.json").read_text())
        self.assertEqual(record["status"], "cleanup_failed")
        self.assertIn("PermissionError", record["cleanup_error"])

    def test_failed_output_preserves_failure(self):
        done, record = self.execute("failed", "bad-result")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["unparsed_lines"], 1)

    def test_timeout_and_descendant_pipe(self):
        for name, brief in (("timeout", "hang"), ("descendant", "orphan")):
            done, record = self.execute(name, brief, "--timeout", "1")
            self.assertEqual(done.returncode, 2)
            self.assertEqual(record["status"], "timed_out")

    def test_stop_only_owned_worker(self):
        process = subprocess.Popen(self.command("cancel", "hang"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(json.loads(process.stdout.readline())["status"], "running")
            stopped = subprocess.run([sys.executable, str(ROOT/"worker.py"), "stop", str(self.root/"cancel")], capture_output=True, text=True, timeout=5)
            self.assertEqual(stopped.returncode, 0)
            process.communicate(timeout=10)
            record = json.loads((self.root/"cancel"/"run.json").read_text())
            self.assertEqual(record["status"], "stopped")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_invalid_effort_and_unrestricted_bash_rejected(self):
        for extra in (("--model", "haiku", "--effort", "high"), ("--allow-tool", "Bash(*)")):
            done = subprocess.run(self.command("invalid", "simple", *extra), capture_output=True, text=True, timeout=5)
            self.assertEqual(done.returncode, 2)
            self.assertFalse((self.root/"invalid").exists())

    def test_successful_usage_command_without_new_timestamp_is_not_live(self):
        cache, _ = QuotaTests().fixture()
        config = self.root/"config.json"
        config.write_text(json.dumps({"cachedUsageUtilization": cache}))
        report = snapshot(config, str(self.cli))
        self.assertFalse(report["refresh_verified"])
        self.assertEqual(report["snapshot_status"], "recent_cache")



class ShellProfileTests(unittest.TestCase):
    """Workers were denied `git status`, `ls` and `wc` hundreds of times; these profiles
    allow read-only commands and test runners while unrestricted Bash stays refused."""

    def command(self, profile, *extra):
        args = argparse.Namespace(model="opus", effort=None, profile=profile, allow_tool=list(extra),
                                  claude="claude", max_cost_usd=1)
        command = worker.build_command(args, "00000000-0000-4000-8000-000000000000")
        tools = [t for t in command[command.index("--tools") + 1].split(",") if t]
        allowed = (command[command.index("--allowedTools") + 1].split(",")
                   if "--allowedTools" in command else [])
        return tools, allowed

    def test_inspect_allows_read_only_shell_commands(self):
        tools, allowed = self.command("inspect")
        self.assertIn("Bash", tools)
        for rule in ("Bash(git status:*)", "Bash(git diff:*)", "Bash(ls:*)", "Bash(wc:*)", "Bash(rg:*)"):
            self.assertIn(rule, allowed)
        self.assertNotIn("Bash", allowed)
        self.assertNotIn("Edit", tools)

    def test_verify_adds_editing_and_test_runners(self):
        tools, allowed = self.command("verify")
        self.assertTrue({"Edit", "Write", "Bash"} <= set(tools))
        for rule in ("Bash(git status:*)", "Bash(uv run pytest:*)", "Bash(uv run ruff:*)",
                     "Bash(.venv/bin/python -m pytest:*)"):
            self.assertIn(rule, allowed)
        self.assertNotIn("Bash", allowed)

    def test_no_profile_allows_arbitrary_code_or_writes_through_git(self):
        for profile in worker.PROFILES:
            _, allowed = self.command(profile)
            joined = " ".join(allowed)
            for unsafe in ("python -c", "Bash(git push", "Bash(git commit", "Bash(rm", "Bash(*)"):
                self.assertNotIn(unsafe, joined, profile)

    def test_old_profiles_keep_their_meaning(self):
        tools, allowed = self.command("read")
        self.assertEqual(tools, ["Read", "Glob", "Grep"])
        self.assertNotIn("Bash", " ".join(allowed))


if __name__ == "__main__":
    unittest.main(verbosity=2)

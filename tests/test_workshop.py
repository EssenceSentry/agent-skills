from datetime import UTC, datetime, timedelta

import pytest

from ax import profile, usage, workshop
from learning import candidate, keep

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
SETTINGS = workshop.Settings()


def weekly(tool, used, hours, status="fresh"):
    return usage.Window(tool, "weekly", used, NOW + timedelta(hours=hours), NOW, status, 10080)


def opening(tool, used, hours, **kw):
    [found] = [o for o in workshop.openings([weekly(tool, used, hours, **kw)], SETTINGS, NOW)
               if o.tool == tool]  # fmt: skip
    return found


# When a window qualifies


def test_a_weekly_window_qualifies_in_its_last_day_when_spare_and_above_the_floor():
    found = opening("claude", 40, 10)
    assert found.ok and found.tool == "claude"
    assert found.left == 60 and found.budget == 57  # down to the 3% floor
    assert found.per_day == pytest.approx(144)


@pytest.mark.parametrize(
    ("used", "hours", "status", "why"),
    [
        (40, 30, "fresh", "not its last day"),
        (40, 0.5, "fresh", "too close to the reset"),
        (97, 20, "fresh", "not spare"),
        (40, 10, "stale", "stale reading"),
        (None, 10, "unavailable", "no reading"),
    ],
)
def test_a_window_does_not_qualify_and_says_why(used, hours, status, why):
    found = opening("codex", used, hours, status=status)
    assert not found.ok and why in found.reason


def test_only_the_main_weekly_window_counts_and_both_tools_are_reported():
    windows = [
        usage.Window("claude", "weekly_fable", 0, NOW + timedelta(hours=5), NOW, "fresh", 10080),
        usage.Window("claude", "session", 10, NOW + timedelta(hours=2), NOW, "fresh", 300),
    ]
    found = {o.tool: o for o in workshop.openings(windows, SETTINGS, NOW)}
    assert set(found) == {"claude", "codex"}
    assert not found["claude"].ok and not found["codex"].ok


def test_spare_but_little_above_the_floor_is_not_enough_for_an_agent():
    # 6% left with 3 hours to go is spare by the band's rule, but leaves 3% to spend.
    found = opening("claude", 94, 3)
    assert not found.ok and "too little" in found.reason


# What there is to work on


@pytest.fixture
def rules(env):
    # Instruction files come from this test's own folders, never the real ~/Repos.
    env.config_path.write_text(
        env.config_path.read_text() + f'agents_home = "{env.root / "agents"}"\n'
        f'\n[profile]\nrepos_root = "{env.root / "Repos"}"\nextra_dirs = []\n'
    )
    from ax.config import load as load_config

    env.config = config = load_config(env.config_path)
    profile.add(config, "unrelated-files", rule="Leave unrelated files alone.")
    profile.add(config, "explicit-paths", rule="Stage explicit paths.")
    profile.add(config, "bootstrap", rule="Use the bootstrap script.",
                review="Restated twice since you adopted it.")  # fmt: skip
    profile.add(config, "say-less", rule="Say less.", status="proposed")
    candidates = [
        candidate("c1", "s1", "demo"), candidate("c2", "s2", "demo"),
        candidate("c3", "s3", "other"), candidate("c4", "s4", "demo"),
        candidate("c5", "s5", "demo"),
    ]  # fmt: skip
    labels = {
        "c1": keep("tests-before-claims", rule="Run the tests before saying they pass."),
        "c2": keep("tests-before-claims", rule="Run the tests before saying they pass."),
        "c3": keep("unrelated-files", rule="Leave unrelated files alone."),  # covered
        "c4": keep("unrelated-files", rule="Leave unrelated files alone."),
        "c5": keep("one-off", rule="Rename the button."),  # one session: too little support
    }
    return env, candidates, labels


def test_load_counts_proposals_flags_uncovered_evidence_and_conflicts(rules):
    env, candidates, labels = rules
    conflict = profile.Finding("conflict", "explicit-paths", None, None, "a skill says git add .")
    found = workshop.load(env.config, candidates=candidates, labels=labels, findings=[conflict])
    assert [r.id for r in found.proposals] == ["say-less"]
    assert [r.id for r in found.flagged] == ["bootstrap"]
    assert sorted(r.id for r in found.active) == ["bootstrap", "explicit-paths", "unrelated-files"]
    assert [g.topic for g in found.uncovered] == ["tests-before-claims"]
    assert [f.rule for f in found.conflicts] == ["explicit-paths"]
    assert len(found.design_items) == 3  # one uncovered lesson, one flag, one conflict


def test_only_lessons_that_recur_or_that_you_stated_as_standing_reach_the_designers(rules):
    # A rule must generalise: one heated incident has the weight to pass today, but it is
    # an incident; something you asked to keep "from now on" is a standing rule.
    env, candidates, labels = rules
    more = [candidate("f1", "s9", "demo", signals=["frustration"]),
            candidate("x1", "s8", "demo", signals=["explicit"])]  # fmt: skip
    labels = {**labels,
              "f1": keep("rename-the-button", rule="Rename the save button.", frustrated=True),
              "x1": keep("utc-dates", rule="Write dates in UTC.")}  # fmt: skip
    found = workshop.load(env.config, candidates=candidates + more, labels=labels, findings=[])
    assert sorted(g.topic for g in found.uncovered) == ["tests-before-claims", "utc-dates"]


def test_the_material_holds_the_instructions_agents_already_follow(work):
    env, found = work
    (env.claude_home / "CLAUDE.md").write_text("Never add a co-author trailer.\n")
    repo = env.root / "Repos" / "demo"
    repo.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("Run the tests before saying they pass.\n")
    skill = env.claude_home / "skills" / "notes"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: notes\n---\nWrite notebooks plainly.\n")
    (env.root / "agents" / "skills").mkdir(parents=True)
    (env.root / "agents" / "skills" / "notes").symlink_to(skill)  # the same skill, linked
    folder = env.root / "run" / "dossier"
    workshop.write_dossier(folder, found, config=env.config)
    index = (folder / "instructions" / "INDEX.md").read_text()
    copied = {p.relative_to(folder / "instructions").as_posix(): p.read_text()
              for p in (folder / "instructions").rglob("*") if p.is_file() and p.name != "INDEX.md"}  # fmt: skip
    assert copied["claude/CLAUDE.md"].startswith("Never add")
    assert copied["repos/demo/AGENTS.md"].startswith("Run the tests")
    assert sum("Write notebooks plainly" in t for t in copied.values()) == 1  # linked once
    assert str(repo / "AGENTS.md") in index and "repos/demo/AGENTS.md" in index


def test_every_brief_says_to_check_the_instructions_and_to_generalise(work):
    env, found = work
    for role in ("designer", "consolidator", "critic", "synthesis", "solo"):
        text = workshop.brief(workshop.Agent(f"claude-{role}", role, "claude", 1))
        assert "instructions/" in text and "INDEX.md" in text, role
        assert "one session" in text or "one incident" in text, role


def set_aside(env, rule_id="tests-before-claims", text="Run the tests before saying they pass."):
    from ax import learn

    profile.add(env.config, rule_id, rule=text, status="proposed")
    learn.reject(env.config, rule_id)  # "not now"


def test_a_lesson_a_set_aside_rule_covers_does_not_reach_the_designers(rules):
    env, candidates, labels = rules
    set_aside(env)
    found = workshop.load(env.config, candidates=candidates, labels=labels, findings=[])
    assert [g.topic for g in found.uncovered] == []
    assert [r.id for r in found.set_aside] == ["tests-before-claims"]


def test_the_material_lists_set_aside_rules_as_the_user_s_to_bring_back(work):
    env, _ = work
    set_aside(env)
    found = workshop.load(env.config, candidates=[], labels={}, findings=[])
    folder = env.root / "run" / "dossier"
    workshop.write_dossier(folder, found)
    rules_md = (folder / "rules.md").read_text()
    section = rules_md.split("# Set aside by the user for now", 1)[1]
    assert "tests-before-claims" in section and "Run the tests" in section
    assert "set aside" in workshop.brief(
        workshop.Agent("claude-designer-1", "designer", "claude", 1)
    )


def test_a_proposal_that_repeats_a_set_aside_rule_is_skipped(work):
    env, _ = work
    set_aside(env)
    found = workshop.load(env.config, candidates=[], labels={}, findings=[])
    found.evidence = {"c1": ("s1", False), "c2": ("s2", False)}
    same_id = proposal()
    same_words = proposal(id="claims-need-runs", rule="Run the tests before saying that they pass.")
    written = workshop.write(env.config, outcome_of(same_id, same_words), found, now=NOW)
    skipped = dict(written.skipped)
    assert written.proposals == []
    assert (
        "set aside" in skipped["tests-before-claims"] and "set aside" in skipped["claims-need-runs"]
    )


# How many agents


def load_of(design_items=0, proposals=0, active=4):
    return workshop.Load(
        proposals=[profile.Rule(f"p{i}", "x", status="proposed") for i in range(proposals)],
        flagged=[],
        active=[profile.Rule(f"a{i}", "x") for i in range(active)],
        uncovered=[object()] * design_items,
        conflicts=[],
    )


def roles(team):
    return [(a.role, a.tool) for a in team.agents]


def test_a_full_team_designs_consolidates_critiques_and_synthesises():
    team = workshop.team(load_of(design_items=6), [opening("claude", 40, 10)], SETTINGS)
    assert roles(team).count(("designer", "claude")) == 3  # all in: two items each
    assert ("consolidator", "claude") in roles(team)
    assert roles(team)[-2:] == [("critic", "claude"), ("synthesis", "claude")]
    assert sorted({a.phase for a in team.agents}) == [1, 2, 3]
    assert sum(len(a.items) for a in team.agents if a.role == "designer") == 6


def test_the_team_shrinks_to_the_allowance_and_widens_batches():
    # 15% left minus the 3% floor is 12%: three agents at the assumed 4% each.
    team = workshop.team(load_of(design_items=6), [opening("claude", 85, 4)], SETTINGS)
    assert roles(team) == [("designer", "claude"), ("critic", "claude"),
                           ("synthesis", "claude")]  # fmt: skip
    assert len(team.agents[0].items) == 6 and team.agents[0].consolidates


def test_one_or_two_agents_of_allowance_get_a_single_solo_agent():
    team = workshop.team(load_of(design_items=4), [opening("codex", 90, 6)], SETTINGS)
    assert roles(team) == [("solo", "codex")]
    assert team.agents[0].consolidates and len(team.agents[0].items) == 4


def test_both_tools_spare_split_the_design_and_each_critiques():
    both = [opening("claude", 40, 10), opening("codex", 20, 8)]
    team = workshop.team(load_of(design_items=8), both, SETTINGS)
    designers = [a.tool for a in team.agents if a.role == "designer"]
    assert set(designers) == {"claude", "codex"}
    assert sorted(a.tool for a in team.agents if a.role == "critic") == ["claude", "codex"]
    [synthesis] = [a for a in team.agents if a.role == "synthesis"]
    assert synthesis.tool == "codex"  # the larger allowance above the floor
    assert len(team.agents) <= SETTINGS.max_agents


def test_nothing_to_work_on_means_no_team():
    team = workshop.team(load_of(active=1), [opening("claude", 40, 10)], SETTINGS)
    assert team.agents == [] and "nothing" in team.reason


def test_no_spare_window_means_no_team():
    team = workshop.team(load_of(design_items=3), [opening("claude", 40, 30)], SETTINGS)
    assert team.agents == [] and "no window" in team.reason


def test_settings_come_from_the_workshop_section(env):
    config_path = env.root / "workshop.toml"
    config_path.write_text(env.config_path.read_text() + "[workshop]\nfloor = 5\nmax_agents = 4\n"
                           "enabled = false\n")  # fmt: skip
    from ax.config import load

    found = workshop.settings(load(config_path))
    assert (found.floor, found.max_agents, found.enabled) == (5, 4, False)
    assert found.effort == "high" and found.codex_model == "gpt-6.1-sol"


# Running the team


DRAFT = (
    '{"drafts": [{"key": "d1", "kind": "new", "id": "tests-before-claims", '
    '"rule": "Run the tests before saying they pass.", "scope": "global", '
    '"level": "advice", "replaces": [], "evidence": ["c1"], "why": "Twice corrected."}]}'
)
VERDICTS = (
    '```json\n{"verdicts": [{"draft": "d1", "verdict": "keep", "why": "Well supported."}]}\n```'
)
FINAL = (
    'Here it is:\n{"proposals": [{"kind": "new", "id": "tests-before-claims", '
    '"rule": "Run the tests before saying they pass.", "scope": "global", "level": "advice", '
    '"replaces": [], "evidence": ["c1", "c2"], "why": "Corrected twice.", '
    '"pattern": "Claiming tests pass without running them.", "checked": ["instructions/INDEX.md"]}], '
    '"summary": "One rule."}'
)


class FakeRunner:
    """Answers by role; an agent in `hang` runs until stopped."""

    def __init__(self, answers=None, hang=()):
        self.answers = {"designer": DRAFT, "consolidator": DRAFT, "critic": VERDICTS,
                        "synthesis": FINAL, "solo": FINAL, **(answers or {})}  # fmt: skip
        self.hang, self.started, self.stopped, self.briefs = set(hang), [], [], {}

    def start(self, agent, brief, folder):
        self.started.append(agent.key)
        self.briefs[agent.key] = brief
        return agent

    def done(self, agent):
        return agent.key not in self.hang or agent.key in self.stopped

    def stop(self, agent):
        self.stopped.append(agent.key)

    def result(self, agent):
        if agent.key in self.stopped:
            return "stopped", "", 0.5
        return "completed", self.answers[agent.role], 1.25


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def readings_of(*steps):
    """Usage readings in turn; the last one repeats."""
    state = {"n": 0}

    def read():
        step = steps[min(state["n"], len(steps) - 1)]
        state["n"] += 1
        return step

    return read


def plain(claude=40, codex=None, balance=500.0):
    windows = [weekly("claude", claude, 10)]
    if codex is not None:
        windows.append(weekly("codex", codex, 8))
    credits = usage.Credits("codex", balance, False, True, NOW, "fresh")
    return windows, credits


@pytest.fixture
def work(rules):
    env, candidates, labels = rules
    return env, workshop.load(env.config, candidates=candidates, labels=labels, findings=[])


def supervise(env, crew, work, runner, readings, **kw):
    clock = Clock()
    return workshop.supervise(
        env.config, crew, work, SETTINGS, runner=runner, readings=readings,
        folder=env.root / "run", clock=clock, sleep=clock.sleep, interval=60, **kw,
    )  # fmt: skip


def test_the_team_runs_phase_by_phase_and_each_phase_sees_the_last(work):
    env, found = work
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    runner = FakeRunner()
    outcome = supervise(env, crew, found, runner, readings_of(plain()))
    phases = [next(a.phase for a in crew.agents if a.key == k) for k in runner.started]
    assert phases == sorted(phases) and phases[-1] == 3
    critic = next(k for k in runner.started if "critic" in k)
    assert "Run the tests before saying they pass." in runner.briefs[critic]  # the drafts
    synthesis = next(k for k in runner.started if "synthesis" in k)
    assert "Well supported." in runner.briefs[synthesis]  # the critiques
    assert [p["id"] for p in outcome.proposals] == ["tests-before-claims"]
    assert outcome.summary == "One rule." and outcome.stopped is None
    assert all(r.status == "completed" for r in outcome.results)
    assert (env.root / "run" / "dossier" / "rules.md").exists()


def test_every_brief_carries_the_rules_its_items_and_the_answer_format(work):
    env, found = work
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    runner = FakeRunner()
    supervise(env, crew, found, runner, readings_of(plain()))
    designer = next(k for k in runner.started if "designer" in k)
    brief = runner.briefs[designer]
    assert "rules.md" in brief and '"drafts"' in brief and "Do not edit" in brief
    assert "tests-before-claims" in brief or "bootstrap" in brief or "explicit-paths" in brief


def test_agents_stop_when_their_tool_reaches_its_floor(work):
    env, found = work
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    first = next(a.key for a in crew.agents if a.phase == 1)
    runner = FakeRunner(hang={first})
    outcome = supervise(env, crew, found, runner, readings_of(plain(), plain(), plain(claude=98)))
    assert first in runner.stopped
    assert "floor" in outcome.stopped and outcome.proposals == []
    assert not any("synthesis" in k for k in runner.started)


def test_codex_agents_stop_the_moment_credits_are_spent(work):
    env, found = work
    crew = workshop.team(found, [opening("codex", 20, 8)], SETTINGS)
    first = next(a.key for a in crew.agents if a.phase == 1)
    runner = FakeRunner(hang={first})
    outcome = supervise(env, crew, found, runner,
                        readings_of(plain(codex=20), plain(codex=20),
                                    plain(codex=21, balance=499.5)))  # fmt: skip
    assert first in runner.stopped and "credits" in outcome.stopped


def test_a_stop_request_stops_every_agent(work):
    env, found = work
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    runner = FakeRunner(hang={a.key for a in crew.agents})
    stop = env.root / "stop.request"
    stop.parent.mkdir(exist_ok=True)
    stop.touch()
    outcome = supervise(env, crew, found, runner, readings_of(plain()), stop_file=stop)
    assert "asked to stop" in outcome.stopped
    assert set(runner.stopped) == set(runner.started)


def test_an_answer_without_json_is_recorded_and_the_rest_go_on(work):
    env, found = work
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    runner = FakeRunner(answers={"consolidator": "I looked and all is well."})
    outcome = supervise(env, crew, found, runner, readings_of(plain()))
    [bad] = [r for r in outcome.results if r.agent.role == "consolidator"]
    assert bad.status == "failed" and "JSON" in bad.error
    assert outcome.proposals  # the designers' drafts still reached the synthesis


def test_agents_that_no_longer_fit_the_allowance_are_skipped(work):
    env, found = work
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    # By launch time the window is at 90%: 7% above the floor fits one 4% agent.
    outcome = supervise(env, crew, found, FakeRunner(), readings_of(plain(claude=90)))
    skipped = [r for r in outcome.results if r.status == "skipped"]
    assert skipped and all("allowance" in r.error for r in skipped)
    assert len([r for r in outcome.results if r.status == "completed"]) == 1


def test_each_agent_s_share_of_the_window_is_measured(work):
    env, found = work
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    phase_one = len([a for a in crew.agents if a.phase == 1])
    readings = readings_of(*[plain(claude=40)] * 3, *[plain(claude=40 + 2 * phase_one)] * 50)
    outcome = supervise(env, crew, found, FakeRunner(), readings)
    assert outcome.share["claude"] == pytest.approx(2.0, abs=0.01)


def test_progress_goes_to_the_job_s_events_file(work, monkeypatch):
    env, found = work
    events = env.root / "events.jsonl"
    monkeypatch.setenv("AX_JOB_FILE", str(events))
    crew = workshop.team(found, [opening("claude", 40, 10)], SETTINGS)
    supervise(env, crew, found, FakeRunner(), readings_of(plain()))
    lines = [line for line in events.read_text().splitlines() if line]
    assert '"stage": "drafts"' in lines[0] and f'"total": {len(crew.agents)}' in lines[0]
    assert f'"done": {len(crew.agents)}' in lines[-1]


FAKE_WORKER = """
import json, sys, time
from pathlib import Path
args = sys.argv[1:]
run_dir = Path(args[args.index("--run-dir") + 1])
run_dir.mkdir(parents=True)
(run_dir / "argv.json").write_text(json.dumps(args))
brief = Path(args[args.index("--brief") + 1]).read_text()
status = "completed"
if "HANG" in brief:
    while not (run_dir / "stop.request").exists():
        time.sleep(0.05)
    status = "stopped"
(run_dir / "answer.md").write_text('{"drafts": []}')
(run_dir / "run.json").write_text(json.dumps({"status": status, "total_cost_usd_estimate": 1.5}))
"""


@pytest.fixture
def scripts(tmp_path):
    folder = tmp_path / "scripts"
    folder.mkdir()
    for name in ("worker.py", "codex_worker.py"):
        (folder / name).write_text(FAKE_WORKER)
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    return tmp_path, workshop.ProcessRunner(SETTINGS, dossier, scripts=folder)


def wait_for(runner, handle):
    import time

    deadline = time.monotonic() + 15
    while not runner.done(handle):
        assert time.monotonic() < deadline, "the worker never ended"
        time.sleep(0.05)


def test_the_process_runner_starts_each_tool_s_worker_with_its_model_and_effort(scripts):
    root, runner = scripts
    claude = workshop.Agent("claude-designer-1", "designer", "claude", 1)
    codex = workshop.Agent("codex-critic", "critic", "codex", 2)
    handles = [runner.start(a, "the brief", root / "agents" / a.key) for a in (claude, codex)]
    for handle in handles:
        wait_for(runner, handle)
    assert runner.result(handles[0]) == ("completed", '{"drafts": []}', 1.5)
    import json

    argv = json.loads((root / "agents" / "claude-designer-1" / "run" / "argv.json").read_text())
    assert argv[0] == "run" and argv[argv.index("--cwd") + 1] == str(root / "dossier")
    for flag, value in (("--model", "opus"), ("--effort", "high"), ("--profile", "read"),
                        ("--max-cost-usd", "40.0"), ("--timeout", "2700")):  # fmt: skip
        assert argv[argv.index(flag) + 1] == value
    argv = json.loads((root / "agents" / "codex-critic" / "run" / "argv.json").read_text())
    assert argv[0] == "run"
    for flag, value in (("--model", "gpt-6.1-sol"), ("--effort", "high"),
                        ("--permission", "read-only")):  # fmt: skip
        assert argv[argv.index(flag) + 1] == value
    assert (root / "agents" / "codex-critic" / "brief.md").read_text() == "the brief"


FAKE_CLAUDE = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if "--help" in args:
    print("--safe-mode --tools --max-budget-usd --output-format --session-id"); sys.exit()
if args == ["--version"]:
    print("2.1.283 (fake)"); sys.exit()
if args == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}))
    sys.exit()
sys.stdin.read()
sid = args[args.index("--session-id") + 1]
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}), flush=True)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": sid,
                  "result": '{"drafts": []}', "total_cost_usd": 1.5}), flush=True)
"""

FAKE_CODEX = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 9.9.9"); sys.exit()
if args == ["exec", "--help"]:
    print("--json --output-last-message --model"); sys.exit()
if args == ["login", "status"]:
    print("Logged in using ChatGPT"); sys.exit()
sys.stdin.read()
open(args[args.index("-o") + 1], "w").write('{"verdicts": []}')
print(json.dumps({"type": "thread.started",
                  "thread_id": "01a12649-f07b-72f0-aee7-76217e23999e"}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"output_tokens": 1}}), flush=True)
"""


def test_agents_start_through_the_real_delegation_scripts(tmp_path, monkeypatch):
    """The fake worker above takes any arguments; this runs the real worker scripts, with
    fake Claude and Codex programs, so a launch they would refuse fails here."""
    import os

    folder = tmp_path / "bin"
    folder.mkdir()
    for name, text in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
        (folder / name).write_text(text)
        (folder / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    runner = workshop.ProcessRunner(SETTINGS, dossier)
    claude = workshop.Agent("claude-designer-1", "designer", "claude", 1)
    codex = workshop.Agent("codex-critic", "critic", "codex", 2)
    handles = [runner.start(a, "the brief", tmp_path / "agents" / a.key) for a in (claude, codex)]
    for handle in handles:
        wait_for(runner, handle)
    logs = [(tmp_path / "agents" / a.key / "runner.log").read_text() for a in (claude, codex)]
    assert runner.result(handles[0]) == ("completed", '{"drafts": []}', 1.5), logs[0]
    assert runner.result(handles[1])[:2] == ("completed", '{"verdicts": []}'), logs[1]


def test_stopping_an_agent_asks_its_runner_to_stop(scripts):
    root, runner = scripts
    agent = workshop.Agent("claude-solo", "solo", "claude", 1)
    handle = runner.start(agent, "HANG until stopped", root / "agents" / agent.key)
    import time

    time.sleep(0.3)
    assert not runner.done(handle)
    runner.stop(handle)
    wait_for(runner, handle)
    assert runner.result(handle)[0] == "stopped"


# Writing what the team proposed


def proposal(**fields):
    return {"kind": "new", "id": "tests-before-claims", "rule": "Run the tests before saying they pass.",
            "scope": "global", "level": "advice", "replaces": [], "evidence": ["c1", "c2"],
            "why": "Corrected twice.", "pattern": "Claiming tests pass without running them.",
            **fields}  # fmt: skip


def outcome_of(*proposals, drafts=(), summary="Two rules.", keep=(), withdraw=(), warnings=()):
    found = workshop.Outcome(proposals=list(proposals), drafts=list(drafts), summary=summary,
                             keep=list(keep), withdraw=list(withdraw), warnings=list(warnings))  # fmt: skip
    found.results = [
        workshop.AgentResult(
            workshop.Agent("claude-synthesis", "synthesis", "claude", 3), "completed", cost=2.5
        )
    ]
    found.used_before, found.used_after = {"claude": 40.0}, {"claude": 52.0}
    return found


def test_valid_proposals_become_rule_notes_and_a_report(work):
    env, found = work
    written = workshop.write(env.config, outcome_of(
        proposal(),
        proposal(kind="merge", id="clean-changes", rule="Change only what the task needs.",
                 replaces=["unrelated-files", "say-less"]),
    ), found, now=NOW)  # fmt: skip
    rules = {r.id: r for r in profile.load_rules(env.config)}
    new = rules["tests-before-claims"]
    assert new.status == "proposed" and new.extra["source"] == "workshop"
    assert new.extra["workshop"] == written.report.stem
    assert rules["clean-changes"].extra["replaces"] == ["unrelated-files", "say-less"]
    assert "Replaces unrelated-files, say-less" in rules["clean-changes"].why
    assert written.proposals == ["tests-before-claims", "clean-changes"]
    report = written.report.read_text()
    assert written.report.parent == env.vault / "Workshops"
    assert "Two rules." in report and "[[Profile/rules/clean-changes]]" in report
    assert "claude-synthesis" in report and "40% → 52%" in report


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        (proposal(id="Not An Id"), "id"),
        (proposal(rule=""), "rule"),
        (proposal(rule="x" * 400), "rule"),
        (proposal(scope="planet:earth"), "scope"),
        (proposal(kind="vibe"), "kind"),
        (proposal(kind="retire", id="nope"), "no active rule"),
    ],
)
def test_malformed_proposals_are_skipped_with_a_reason(work, bad, why):
    env, found = work
    written = workshop.write(env.config, outcome_of(bad), found, now=NOW)
    assert written.proposals == [] and why in written.skipped[0][1]
    assert why in written.report.read_text()


def test_an_id_that_is_taken_gets_a_fresh_one_and_existing_notes_stay(work):
    env, found = work
    written = workshop.write(env.config, outcome_of(
        proposal(kind="rewrite", id="bootstrap", rule="Refresh with scripts/bootstrap_dev.py.",
                 replaces=["bootstrap"]),
    ), found, now=NOW)  # fmt: skip
    assert written.proposals == ["bootstrap-2"]
    rules = {r.id: r for r in profile.load_rules(env.config)}
    assert (
        rules["bootstrap"].status == "active"
        and rules["bootstrap"].rule == "Use the bootstrap script."
    )


def test_a_retirement_is_put_to_the_user_on_the_rule_itself(work):
    env, found = work
    written = workshop.write(env.config, outcome_of(
        proposal(kind="retire", id="explicit-paths", rule="", why="Covered by clean-changes."),
    ), found, now=NOW)  # fmt: skip
    assert written.retire == ["explicit-paths"]
    rule = next(r for r in profile.load_rules(env.config) if r.id == "explicit-paths")
    assert rule.status == "active" and rule.extra["workshop"]["suggest"] == "retire"


def test_unreviewed_drafts_are_written_when_no_synthesis_ran(work):
    env, found = work
    stopped = outcome_of(drafts=[{**proposal(), "key": "d1"}], summary="")
    stopped.stopped = "claude reached its 3% floor"
    written = workshop.write(env.config, stopped, found, now=NOW)
    assert written.proposals == ["tests-before-claims"]
    assert "unreviewed" in written.report.read_text()


def test_at_most_twelve_proposals_are_written(work):
    env, found = work
    many = [proposal(id=f"rule-{n}", rule=f"Rule number {n} says something.") for n in range(15)]
    written = workshop.write(env.config, outcome_of(*many), found, now=NOW)
    assert len(written.proposals) == 12 and len(written.skipped) == 3


def test_accepting_a_workshop_proposal_retires_or_drops_what_it_replaces(work):
    from ax import learn

    env, found = work
    workshop.write(env.config, outcome_of(
        proposal(kind="merge", id="clean-changes", rule="Change only what the task needs.",
                 replaces=["unrelated-files", "say-less"]),
    ), found, now=NOW)  # fmt: skip
    learn.accept(env.config, "clean-changes")
    rules = {r.id: r for r in profile.load_rules(env.config)}
    assert rules["clean-changes"].status == "active"
    assert rules["unrelated-files"].status == "retired"
    assert rules["say-less"].status == "not-now"  # a proposal it replaced is rejected, kept
    assert rules["say-less"].superseded_by == "clean-changes"
    assert rules["unrelated-files"].superseded_by == "clean-changes"
    assert "rules workshop" in rules["say-less"].decided_by  # off the list when written
    learn.restore(env.config, "clean-changes")  # changing your mind about the acceptance
    rules = {r.id: r for r in profile.load_rules(env.config)}
    assert rules["clean-changes"].status == "proposed"
    assert (
        rules["unrelated-files"].status == "active" and not rules["unrelated-files"].superseded_by
    )
    assert rules["say-less"].status == "not-now"  # the workshop's withdrawal stands


def test_the_final_list_keeps_replaces_or_withdraws_every_waiting_proposal(work):
    env, _ = work
    profile.add(env.config, "tabs", rule="Use tabs.", status="proposed")
    profile.add(env.config, "old-idea", rule="Say it twice.", status="proposed",
                extra={"source": "workshop", "workshop": "2026-10-25 1811 claude"})  # fmt: skip
    found = workshop.load(env.config, candidates=[], labels={}, findings=[])
    written = workshop.write(env.config, outcome_of(
        proposal(kind="merge", id="clean-changes", rule="Change only what the task needs.",
                 replaces=["say-less"], evidence=["say-less"]),
        keep=["tabs"],
        withdraw=[{"id": "old-idea", "why": "The ax skill already says it."}],
    ), found, now=NOW)  # fmt: skip
    rules = {r.id: r for r in profile.load_rules(env.config)}
    assert rules["clean-changes"].status == "proposed" and rules["tabs"].status == "proposed"
    assert rules["say-less"].status == "not-now"
    assert rules["say-less"].superseded_by == "clean-changes"
    assert "rules workshop" in rules["say-less"].decided_by
    assert rules["old-idea"].status == "not-now" and not rules["old-idea"].superseded_by
    assert "The ax skill already says it." in rules["old-idea"].why
    report = written.report.read_text()
    assert "## Kept" in report and "## Withdrawn" in report and "tabs" in report


def test_proposals_the_final_agent_left_out_stay_and_are_named(work):
    env, found = work
    written = workshop.write(env.config, outcome_of(proposal()), found, now=NOW)
    assert (
        next(r for r in profile.load_rules(env.config) if r.id == "say-less").status == "proposed"
    )
    assert "## Not reviewed" in written.report.read_text()


def test_a_new_rule_must_rest_on_two_sessions_or_a_standing_request(work):
    env, found = work
    one = proposal(id="one-session", evidence=["c1"])
    no_pattern = proposal(id="no-pattern", pattern="")
    found.evidence["c5"] = ("s5", True)  # c5 asked to keep it "from now on"
    standing = proposal(id="standing", rule="Rename buttons in the design file.", evidence=["c5"])
    written = workshop.write(env.config, outcome_of(one, no_pattern, standing, proposal()),
                             found, now=NOW)  # fmt: skip
    skipped = dict(written.skipped)
    assert "one session" in skipped["one-session"] and "pattern" in skipped["no-pattern"]
    assert sorted(written.proposals) == ["standing", "tests-before-claims"]


def test_warnings_about_instructions_reach_the_report_and_the_app(work):
    from ax import app

    env, found = work
    warning = {"file": "/Users/me/Repos/demo/AGENTS.md",
               "problem": "Says to work on branches, but you commit on main.",
               "suggestion": "Say to commit on main.", "evidence": ["c1", "c2"]}  # fmt: skip
    written = workshop.write(env.config, outcome_of(proposal(), warnings=[warning]), found, now=NOW)
    report = written.report.read_text()
    assert "## Instructions to check" in report and "/Users/me/Repos/demo/AGENTS.md" in report
    state = app.now_state(env.config, usage_of=lambda config: [])
    [item] = [w for w in state["waiting"] if w["kind"] == "instruction"]
    assert item["title"].startswith("/Users/me/Repos/demo/AGENTS.md")
    assert "commit on main" in item["detail"] and item["actions"] == ["dismiss"]
    app.act(env.config, "instruction-dismiss", {"id": item["id"]})
    state = app.now_state(env.config, usage_of=lambda config: [])
    assert not [w for w in state["waiting"] if w["kind"] == "instruction"]


def test_the_final_brief_names_every_waiting_proposal_to_settle(work):
    env, found = work
    final = workshop.Agent("claude-synthesis", "synthesis", "claude", 3)
    text = workshop.brief(final, waiting=["say-less", "tabs"])
    assert "say-less" in text and "tabs" in text
    assert '"keep"' in text and '"withdraw"' in text and '"warnings"' in text


def test_a_run_does_not_start_again_on_its_own_proposals(work):
    env, found = work
    workshop.remember(env.config, [opening("claude", 40, 10)], found, {})
    workshop.write(env.config, outcome_of(proposal()), found, now=NOW)  # the run's own output
    never = lambda config, key, label: pytest.fail("started on its own proposals")  # noqa: E731
    assert workshop.maybe_start(env.config, readings=spare(), launch=never, now=NOW) is None


def test_the_app_puts_a_suggested_retirement_up_for_review_and_keep_clears_it(work):
    from ax import app, learn_life

    env, found = work
    workshop.write(env.config, outcome_of(
        proposal(kind="retire", id="explicit-paths", rule="", why="Covered by clean-changes."),
    ), found, now=NOW)  # fmt: skip
    state = app.now_state(env.config, usage_of=lambda c: [])
    review = next(w for w in state["waiting"] if w["id"] == "explicit-paths")
    assert review["kind"] == "review" and "workshop suggests retiring" in review["detail"]
    learn_life.keep(env.config, "explicit-paths")
    rule = next(r for r in profile.load_rules(env.config) if r.id == "explicit-paths")
    assert "workshop" not in rule.extra


# Starting by itself, and the commands


def spare():
    return readings_of(plain(claude=40))


def test_after_a_sync_a_spare_window_with_work_waiting_starts_a_detached_run(work):
    from ax import jobs

    env, _ = work
    launched = []

    def launch(config, key, label):
        launched.append((key, label))
        jobs.new(config, key, label=label)  # what the real launch registers

    said = workshop.maybe_start(env.config, readings=spare(), launch=launch, now=NOW)
    [(key, label)] = launched
    assert key.startswith("workshop-") and "rules workshop" in label.lower()
    assert said and key in said
    # While it runs, another sync starts nothing.
    assert workshop.maybe_start(env.config, readings=spare(), launch=launch, now=NOW) is None
    assert len(launched) == 1


def test_nothing_starts_without_a_spare_window_or_when_turned_off(work, monkeypatch):
    env, _ = work
    never = lambda config, key, label: pytest.fail("started a run")  # noqa: E731
    late = readings_of(plain(claude=40))
    assert workshop.maybe_start(env.config, readings=readings_of(([weekly("claude", 40, 30)], None)),
                                launch=never, now=NOW) is None  # fmt: skip
    off = workshop.Settings(enabled=False)
    monkeypatch.setattr(workshop, "settings", lambda config: off)
    assert workshop.maybe_start(env.config, readings=late, launch=never, now=NOW) is None


def test_a_window_is_not_worked_twice_on_the_same_items(work):
    env, found = work
    workshop.remember(env.config, [opening("claude", 40, 10)], found, {})
    never = lambda config, key, label: pytest.fail("started a run")  # noqa: E731
    assert workshop.maybe_start(env.config, readings=spare(), launch=never, now=NOW) is None
    profile.add(env.config, "brand-new", rule="Something new to weigh.", status="proposed")
    started = []
    workshop.maybe_start(env.config, readings=spare(), now=NOW,
                         launch=lambda c, k, label: started.append(k))  # fmt: skip
    assert started


def test_a_window_keeps_its_key_when_its_reported_reset_moves_a_minute():
    base = opening("claude", 40, 10)
    moved = workshop.Opening(
        **{**base.__dict__, "resets_at": base.resets_at - timedelta(minutes=1)}
    )
    assert workshop._window_key(moved) == workshop._window_key(base)


def test_a_dry_run_writes_the_material_and_briefs_and_launches_nothing(work):
    env, _ = work
    found = workshop.run(env.config, dry_run=True, readings=spare(), now=NOW,
                         runner=FakeRunner(answers={"designer": "should not run"}))  # fmt: skip
    folder = env.config.data / "workshop" / "runs" / found["folder"].split("/")[-1]
    assert (folder / "dossier" / "rules.md").exists()
    briefs = sorted(p.name for p in (folder / "briefs").iterdir())
    assert briefs == sorted(f"{a['key']}.md" for a in found["team"])
    assert found["dry_run"] and found["team"] and "item(s) to design" in found["reason"]


def test_a_run_supervises_writes_tells_the_user_and_remembers_the_window(work, rules, monkeypatch):
    from ax import learn

    env, _ = work
    _, candidates, labels = rules
    monkeypatch.setattr(learn, "load_candidates", lambda config: candidates)  # what sync saved
    monkeypatch.setattr(learn, "load_labels", lambda config: labels)
    told, clock = [], Clock()
    found = workshop.run(env.config, readings=spare(), runner=FakeRunner(), now=NOW,
                         clock=clock, sleep=clock.sleep,
                         notify=lambda title, message: told.append(title))  # fmt: skip
    assert found["proposals"] == ["tests-before-claims"]
    assert told == ["Rules workshop started", "Rules workshop finished"]
    state = workshop.load_state(env.config)
    [window] = state["windows"].values()
    # What the run read from disk: the flag and the waiting proposal.
    assert window["runs"] == 1 and {"flag:bootstrap", "proposal:say-less"} <= set(window["covered"])


class FailingRunner(FakeRunner):
    def result(self, agent):
        return "failed", "", None


def test_a_run_whose_agents_all_fail_leaves_the_work_open_and_says_it_failed(work):
    env, _ = work
    told, clock = [], Clock()
    found = workshop.run(env.config, readings=spare(), runner=FailingRunner(), now=NOW,
                         clock=clock, sleep=clock.sleep,
                         notify=lambda title, message: told.append(title))  # fmt: skip
    assert found["failed"] and found["proposals"] == []
    assert told == ["Rules workshop started", "Rules workshop failed"]
    windows = workshop.load_state(env.config).get("windows", {})
    assert all(not w["covered"] for w in windows.values())
    started = []
    workshop.maybe_start(env.config, readings=spare(), now=NOW,
                         launch=lambda c, k, label: started.append(k))  # fmt: skip
    assert started  # the next sync tries again


def test_a_failed_run_fails_its_job(work, monkeypatch):
    from typer.testing import CliRunner

    from ax.cli import app as cli

    env, _ = work
    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setattr(workshop, "run", lambda config, dry_run=False: {
        "team": [{"key": "claude-solo", "role": "solo", "items": 3, "consolidates": False}],
        "reason": "one agent", "folder": "f", "dry_run": False, "proposals": [], "retire": [],
        "report": "r.md", "stopped": None, "failed": True})  # fmt: skip
    result = CliRunner().invoke(cli, ["workshop", "run"])
    assert result.exit_code == 1 and "no agent finished" in result.output


def test_stop_asks_a_running_workshop_to_stop(env):
    workshop.stop(env.config)
    assert workshop.stop_file(env.config).exists()


def test_the_commands(work, monkeypatch):
    import json

    from typer.testing import CliRunner

    from ax.cli import app as cli

    env, _ = work
    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setattr(workshop, "_readings", lambda config: spare()())
    monkeypatch.setattr(workshop, "_now", lambda: NOW)
    result = CliRunner().invoke(cli, ["workshop", "status", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["openings"][0]["ok"] and data["team"]
    result = CliRunner().invoke(cli, ["workshop", "run", "--dry-run"])
    assert result.exit_code == 0 and "dossier" in result.output
    result = CliRunner().invoke(cli, ["workshop", "stop"])
    assert result.exit_code == 0 and workshop.stop_file(env.config).exists()


def test_sync_checks_whether_the_workshop_should_start(env, monkeypatch):
    from typer.testing import CliRunner

    from ax.cli import app as cli

    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setattr(workshop, "maybe_start", lambda config: "started workshop-x: 3 agents")
    result = CliRunner().invoke(cli, ["sync"])
    assert "rules workshop: started workshop-x" in result.output

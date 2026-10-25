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
    config = env.config
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
    '"replaces": [], "evidence": ["c1"], "why": "Corrected twice."}], "summary": "One rule."}'
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
    assert argv[0] == "start" and argv[argv.index("--cwd") + 1] == str(root / "dossier")
    for flag, value in (("--model", "opus"), ("--effort", "high"), ("--profile", "read"),
                        ("--max-cost-usd", "40.0"), ("--timeout", "2700")):  # fmt: skip
        assert argv[argv.index(flag) + 1] == value
    argv = json.loads((root / "agents" / "codex-critic" / "run" / "argv.json").read_text())
    assert argv[0] == "run"
    for flag, value in (("--model", "gpt-6.1-sol"), ("--effort", "high"),
                        ("--permission", "read-only")):  # fmt: skip
        assert argv[argv.index(flag) + 1] == value
    assert (root / "agents" / "codex-critic" / "brief.md").read_text() == "the brief"


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

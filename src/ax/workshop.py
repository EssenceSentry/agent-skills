"""The rules workshop: strong agents spend a weekly window's spare allowance on the rules.

A weekly window that ends its week with allowance left resets it unused. In a window's
last day, when it is spare by the usage band's rule, ax starts agents on that tool's own
allowance (Opus 5.5 for Claude, Sol 6.1 for Codex), as many as the rule work waiting and
the allowance above a small floor allow. It needs no approval per run: the user set this
policy. The agents only read and answer in JSON; ax validates what they propose and
writes it as rule proposals and a report note, so accepting stays with the user. Codex
credits are never spent.
"""

import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ax import learn, profile

TOOLS = ("claude", "codex")
EVEN_PER_DAY = 100 / 7  # an even pace spends a seventh of a weekly window a day
SPARE_FACTOR = 1.5  # more than this many even days a day is allowance that resets unused
LAST_DAY = timedelta(hours=24)
MIN_TIME = timedelta(minutes=45)  # closer to the reset than this, a run can't finish
ITEMS_PER_DESIGNER = 2  # all in: no designer gets fewer than this while room allows


@dataclass(frozen=True)
class Settings:
    enabled: bool = True
    floor: float = 3.0  # percent of the window left untouched
    max_agents: int = 8
    agent_share: float = 4.0  # percent of a weekly window one agent run uses, until measured
    timeout: int = 2700  # seconds one agent may run
    claude_model: str = "opus"
    codex_model: str = "gpt-6.1-sol"
    effort: str = "high"
    claude_budget_usd: float = 40.0  # the delegation runner's cost cap for one agent


def settings(config) -> Settings:
    raw = dict(getattr(config, "workshop", {}) or {})
    known = {k: raw[k] for k in Settings.__dataclass_fields__ if k in raw}
    return Settings(**known)


# When a window qualifies


@dataclass
class Opening:
    tool: str
    ok: bool
    reason: str
    used: float | None = None
    left: float = 0.0
    hours_left: float = 0.0
    per_day: float = 0.0
    budget: float = 0.0  # percent of the window above the floor
    resets_at: datetime | None = None


def _opening(tool: str, window, s: Settings, now: datetime) -> Opening:
    if window is None or window.used is None:
        return Opening(tool, False, "no reading of its weekly window")
    if window.status != "fresh":
        return Opening(tool, False, f"a {window.status.replace('_', ' ')} reading", window.used)
    left = max(0.0, 100 - window.used)
    found = Opening(tool, False, "", window.used, left, resets_at=window.resets_at)
    if window.resets_at is None:
        found.reason = "no reset time"
        return found
    remaining = window.resets_at - now
    found.hours_left = remaining.total_seconds() / 3600
    if remaining > LAST_DAY:
        found.reason = f"resets in {found.hours_left / 24:.1f} days: not its last day"
        return found
    if remaining < MIN_TIME:
        found.reason = "too close to the reset for a run"
        return found
    found.per_day = left / (found.hours_left / 24)
    if found.per_day <= EVEN_PER_DAY * SPARE_FACTOR:
        found.reason = f"not spare: {found.per_day:.0f}% a day left"
        return found
    found.budget = left - s.floor
    if found.budget < s.agent_share:
        found.reason = f"too little above the {s.floor:g}% floor for an agent"
        return found
    found.ok = True
    found.reason = (
        f"{left:.0f}% left with {found.hours_left:.1f} h to the reset: "
        f"{found.budget:.0f}% to spend above the floor"
    )
    return found


def openings(windows, s: Settings, now: datetime) -> list[Opening]:
    """Each tool's main weekly window, judged; Fable's and the 5-hour session don't count."""
    by_tool = {w.provider: w for w in windows if w.name == "weekly"}
    return [_opening(tool, by_tool.get(tool), s, now) for tool in TOOLS]


# What there is to work on


@dataclass
class Load:
    proposals: list
    flagged: list
    active: list
    uncovered: list  # learn.Group evidence no rule covers
    conflicts: list  # profile.Finding of kind "conflict"

    @property
    def design_items(self) -> list:
        """What needs designing: a lesson no rule covers, a flagged rule, a conflict."""
        return [*self.uncovered, *self.flagged, *self.conflicts]

    @property
    def consolidation(self) -> bool:
        return len(self.active) + len(self.proposals) >= 2

    @property
    def empty(self) -> bool:
        return not (self.design_items or self.proposals) and not self.consolidation


def load(config, *, candidates=None, labels=None, findings=None) -> Load:
    rules = profile.load_rules(config, problems=[])
    active = [r for r in rules if r.status == "active"]
    proposals = [r for r in rules if r.status == "proposed"]
    candidates = learn.load_candidates(config) if candidates is None else candidates
    labels = learn.load_labels(config) if labels is None else labels
    known = active + proposals
    uncovered = [
        g
        for g in learn.groups(candidates, labels)
        if g.support >= learn.MIN_SUPPORT and not any(learn._matches(g, r) for r in known)
    ]
    if findings is None:
        findings = profile.check(config)
    return Load(
        proposals=proposals,
        flagged=[r for r in active if r.review],
        active=active,
        uncovered=uncovered,
        conflicts=[f for f in findings if f.kind == "conflict"],
    )


# How many agents


@dataclass
class Agent:
    key: str
    role: str  # designer, consolidator, critic, synthesis or solo
    tool: str
    phase: int  # 1 drafts, 2 critiques, 3 the final proposals
    items: list = field(default_factory=list)
    consolidates: bool = False


@dataclass
class Team:
    agents: list
    reason: str


def _assign(capacity: dict, prefer: str | None = None) -> str | None:
    """The tool with the most room left (or `prefer`, while it has room); takes one slot."""
    if prefer and capacity.get(prefer, 0) > 0:
        tool = prefer
    else:
        tool = max(capacity, key=lambda t: capacity[t], default=None)
        if tool is None or capacity[tool] <= 0:
            return None
    capacity[tool] -= 1
    return tool


def team(work: Load, found: list[Opening], s: Settings, *, share: float | None = None) -> Team:
    """Sized from the work and the allowance, going all in: as many designers as the room
    allows down to two items each, a consolidator, a critic per tool and a synthesis."""
    ready = [o for o in found if o.ok]
    if not ready:
        return Team([], "no window has spare allowance in its last day")
    if work.empty:
        return Team([], "nothing to work on: no proposals, flags or uncovered lessons")
    share = share or s.agent_share
    capacity = {o.tool: int(o.budget // share) for o in ready}
    biggest = max(ready, key=lambda o: o.budget).tool
    items = work.design_items
    total = min(sum(capacity.values()), s.max_agents)
    if total <= 2:
        tool = _assign(capacity, biggest)
        solo = Agent(f"{tool}-solo", "solo", tool, 1, list(items), work.consolidation)
        return Team([solo], f"room for {total} agent(s): one does all of it")
    critics = [t for t in TOOLS if capacity.get(t, 0) > 0]
    late = [Agent(f"{t}-critic", "critic", _assign(capacity, t), 2) for t in critics]
    late.append(Agent(f"{biggest}-synthesis", "synthesis", _assign(capacity, biggest), 3))
    room = total - len(late)
    early: list[Agent] = []
    separate = work.consolidation and items and room >= 2
    if work.consolidation and (separate or not items):
        tool = _assign(capacity, biggest)
        early.append(Agent(f"{tool}-consolidator", "consolidator", tool, 1, consolidates=True))
        room -= 1
    if items:
        designers = max(1, min(room, math.ceil(len(items) / ITEMS_PER_DESIGNER)))
        for n in range(designers):
            tool = _assign(capacity) or biggest
            early.append(Agent(f"{tool}-designer-{n + 1}", "designer", tool, 1,
                               items[n::designers]))  # fmt: skip
        if work.consolidation and not separate:
            early[-designers].consolidates = True
    reason = (
        f"{len(items)} item(s) to design and {len(work.proposals)} proposal(s) waiting; "
        f"allowance for {sum(int(o.budget // share) for o in ready)} agent(s) at {share:g}% each"
    )
    return Team(early + late, reason)


# The material and the briefs

PHASES = {1: "drafts", 2: "critiques", 3: "proposals"}
_DRAFT = (
    '{"key": "d1", "kind": "new|merge|rewrite|retire", "id": "kebab-case-id", '
    '"rule": "one sentence", "scope": "global or repo:NAME", "level": "advice|check|block", '
    '"replaces": ["rule ids"], "evidence": ["candidate or rule ids"], "why": "short reason"}'
)
_FORMATS = {
    "drafts": '{"drafts": [' + _DRAFT + "]}",
    "verdicts": '{"verdicts": [{"draft": "d1", "verdict": "keep|revise|drop", "why": "...", '
    '"revision": {...same fields as a draft, when revised}}]}',
    "proposals": '{"proposals": [' + _DRAFT.replace('"key": "d1", ', "") + '], "summary": "..."}',
}
_ANSWERS = {"designer": "drafts", "consolidator": "drafts", "critic": "verdicts",
            "synthesis": "proposals", "solo": "proposals"}  # fmt: skip
_COMMON = (
    "You are part of a rules workshop for the user's agent layer, ax. The rules are short "
    "instructions compiled into Claude Code and Codex; each one should prevent a correction "
    "the user has had to make, in words an agent can act on. The material is in this "
    "folder: rules.md (every active and proposed rule, with its evidence) and evidence.md "
    "(lessons no rule covers, flagged rules and conflicts). Read it. Do not edit anything, "
    "run commands that change files, or start other agents. Prefer fewer, sharper rules: "
    "merge overlapping ones, scope a rule to the repo it belongs to, and drop a rule the "
    "evidence does not support. Keep each rule to one sentence. Ids are kebab-case; reuse "
    "an existing id only to retire or rewrite that rule."
)
_ROLES = {
    "designer": "Design rules for the items below: one rule per real lesson, a rewrite for "
    "a flagged rule, a resolution for a conflict. Say which rules a draft replaces.",
    "consolidator": "Go through every rule in rules.md. Draft merges of rules that say the "
    "same thing, rewrites that make a rule clearer or narrower, and retirements of rules "
    "with no recent evidence or that another rule already covers.",
    "critic": "Judge every draft below against the evidence and the existing rules: keep it, "
    "revise it (give the revision) or drop it, with a reason. Drop drafts that duplicate a "
    "rule, rest on one session, or are too vague to act on.",
    "synthesis": "Write the final proposals from the drafts and the critiques below: apply "
    "every revision, drop what the critics dropped, settle disagreements, and keep at most "
    "twelve. Add a one-paragraph summary for the user.",
    "solo": "Do the whole workshop alone: design rules for the items below, consolidate the "
    "existing rules, criticise your own drafts, and write the final proposals (at most "
    "twelve) with a one-paragraph summary.",
}


def _item_line(item) -> str:
    if isinstance(item, learn.Group):
        sample = "; ".join(sorted({c["text"][:160] for c, _ in item.members})[:3])
        return (
            f"- lesson `{item.topic}`: {item.rule} (support {item.support}, "
            f"{len(item.sessions)} sessions, projects {', '.join(sorted(item.projects)) or '-'}; "
            f"candidates {', '.join(c['id'] for c, _ in item.members)}; said: {sample})"
        )
    if isinstance(item, profile.Rule):
        return f"- flagged rule `{item.id}`: {item.rule} (flag: {item.review})"
    if isinstance(item, profile.Finding):
        return f"- conflict on `{item.rule}`: {item.message}"
    return f"- {item}"


def _rule_block(rule) -> str:
    facts = ", ".join(
        f"{k} {v}"
        for k, v in (("status", rule.status), ("scope", rule.scope), ("level", rule.level),
                     ("maturity", rule.maturity), ("support", rule.support),
                     ("recurrences", rule.recurrences), ("last evidence", rule.last_evidence))
        if v not in (None, "")
    )  # fmt: skip
    why = (rule.why or "").strip().replace("\n", " ")[:900]
    return f"## {rule.id}\n{rule.rule}\n\n{facts}.\n\n{why}\n"


def write_dossier(folder, work: Load) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    rules = "\n".join(_rule_block(r) for r in [*work.active, *work.proposals])
    (folder / "rules.md").write_text(f"# Rules\n\n{rules or 'No rules yet.'}\n")
    evidence = "\n".join(_item_line(i) for i in work.design_items) or "Nothing uncovered."
    (folder / "evidence.md").write_text(f"# Evidence\n\n{evidence}\n")


def brief(agent: Agent, *, drafts=(), verdicts=()) -> str:
    answer = _ANSWERS[agent.role]
    parts = [_COMMON, "", f"Your part: {_ROLES[agent.role]}"]
    if agent.consolidates and agent.role in ("designer", "solo"):
        parts.append("Also consolidate the existing rules, as a consolidator would.")
    if agent.items:
        parts += ["", "Your items:", *(_item_line(i) for i in agent.items)]
    if drafts:
        parts += ["", "The drafts:", "```json", json.dumps(list(drafts), indent=1), "```"]
    if verdicts:
        parts += ["", "The critiques:", "```json", json.dumps(list(verdicts), indent=1), "```"]
    parts += ["", "Answer with one JSON object and nothing else, in this shape:", _FORMATS[answer]]
    return "\n".join(parts)


def parse(text: str) -> dict | None:
    """The JSON object in an agent's answer: the whole answer, a fenced block, or the span
    from the first brace to the last."""
    text = (text or "").strip()
    found = [text, *re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        found.append(text[start : end + 1])
    for piece in found:
        try:
            value = json.loads(piece)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


# Running the team


@dataclass
class AgentResult:
    agent: Agent
    status: str  # completed, failed, stopped or skipped
    answer: dict | None = None
    error: str | None = None
    cost: float | None = None


@dataclass
class Outcome:
    results: list = field(default_factory=list)
    drafts: list = field(default_factory=list)
    verdicts: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    summary: str = ""
    stopped: str | None = None
    share: dict = field(default_factory=dict)
    used_before: dict = field(default_factory=dict)
    used_after: dict = field(default_factory=dict)


def _used(windows) -> dict:
    return {w.provider: w.used for w in windows if w.name == "weekly" and w.used is not None}


def _resets(windows) -> dict:
    return {w.provider: w.resets_at for w in windows if w.name == "weekly" and w.resets_at}


def _progress(**fields) -> None:
    path = os.environ.get("AX_JOB_FILE")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps(fields) + "\n")


class _Run:
    def __init__(self, crew, s, runner, readings, folder, clock, sleep, interval, stop_file):
        self.crew, self.s, self.runner, self.readings = crew, s, runner, readings
        self.folder, self.clock, self.sleep, self.interval = folder, clock, sleep, interval
        self.stop_file = stop_file
        self.outcome = Outcome()
        self.launched: dict[str, int] = {}
        self.done = 0
        windows, credits = readings()
        self.base_used = _used(windows)
        self.base_balance = credits.balance if credits else None
        self.outcome.used_before = dict(self.base_used)
        self.burn: dict[str, list] = {}  # tool -> [percent seen, agents]

    def _room(self, tool: str, used: dict) -> float:
        """Percent left above the floor, less what launched agents haven't shown yet."""
        now_used = used.get(tool, 100.0)
        seen = now_used - self.base_used.get(tool, now_used)
        owed = max(0.0, self.launched.get(tool, 0) * self.s.agent_share - seen)
        return 100 - now_used - self.s.floor - owed

    def _stop_reason(self, windows, credits, tools: set) -> tuple[str | None, set]:
        if self.stop_file and self.stop_file.exists():
            return "asked to stop", tools
        used, resets = _used(windows), _resets(windows)
        for tool in sorted(tools):
            if used.get(tool, 0) >= 100 - self.s.floor:
                return f"{tool} reached its {self.s.floor:g}% floor", {tool}
            if tool in resets and self.clock() >= resets[tool]:
                return f"{tool}'s window reset", {tool}
        spent = (
            "codex" in tools
            and credits is not None
            and self.base_balance is not None
            and credits.balance is not None
            and credits.balance < self.base_balance - 1e-6
        )
        if spent:
            return "Codex began spending credits", {"codex"}
        return None, set()

    def phase(self, number: int, agents: list, brief_of) -> list:
        _progress(stage=PHASES[number], done=self.done, total=len(self.crew.agents))
        windows, credits = self.readings()
        reason, _ = self._stop_reason(windows, credits, {a.tool for a in agents})
        if reason:
            self.outcome.stopped = reason
            return []
        start_used, running, finished = _used(windows), [], []
        for agent in agents:
            if self._room(agent.tool, _used(windows)) < self.s.agent_share:
                self._finish(AgentResult(agent, "skipped", error="no allowance left for it"))
                continue
            text = brief_of(agent)
            handle = self.runner.start(agent, text, self.folder / "agents" / agent.key)
            self.launched[agent.tool] = self.launched.get(agent.tool, 0) + 1
            running.append((agent, handle))
        while running:
            windows, credits = self.readings()
            reason, tools = self._stop_reason(windows, credits, {a.tool for a, _ in running})
            if reason:
                self.outcome.stopped = reason
                for agent, handle in running:
                    if agent.tool in tools:
                        self.runner.stop(handle)
            still = []
            for agent, handle in running:
                if self.runner.done(handle):
                    finished.append(self._collect(agent, handle))
                else:
                    still.append((agent, handle))
            running = still
            if running:
                self.sleep(self.interval)
        windows, _ = self.readings()
        self._measure(start_used, _used(windows), finished)
        self.outcome.used_after = _used(windows)
        return [r for r in finished if r.status == "completed"]

    def _collect(self, agent, handle) -> AgentResult:
        status, text, cost = self.runner.result(handle)
        result = AgentResult(agent, status, cost=cost)
        if status == "completed":
            key = _ANSWERS[agent.role]
            answer = parse(text)
            if answer is None or not isinstance(answer.get(key), list):
                result.status, result.error = "failed", f"its answer had no JSON with {key}"
            else:
                result.answer = answer
        elif status != "stopped":
            result.error = f"the agent ended {status}"
        self._finish(result)
        return result

    def _finish(self, result: AgentResult) -> None:
        self.outcome.results.append(result)
        self.done += 1
        _progress(done=self.done, total=len(self.crew.agents), stage=PHASES[result.agent.phase])

    def _measure(self, before: dict, after: dict, finished: list) -> None:
        for tool in {r.agent.tool for r in finished}:
            seen = after.get(tool, 0) - before.get(tool, 0)
            agents = sum(1 for r in finished if r.agent.tool == tool)
            if seen > 0 and agents:  # a phase too short to move the reading says nothing
                total = self.burn.setdefault(tool, [0.0, 0])
                total[0] += seen
                total[1] += agents
                self.outcome.share[tool] = total[0] / total[1]


def supervise(config, crew: Team, work: Load, s: Settings, *, runner, readings, folder,
              clock, sleep, interval: float = 60, stop_file=None) -> Outcome:  # fmt: skip
    """Run the team phase by phase: drafts, critiques, then the final proposals. Each tool
    stays above its floor, Codex never spends credits, and a stop request ends it all."""
    write_dossier(folder / "dossier", work)
    run = _Run(crew, s, runner, readings, folder, clock, sleep, interval, stop_file)
    outcome = run.outcome
    for number in (1, 2, 3):
        agents = [a for a in crew.agents if a.phase == number]
        if not agents or outcome.stopped:
            continue
        done = run.phase(number, agents, lambda a: brief(a, drafts=outcome.drafts,
                                                          verdicts=outcome.verdicts))  # fmt: skip
        for result in done:
            outcome.drafts += result.answer.get("drafts", [])
            outcome.verdicts += result.answer.get("verdicts", [])
            if "proposals" in result.answer:
                outcome.proposals = result.answer["proposals"]
                outcome.summary = str(result.answer.get("summary", ""))
    for agent in crew.agents:  # never launched: a stop came first
        if not any(r.agent is agent for r in outcome.results):
            outcome.results.append(AgentResult(agent, "skipped", error=outcome.stopped))
    return outcome


class ProcessRunner:
    """Starts each agent through the delegation skill's runner for its tool, read-only,
    in the folder of material; a stop asks the runner to stop, which ends its child."""

    _DONE = {"completed": "completed", "needs_review": "completed", "unverified": "completed",
             "stopped": "stopped"}  # fmt: skip

    def __init__(self, s: Settings, dossier, *, scripts=None, python: str | None = None):
        from ax import job_wake, usage

        self.s, self.dossier = s, dossier
        self.scripts = scripts or usage._repo_root() / "skills" / "delegation" / "scripts"
        self.python = python or sys.executable
        self.env = job_wake.clean_env(os.environ)

    def _argv(self, agent: Agent, brief_path, run_dir) -> list[str]:
        s = self.s
        if agent.tool == "claude":
            return [self.python, str(self.scripts / "worker.py"), "start",
                    "--cwd", str(self.dossier), "--brief", str(brief_path),
                    "--run-dir", str(run_dir), "--model", s.claude_model, "--effort", s.effort,
                    "--profile", "read", "--max-cost-usd", str(s.claude_budget_usd),
                    "--timeout", str(s.timeout)]  # fmt: skip
        return [self.python, str(self.scripts / "codex_worker.py"), "run",
                "--brief", str(brief_path), "--cwd", str(self.dossier),
                "--run-dir", str(run_dir), "--model", s.codex_model, "--effort", s.effort,
                "--permission", "read-only", "--timeout", str(s.timeout)]  # fmt: skip

    def start(self, agent: Agent, text: str, folder):
        folder.mkdir(parents=True, exist_ok=True)
        brief_path, run_dir = folder / "brief.md", folder / "run"
        brief_path.write_text(text)
        with open(folder / "runner.log", "ab") as log:
            process = subprocess.Popen(
                self._argv(agent, brief_path, run_dir), cwd=self.dossier, env=self.env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )  # fmt: skip
        return {"process": process, "run_dir": run_dir}

    def done(self, handle) -> bool:
        return handle["process"].poll() is not None

    def stop(self, handle) -> None:
        if handle["run_dir"].exists():
            (handle["run_dir"] / "stop.request").touch()

    def result(self, handle) -> tuple[str, str, float | None]:
        run_dir = handle["run_dir"]
        try:
            record = json.loads((run_dir / "run.json").read_text())
        except (OSError, ValueError):
            return "failed", "", None
        answer = run_dir / "answer.md"
        text = answer.read_text() if answer.exists() else ""
        cost = record.get("total_cost_usd_estimate")
        status = self._DONE.get(record.get("status"), record.get("status") or "failed")
        return status, text, cost if isinstance(cost, int | float) else None

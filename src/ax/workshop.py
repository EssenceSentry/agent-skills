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
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

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
    evidence: dict = field(default_factory=dict)  # candidate id -> (session, said as standing)
    set_aside: list = field(default_factory=list)  # rules the user said "not now" to

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


def general(group) -> bool:
    """A lesson worth a lasting rule: it came up in two sessions or more, or you stated it
    as standing ("from now on", "remember"). One incident, however heated, is not one."""
    return len(group.sessions) >= 2 or any("explicit" in c["signals"] for c, _ in group.members)


def load(config, *, candidates=None, labels=None, findings=None) -> Load:
    rules = profile.load_rules(config, problems=[])
    active = [r for r in rules if r.status == "active"]
    proposals = [r for r in rules if r.status == "proposed"]
    set_aside = [r for r in rules if r.status == "not-now"]
    candidates = learn.load_candidates(config) if candidates is None else candidates
    labels = learn.load_labels(config) if labels is None else labels
    known = active + proposals + set_aside  # a set-aside rule's lesson is not new work
    uncovered = [
        g
        for g in learn.groups(candidates, labels)
        if g.support >= learn.MIN_SUPPORT
        and general(g)
        and not any(learn._matches(g, r) for r in known)
    ]
    if findings is None:
        findings = profile.check(config)
    return Load(
        proposals=proposals,
        flagged=[r for r in active if r.review],
        active=active,
        uncovered=uncovered,
        conflicts=[f for f in findings if f.kind == "conflict"],
        evidence={c["id"]: (c["session"], "explicit" in c["signals"]) for c in candidates},
        set_aside=set_aside,
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
    '"replaces": ["rule ids"], "evidence": ["candidate or rule ids"], '
    '"pattern": "the recurring situation it covers, not one incident", '
    '"checked": ["instructions/ files you searched"], "why": "short reason"}'
)
_WARNING = (
    '{"file": "the original path, from instructions/INDEX.md", "problem": "what it gets wrong", '
    '"evidence": ["candidate or rule ids"], "suggestion": "what to change"}'
)
_FORMATS = {
    "drafts": '{"drafts": [' + _DRAFT + '], "warnings": [' + _WARNING + "]}",
    "verdicts": '{"verdicts": [{"draft": "d1", "verdict": "keep|revise|drop", "why": "...", '
    '"revision": {...same fields as a draft, when revised}}]}',
    "proposals": '{"proposals": [' + _DRAFT.replace('"key": "d1", ', "") + "], "
    '"keep": ["ids of waiting proposals kept as they are"], '
    '"withdraw": [{"id": "a waiting proposal", "why": "...", '
    '"superseded_by": "the id of one of your proposals, or empty"}], '
    '"warnings": [' + _WARNING + '], "summary": "..."}',
}
_ANSWERS = {"designer": "drafts", "consolidator": "drafts", "critic": "verdicts",
            "synthesis": "proposals", "solo": "proposals"}  # fmt: skip
_COMMON = (
    "You are part of a rules workshop for the user's agent layer, ax. The rules are short "
    "instructions compiled into Claude Code and Codex; each one should prevent a correction "
    "the user has had to make, in words an agent can act on. The material is in this "
    "folder: rules.md (every active and proposed rule, with its evidence) and evidence.md "
    "(lessons no rule covers, flagged rules and conflicts), and instructions/ holds copies of "
    "what agents already read: global and repo instruction files (AGENTS.md, CLAUDE.md), "
    "skills and memories, listed with their origins in instructions/INDEX.md. Read it. Do "
    "not edit anything, run commands that change files, or start other agents. Prefer "
    "fewer, sharper rules: merge overlapping ones, scope a rule to the repo it belongs to, "
    "and drop a rule the evidence does not support. A rule must generalise: it names a "
    "pattern that recurs across sessions, never one incident; a lesson from one session is "
    "not a rule unless the user stated it as standing ('from now on', 'remember'). Before "
    "proposing anything, search instructions/ for what already says it: drop a rule an "
    "instruction file or skill already states, and say which files you checked. Rules the "
    "user set aside for now are listed at the end of rules.md: never propose them, or "
    "anything that says the same, again, and never count them against an idea. Keep each "
    "rule to one sentence. Ids are kebab-case; reuse an existing id only to retire or "
    "rewrite that rule."
)
_ROLES = {
    "designer": "Design rules for the items below: one rule per real lesson, a rewrite for "
    "a flagged rule, a resolution for a conflict. Say which rules a draft replaces. Also "
    "warn about any instruction file or skill the conversations show to be wrong, out of "
    "date, or the cause of a correction.",
    "consolidator": "Go through every rule in rules.md. Draft merges of rules that say the "
    "same thing, rewrites that make a rule clearer or narrower, and retirements of rules "
    "with no recent evidence or that another rule or an instruction file already covers. "
    "Warn about instruction files or skills that contradict the rules or each other.",
    "critic": "Judge every draft below against the evidence, the existing rules and "
    "instructions/: keep it, revise it (give the revision) or drop it, with a reason. Drop "
    "drafts that duplicate a rule or an instruction, rest on one session or one incident, "
    "or are too vague to act on.",
    "synthesis": "Write the one list the user will review. Every proposal waiting for the "
    "user (listed below) ends up in exactly one place: kept as it is (keep), replaced by "
    "one of your proposals (name it in that proposal's replaces), or withdrawn with a "
    "reason (withdraw). Apply every revision, drop what the critics dropped and settle "
    "disagreements; your proposals and the kept ones are at most twelve together. Keep the "
    "warnings about instruction files that the evidence supports. Add a one-paragraph "
    "summary for the user.",
    "solo": "Do the whole workshop alone: design rules for the items below, consolidate the "
    "existing rules, criticise your own drafts, warn about instruction files the "
    "conversations show to be wrong, and write the one list the user will review: every "
    "proposal waiting for the user (listed below) kept, replaced or withdrawn, at most "
    "twelve together, with a one-paragraph summary.",
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


def write_dossier(folder, work: Load, *, config=None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    rules = "\n".join(_rule_block(r) for r in [*work.active, *work.proposals])
    aside = "\n".join(_rule_block(r) for r in work.set_aside) or "None."
    (folder / "rules.md").write_text(
        f"# Rules\n\n{rules or 'No rules yet.'}\n\n# Set aside by the user for now\n\n"
        'Rules the user said "not now" to. They may bring them back; do not propose them, '
        f"or anything that says the same, again.\n\n{aside}\n"
    )
    evidence = "\n".join(_item_line(i) for i in work.design_items) or "Nothing uncovered."
    (folder / "evidence.md").write_text(f"# Evidence\n\n{evidence}\n")
    if config is not None:
        copy_instructions(config, folder / "instructions")


def _instruction_name(config, path: Path) -> str:
    """Where a copy goes inside instructions/: by the folder it came from."""
    places = [
        (config.claude_home / "skills", "skills"), (config.agents_home / "skills", "skills"),
        (config.codex_home / "skills", "skills"), (config.claude_home / "plugins", "plugins"),
        (config.claude_home / "projects", "memories"), (config.profile_repos_root, "repos"),
        *((d, f"extra/{d.name}") for d in config.profile_extra_dirs),
        (config.claude_home, "claude"), (config.codex_home, "codex"),
    ]  # fmt: skip
    for root, name in places:
        if path.is_relative_to(root):
            return f"{name}/{path.relative_to(root).as_posix()}"
    return f"other/{path.name}"


def copy_instructions(config, folder: Path) -> list[str]:
    """Copy every file agents already read as instructions (global and repo instruction
    files, skills, memories) into `folder`, once each, with an INDEX.md of where each
    came from, so the workshop can check what is already said."""
    folder.mkdir(parents=True, exist_ok=True)
    reals, texts, lines = set(), set(), []
    for path in profile._instruction_files(config):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        real = os.path.realpath(path)
        if real in reals or text in texts:
            continue  # the same skill linked from two folders
        reals.add(real)
        texts.add(text)
        name = _instruction_name(config, path)
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
        lines.append(f"- `{name}` ← {path}")
    index = ("# Instructions agents already follow\n\nRead-only copies. Each line is a copy "
             "here, then the file it came from.\n\n" + "\n".join(lines) + "\n")  # fmt: skip
    (folder / "INDEX.md").write_text(index)
    return lines


def brief(agent: Agent, *, drafts=(), verdicts=(), waiting=()) -> str:
    answer = _ANSWERS[agent.role]
    parts = [_COMMON, "", f"Your part: {_ROLES[agent.role]}"]
    if answer == "proposals":
        parts += ["", "Proposals waiting for the user (settle each one):",
                  *([f"- {rid}" for rid in waiting] or ["- none"])]  # fmt: skip
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


def _list(value) -> list:
    return value if isinstance(value, list) else []


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
    keep: list = field(default_factory=list)  # waiting proposals the final list keeps
    withdraw: list = field(default_factory=list)  # and those it takes off the list
    warnings: list = field(default_factory=list)  # instruction files that look wrong
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
    write_dossier(folder / "dossier", work, config=config)
    run = _Run(crew, s, runner, readings, folder, clock, sleep, interval, stop_file)
    outcome = run.outcome
    waiting = [r.id for r in work.proposals]
    for number in (1, 2, 3):
        agents = [a for a in crew.agents if a.phase == number]
        if not agents or outcome.stopped:
            continue
        done = run.phase(number, agents, lambda a: brief(a, drafts=outcome.drafts,
                                                          verdicts=outcome.verdicts,
                                                          waiting=waiting))  # fmt: skip
        for result in done:
            outcome.drafts += result.answer.get("drafts", [])
            outcome.verdicts += result.answer.get("verdicts", [])
            if "proposals" not in result.answer:
                outcome.warnings += _list(result.answer.get("warnings"))
                continue
            outcome.proposals = result.answer["proposals"]
            outcome.summary = str(result.answer.get("summary", ""))
            outcome.keep = [str(k) for k in _list(result.answer.get("keep"))]
            outcome.withdraw = _list(result.answer.get("withdraw"))
            if "warnings" in result.answer:  # the final list's warnings replace the drafts'
                outcome.warnings = _list(result.answer["warnings"])
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
            return [self.python, str(self.scripts / "worker.py"), "run",
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


# Writing what the team proposed

MAX_PROPOSALS = 12
KINDS = ("new", "merge", "rewrite", "retire")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SCOPE = re.compile(r"global|repo:[A-Za-z0-9._-]+")


@dataclass
class Written:
    proposals: list = field(default_factory=list)
    retire: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # (id, reason)
    kept: list = field(default_factory=list)  # waiting proposals the final list kept
    withdrawn: list = field(default_factory=list)  # (id, why) taken off the list
    unreviewed: list = field(default_factory=list)  # waiting proposals it left unsettled
    warnings: list = field(default_factory=list)  # instruction files that look wrong
    report: object = None


def _same_words(a, b) -> bool:
    return learn._overlap(learn._words(str(a or "")), learn._words(str(b or ""))) >= 0.8


def _problem(entry: dict, rules: dict, evidence: dict, set_aside=()) -> str | None:
    kind, rid = entry.get("kind"), entry.get("id")
    if kind not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}, not {kind!r}"
    if not isinstance(rid, str) or len(rid) > 64 or not _ID.fullmatch(rid):
        return f"id must be kebab-case, not {rid!r}"
    if kind == "retire":
        rule = rules.get(rid)
        return None if rule and rule.status == "active" else f"no active rule {rid} to retire"
    text = entry.get("rule")
    if not isinstance(text, str) or not text.strip() or len(text) > 300 or "\n" in text.strip():
        return "rule must be one sentence of at most 300 characters"
    if not _SCOPE.fullmatch(str(entry.get("scope") or "global")):
        return f"scope must be global or repo:NAME, not {entry.get('scope')!r}"
    if (entry.get("level") or "advice") not in ("advice", "check", "block"):
        return f"level must be advice, check or block, not {entry.get('level')!r}"
    aside = next((r for r in set_aside if r.id == rid or _same_words(r.rule, entry.get("rule"))),
                  None)  # fmt: skip
    if aside is not None:
        return f"it repeats {aside.id}, which you set aside for now (bring it back from Decided)"
    if not str(entry.get("pattern") or "").strip():
        return "a proposal names the recurring pattern it covers"
    if kind == "new":
        seen = [evidence[e] for e in _list(entry.get("evidence")) if e in evidence]
        if len({session for session, _ in seen}) < 2 and not any(said for _, said in seen):
            return "it rests on one session: a rule must generalise"
    return None


def _free_id(rid: str, taken: set) -> str:
    if rid not in taken:
        return rid
    n = 2
    while f"{rid}-{n}" in taken:
        n += 1
    return f"{rid}-{n}"


def write(config, outcome: Outcome, work: Load, *, now: datetime) -> Written:
    """Write valid proposals as rule notes (`proposed`, from the workshop), put suggested
    retirements on the rules themselves, and record the run in a report note."""
    rules = {r.id: r for r in profile.load_rules(config, problems=[])}
    entries, unreviewed = _list(outcome.proposals), False
    if not entries and outcome.drafts:
        entries, unreviewed = outcome.drafts, True  # no synthesis ran: the drafts as they are
    tools = sorted({r.agent.tool for r in outcome.results}) or ["claude"]
    folder = config.vault / "Workshops"
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / f"{now.astimezone():%Y-%m-%d %H%M} {'+'.join(tools)}.md"
    written = Written(report=report)
    day = now.astimezone().strftime("%Y-%m-%d")
    lines: list[str] = []
    waiting = {r.id for r in work.proposals}
    by = f"the rules workshop ({report.stem})"
    withdrawn: list = []  # (id, why)
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {}
        problem = _problem(entry, rules, work.evidence, work.set_aside)
        if problem:
            written.skipped.append((str(entry.get("id")), problem))
            continue
        why = str(entry.get("why") or "").strip()[:1500]
        if entry["kind"] == "retire":
            rule = rules[entry["id"]]
            rule.extra["workshop"] = {"suggest": "retire", "why": why, "report": report.stem}
            profile._write(rule, rule.path)
            written.retire.append(rule.id)
            continue
        if len(written.proposals) >= MAX_PROPOSALS:
            written.skipped.append((entry["id"], f"over the limit of {MAX_PROPOSALS} proposals"))
            continue
        replaces = [r for r in entry.get("replaces") or [] if isinstance(r, str) and r in rules]
        rid = _free_id(entry["id"], set(rules) | set(written.proposals))
        said = f" Replaces {', '.join(replaces)}; accepting it retires them." if replaces else ""
        try:
            rule = profile.add(
                config, rid, rule=entry["rule"].strip(), scope=entry.get("scope") or "global",
                level=entry.get("level") or "advice", status="proposed",
                evidence=[str(e) for e in entry.get("evidence") or []][:20],
                why=f"Proposed by the rules workshop on {day} ([[Workshops/{report.stem}]])."
                f"{said}\n\n{why}",
                extra={"source": "workshop", "workshop": report.stem, "replaces": replaces},
            )  # fmt: skip
        except ValueError as exc:
            written.skipped.append((rid, str(exc)))
            continue
        written.proposals.append(rule.id)
        rules[rule.id] = rule
        merged = f"; replaces {', '.join(replaces)}" if replaces else ""
        lines.append(f"- [[Profile/rules/{rule.id}]]: {rule.rule} ({entry['kind']}{merged})")
        for old in replaces:  # one list: a waiting proposal it replaces leaves the queue now
            if old in waiting and rules[old].status == "proposed":
                learn.reject(config, old, by=by, superseded_by=rule.id)
                withdrawn.append((old, f"replaced by [[Profile/rules/{rule.id}]]"))
    for entry in outcome.withdraw:
        entry = entry if isinstance(entry, dict) else {}
        rid, why = str(entry.get("id") or ""), str(entry.get("why") or "").strip()[:600]
        current = next((r for r in profile.load_rules(config, problems=[]) if r.id == rid), None)
        if rid not in waiting or current is None or current.status != "proposed":
            continue
        instead = str(entry.get("superseded_by") or "")
        instead = instead if instead in written.proposals else ""
        learn.reject(config, rid, by=by, superseded_by=instead, note=why)
        withdrawn.append(
            (rid, why + (f" Replaced by [[Profile/rules/{instead}]]." if instead else ""))
        )
    kept = [k for k in outcome.keep if k in waiting and k not in {w for w, _ in withdrawn}]
    settled = set(kept) | {w for w, _ in withdrawn}
    written.kept, written.withdrawn = kept, withdrawn
    written.unreviewed = sorted(waiting - settled) if not unreviewed else []
    written.warnings = add_warnings(config, outcome.warnings, report=report.stem)
    report.write_text(_report(outcome, written, lines, unreviewed, now))
    return written


def _report(outcome: Outcome, written: Written, lines: list, unreviewed: bool, now) -> str:
    meta = {
        "date": now.astimezone().isoformat(timespec="minutes"),
        "tools": sorted({r.agent.tool for r in outcome.results}),
        "agents": len(outcome.results),
        "proposals": written.proposals,
        "retire": written.retire,
        "stopped": outcome.stopped,
    }
    parts = ["---", yaml.safe_dump(meta, sort_keys=False).strip(), "---", "",
             f"# Rules workshop, {now.astimezone():%d %B %Y}", ""]  # fmt: skip
    if outcome.summary:
        parts += [outcome.summary, ""]
    if unreviewed:
        parts += ["No synthesis ran, so these are the designers' unreviewed drafts.", ""]
    if outcome.stopped:
        parts += [f"Stopped early: {outcome.stopped}.", ""]
    parts += ["## Proposals", "", *(lines or ["None written."]), ""]
    if written.kept:
        parts += ["## Kept", "", *(f"- [[Profile/rules/{rid}]]" for rid in written.kept), ""]
    if written.withdrawn:
        parts += ["## Withdrawn", "", "Set aside for you, under Decided in the app, where "
                  "you can bring any of them back.", ""]  # fmt: skip
        parts += [f"- [[Profile/rules/{rid}]]: {why}" for rid, why in written.withdrawn] + [""]
    if written.unreviewed:
        parts += ["## Not reviewed", "", "Waiting proposals the final list left as they were.", ""]
        parts += [f"- [[Profile/rules/{rid}]]" for rid in written.unreviewed] + [""]
    if written.warnings:
        parts += ["## Instructions to check", ""]
        for w in written.warnings:
            parts.append(f"- `{w['file']}`: {w['problem']}"
                         + (f" Suggestion: {w['suggestion']}" if w["suggestion"] else ""))  # fmt: skip
        parts.append("")
    if written.retire:
        parts += ["## Suggested retirements", ""]
        parts += [f"- [[Profile/rules/{rid}]]" for rid in written.retire] + [""]
    if written.skipped:
        parts += ["## Skipped", "", *(f"- `{rid}`: {why}" for rid, why in written.skipped), ""]
    parts += ["## Agents", "", "| Agent | Tool | Status | Cost | Note |", "|---|---|---|---|---|"]
    for r in outcome.results:
        cost = f"${r.cost:.2f}" if isinstance(r.cost, int | float) else "-"
        parts.append(f"| {r.agent.key} | {r.agent.tool} | {r.status} | {cost} | {r.error or ''} |")
    parts += ["", "## Allowance", ""]
    for tool, before in sorted(outcome.used_before.items()):
        after = outcome.used_after.get(tool, before)
        share = outcome.share.get(tool)
        measured = f" (about {share:.1f}% per agent)" if share else ""
        parts.append(f"- {tool}: {before:.0f}% → {after:.0f}%{measured}")
    return "\n".join(parts) + "\n"


# Starting by itself, and remembering what was done


def _now() -> datetime:
    return datetime.now(UTC)


def _readings(config):
    """Both tools' windows, Claude's asked fresh (a built-in /usage: no model call)."""
    from ax import usage

    windows = usage.claude_windows(config, refresh=True) + usage.codex_windows(config.codex_home)
    return windows, usage.codex_credits(config.codex_home)


def _readings_cached(config):
    from ax import usage

    windows = usage.claude_windows(config, refresh=False) + usage.codex_windows(config.codex_home)
    return windows, usage.codex_credits(config.codex_home)


def _launch(config, key: str, label: str) -> None:
    from ax import jobs

    argv = [sys.executable, "-m", "ax.cli", "workshop", "run"]
    jobs.run(config, argv, key=key, label=label, cwd=str(config.data))


def _notify(config):
    from ax import job_notify

    ntfy = job_notify.settings(config)
    if ntfy is None:
        return lambda title, message: None
    return lambda title, message: job_notify.send(ntfy, title, message, tags=("hammer",))


def keys(work: Load) -> set:
    """What a run works on, so the next one in the same window can tell what is new."""
    found = {f"lesson:{g.topic}" for g in work.uncovered}
    found |= {f"flag:{r.id}" for r in work.flagged}
    found |= {f"conflict:{f.rule}:{f.message[:60]}" for f in work.conflicts}
    # The workshop's own proposals are its output, not new work for the next run.
    mine = {r.id for r in work.proposals if r.extra.get("source") == "workshop"}
    return found | {f"proposal:{r.id}" for r in work.proposals if r.id not in mine}


# Warnings about instruction files, kept until the user dismisses them


def warnings_path(config) -> Path:
    return config.data / "workshop" / "warnings.json"


def load_warnings(config) -> dict:
    try:
        found = json.loads(warnings_path(config).read_text())
    except (OSError, ValueError):
        return {"last": 0, "warnings": []}
    return found if isinstance(found, dict) else {"last": 0, "warnings": []}


def _save_warnings(config, data: dict) -> None:
    path = warnings_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(path)


def add_warnings(config, entries, *, report: str) -> list[dict]:
    """Record the run's warnings that name a file and a problem; ids are never reused."""
    data = load_warnings(config)
    added = []
    for entry in _list(entries):
        entry = entry if isinstance(entry, dict) else {}
        file, problem = (
            str(entry.get("file") or "").strip(),
            str(entry.get("problem") or "").strip(),
        )
        if not file or not problem:
            continue
        data["last"] = int(data.get("last") or 0) + 1
        warning = {"id": f"W{data['last']}", "file": file[:300], "problem": problem[:600],
                   "suggestion": str(entry.get("suggestion") or "").strip()[:600],
                   "evidence": [str(e) for e in _list(entry.get("evidence"))][:10],
                   "report": report, "status": "open"}  # fmt: skip
        data.setdefault("warnings", []).append(warning)
        added.append(warning)
    if added:
        _save_warnings(config, data)
    return added


def open_warnings(config) -> list[dict]:
    return [w for w in load_warnings(config).get("warnings", []) if w.get("status") == "open"]


def dismiss_warning(config, warning_id: str) -> dict:
    data = load_warnings(config)
    for w in data.get("warnings", []):
        if w.get("id") == warning_id and w.get("status") == "open":
            w["status"] = "dismissed"
            _save_warnings(config, data)
            return w
    raise ValueError(f"no open warning {warning_id}")


def _state_path(config):
    return config.data / "workshop" / "state.json"


def load_state(config) -> dict:
    try:
        return json.loads(_state_path(config).read_text())
    except (OSError, ValueError):
        return {"windows": {}, "share": {}}


def _window_key(found: Opening) -> str:
    """The window's tool and reset, to the nearest hour: the reported reset moves by a
    minute between readings (23:59, then 00:00)."""
    hour = (found.resets_at + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
    return f"{found.tool}:{hour.isoformat(timespec='minutes')}"


def remember(config, ready: list, work: Load, share: dict, *, took: bool = True) -> None:
    """Count a run in its windows; only a run that finished something (`took`) marks
    its work as taken, so a run that failed leaves it to the next one."""
    state = load_state(config)
    for found in ready:
        window = state.setdefault("windows", {}).setdefault(
            _window_key(found), {"covered": [], "runs": 0}
        )
        if took:
            window["covered"] = sorted(set(window["covered"]) | keys(work))
        window["runs"] += 1
    for tool, measured in share.items():  # an even mix of the last estimate and this run
        old = state.setdefault("share", {}).get(tool)
        state["share"][tool] = round((old + measured) / 2 if old else measured, 2)
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def _share(state: dict, ready: list) -> float | None:
    known = [state.get("share", {}).get(o.tool) for o in ready]
    known = [k for k in known if k]
    return max(known) if known else None


def stop_file(config):
    return config.data / "workshop" / "stop.request"


def stop(config) -> None:
    path = stop_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _running(config) -> str | None:
    from ax import jobs

    jobs.refresh_active(config)  # a run that ended while no one watched no longer blocks
    for job in jobs.list_jobs(config, refresh_active=False):
        if job.key.startswith("workshop-") and job.status == "running":
            return job.key
    return None


def _plan(config, readings, now) -> tuple:
    s = settings(config)
    windows, _ = readings()
    found = openings(windows, s, now)
    ready = [o for o in found if o.ok]
    work = load(config)
    state = load_state(config)
    crew = team(work, found, s, share=_share(state, ready))
    return s, found, ready, work, state, crew


def maybe_start(config, *, readings=None, launch=None, now=None) -> str | None:
    """After a sync: start a detached run when a window is spare in its last day and the
    rules have work that no run in this window has taken yet."""
    now = now or _now()
    s, found, ready, work, state, crew = _plan(
        config, readings or (lambda: _readings_cached(config)), now
    )
    if not s.enabled or not ready or not crew.agents or _running(config):
        return None
    done = set()
    for o in ready:
        done |= set(state.get("windows", {}).get(_window_key(o), {}).get("covered", []))
    if not keys(work) - done:
        return None  # this window's runs already took all of it
    key = f"workshop-{now.astimezone():%Y%m%d-%H%M}"
    tools = " and ".join(sorted({a.tool for a in crew.agents}))
    label = (f"Rules workshop: {len(crew.agents)} agents on {tools}'s spare weekly allowance "
             f"consolidate and design the rules; their work lands as proposals.")  # fmt: skip
    (launch or _launch)(config, key, label)
    return f"started {key}: {crew.reason}"


def _agent_row(agent: Agent) -> dict:
    return {"key": agent.key, "role": agent.role, "tool": agent.tool, "phase": agent.phase,
            "items": len(agent.items), "consolidates": agent.consolidates}  # fmt: skip


def status(config, *, readings=None, now=None) -> dict:
    now = now or _now()
    s, found, ready, work, state, crew = _plan(config, readings or (lambda: _readings(config)), now)
    return {
        "enabled": s.enabled,
        "running": _running(config),
        "openings": [
            {
                "tool": o.tool,
                "ok": o.ok,
                "reason": o.reason,
                "used": o.used,
                "budget": round(o.budget, 1),
            }
            for o in found
        ],  # fmt: skip
        "work": {
            "proposals": len(work.proposals),
            "flagged": len(work.flagged),
            "uncovered": len(work.uncovered),
            "conflicts": len(work.conflicts),
            "active": len(work.active),
        },  # fmt: skip
        "team": [_agent_row(a) for a in crew.agents],
        "reason": crew.reason,
    }


def run(config, *, dry_run=False, readings=None, runner=None, now=None, clock=None,
        sleep=None, notify=None) -> dict:  # fmt: skip
    """One workshop run, normally started by `maybe_start` as a detached ax job."""
    now = now or _now()
    readings = readings or (lambda: _readings(config))
    s, found, ready, work, state, crew = _plan(config, readings, now)
    folder = config.data / "workshop" / "runs" / f"{now.astimezone():%Y%m%d-%H%M%S}"
    summary = {"folder": str(folder), "team": [_agent_row(a) for a in crew.agents],
               "reason": crew.reason, "dry_run": dry_run}  # fmt: skip
    if dry_run or not crew.agents:
        write_dossier(folder / "dossier", work, config=config)
        (folder / "briefs").mkdir(parents=True, exist_ok=True)
        for agent in crew.agents:
            (folder / "briefs" / f"{agent.key}.md").write_text(brief(agent))
        return summary
    stop_file(config).unlink(missing_ok=True)
    tell = notify or _notify(config)
    tell("Rules workshop started", f"{len(crew.agents)} agents: {crew.reason}")
    outcome = supervise(
        config, crew, work, s, runner=runner or ProcessRunner(s, folder / "dossier"),
        readings=readings, folder=folder, clock=clock or _now, sleep=sleep or time.sleep,
        stop_file=stop_file(config),
    )  # fmt: skip
    written = write(config, outcome, work, now=now)
    took = any(r.status == "completed" for r in outcome.results)
    remember(config, ready, work, outcome.share, took=took)
    failed = not took and not outcome.stopped
    if failed:
        tell("Rules workshop failed",
             f"none of its {len(crew.agents)} agents finished; the next sync tries again. "
             f"Report: {written.report.name}")  # fmt: skip
    else:
        ended = f"stopped early: {outcome.stopped}. " if outcome.stopped else ""
        tell("Rules workshop finished",
             f"{ended}{len(written.proposals)} new proposal(s), {len(written.kept)} kept, "
             f"{len(written.withdrawn)} withdrawn, {len(written.retire)} suggested "
             f"retirement(s) and {len(written.warnings)} instruction warning(s) wait in the "
             f"app; report: {written.report.name}")  # fmt: skip
    return {**summary, "proposals": written.proposals, "retire": written.retire,
            "skipped": written.skipped, "report": str(written.report),
            "kept": written.kept, "withdrawn": [rid for rid, _ in written.withdrawn],
            "warnings": [w["id"] for w in written.warnings],
            "stopped": outcome.stopped, "failed": failed}  # fmt: skip

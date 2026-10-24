"""Research campaigns: experiments that must pass a value gate before they run.

A campaign lives in the vault at Projects/<project>/Research/<slug>/. Each
experiment is a note under experiments/ whose frontmatter Obsidian Bases can
show, ranked by score: how much the decision matters (value, 1-5) times the
chance the result changes it (p_change), per estimated hour. Agents propose
work through the gate; nothing in it judges the science, it only makes the
decision, the outcomes and the cost explicit before effort is spent.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Three finished experiments in a row that changed no decision is a stall.
STALL_AFTER = 3
_ACTION = re.compile(r"→|->|\bthen\b", re.I)
_OPEN = ("proposed", "running")
# A single folder name that cannot climb out of the vault or hide.
_SAFE_NAME = re.compile(r"^(?!\.)[\w .-]+$")


class GateFailed(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Experiment:
    id: str
    path: Path
    question: str
    status: str
    score: float
    decision: str = ""
    outcomes: list[str] = field(default_factory=list)
    est_hours: float = 0.0
    actual_hours: float | None = None
    decision_changed: bool | None = None
    finished: str | None = None


def init(
    vault: Path,
    project: str,
    slug: str,
    objective: str,
    decisions: list[str],
    budget_hours: float,
) -> Path:
    """Create a campaign folder and its Campaign.md; never overwrite one."""
    for name in (project, slug):
        if not _SAFE_NAME.match(name):
            raise ValueError(f"{name!r}: use letters, digits, spaces, dots, - and _ only")
    folder = Path(vault) / "Projects" / project / "Research" / slug
    note = folder / "Campaign.md"
    if note.exists():
        raise FileExistsError(note)
    folder.mkdir(parents=True)
    meta = {
        "type": "campaign",
        "project": project,
        "campaign": slug,
        "status": "active",
        "objective": objective,
        "decisions": list(decisions),
        "budget_hours": budget_hours,
        "created": _now(),
    }
    served = "\n".join(f"- {d}" for d in decisions) or "- (name the decisions this research serves)"
    body = (
        f"# {slug}\n\n{objective}\n\n## Decisions this serves\n\n{served}\n\n"
        "## Stop rules\n\n- Stop when the budget is spent or three results in a row change "
        "no decision.\n\n## Current answer\n\nNot yet known.\n"
    )
    _write(note, meta, body)
    return folder


def find_campaign(vault: Path, slug: str) -> Path | None:
    matches = sorted(Path(vault).glob(f"Projects/*/Research/{slug}/Campaign.md"))
    return matches[0].parent if len(matches) == 1 else None


def gate_problems(fields: dict) -> list[str]:
    problems = []
    if not str(fields.get("question") or "").strip():
        problems.append("state the question")
    if not str(fields.get("decision") or "").strip():
        problems.append("name the decision or claim this informs")
    outcomes = [o for o in fields.get("outcomes") or [] if str(o).strip()]
    if len(outcomes) < 2:
        problems.append("list at least two outcomes that would lead to different actions")
    if any(not _ACTION.search(o) for o in outcomes):
        problems.append("give each outcome its action, as 'result → action'")
    if not str(fields.get("cheaper") or "").strip():
        problems.append("say what cheaper evidence was considered and why it isn't enough")
    if not str(fields.get("stop") or "").strip():
        problems.append("set a stop rule: what result, failure or cost ends this")
    hours = fields.get("est_hours")
    if not isinstance(hours, int | float) or hours <= 0:
        problems.append("estimate the cost in hours")
    value = fields.get("value")
    if not isinstance(value, int | float) or not 1 <= value <= 5:
        problems.append("rate how much the decision matters, value 1-5")
    p_change = fields.get("p_change")
    if not isinstance(p_change, int | float) or not 0 <= p_change <= 1:
        problems.append("estimate the chance the result changes the decision, p_change 0-1")
    return problems


def propose(campaign: Path, **fields) -> Experiment:
    """Record a proposed experiment, or raise GateFailed naming what is missing."""
    problems = gate_problems(fields)
    if problems:
        raise GateFailed(problems)
    folder = Path(campaign) / "experiments"
    folder.mkdir(exist_ok=True)
    number = 1 + max(
        (int(m.group(1)) for p in folder.glob("E*.md") if (m := re.match(r"E(\d+)", p.name))),
        default=0,
    )
    exp_id = f"E{number:03d}"
    meta = {
        "type": "experiment",
        "id": exp_id,
        "campaign": Path(campaign).name,
        "status": "proposed",
        "question": fields["question"],
        "decision": fields["decision"],
        "outcomes": list(fields["outcomes"]),
        "cheaper": fields["cheaper"],
        "stop": fields["stop"],
        "est_hours": float(fields["est_hours"]),
        "value": fields["value"],
        "p_change": float(fields["p_change"]),
        "score": _score(fields["value"], fields["p_change"], fields["est_hours"]),
        "created": _now(),
    }
    outcomes = "\n".join(f"- {o}" for o in meta["outcomes"])
    body = (
        f"# {exp_id} {meta['question']}\n\n"
        f"**Decision:** {meta['decision']}\n\n**Outcomes:**\n\n{outcomes}\n\n"
        f"**Cheaper evidence considered:** {meta['cheaper']}\n\n**Stop rule:** {meta['stop']}\n\n"
        "## Notes\n\n## Result\n"
    )
    path = folder / f"{exp_id} {_slug(meta['question'])}.md"
    _write(path, meta, body)
    return _load(path)


def experiments(campaign: Path) -> list[Experiment]:
    return [_load(p) for p in sorted((Path(campaign) / "experiments").glob("E*.md"))]


def rank(found: list[Experiment]) -> list[Experiment]:
    """Open proposals, best value per hour first."""
    return sorted((e for e in found if e.status == "proposed"), key=lambda e: e.score, reverse=True)


def start(campaign: Path, exp_id: str) -> None:
    _update(campaign, exp_id, status="running", started=_now())


def finish(
    campaign: Path,
    exp_id: str,
    *,
    result: str,
    hours: float,
    decision_changed: bool,
    insight: str | None = None,
) -> None:
    path = _path(campaign, exp_id)
    _update(
        campaign,
        exp_id,
        status="done",
        finished=_now(),
        actual_hours=hours,
        decision_changed=decision_changed,
    )
    changed = "changed the decision" if decision_changed else "changed no decision"
    _append_section(path, f"{result}\n\n_{changed}; {hours:g} hours._")
    if insight:
        _append(Path(campaign) / "Insights.md", "Insights", f"{exp_id}: {insight}")


def abandon(campaign: Path, exp_id: str, *, reason: str, dead_end: bool = False) -> None:
    _update(campaign, exp_id, status="abandoned", finished=_now())
    _append_section(_path(campaign, exp_id), f"Abandoned: {reason}")
    if dead_end:
        _append(Path(campaign) / "Dead ends.md", "Dead ends", f"{exp_id}: {reason}")


def summary(campaign: Path) -> dict:
    found = experiments(campaign)
    meta, _ = _read(Path(campaign) / "Campaign.md")
    done = sorted((e for e in found if e.status == "done"), key=lambda e: e.finished or "")
    recent = done[-STALL_AFTER:]
    return {
        "budget_hours": meta.get("budget_hours"),
        "spent_hours": sum(e.actual_hours or 0 for e in found),
        "proposed": sum(e.status == "proposed" for e in found),
        "running": sum(e.status == "running" for e in found),
        "done": len(done),
        "stalled": len(recent) == STALL_AFTER and not any(e.decision_changed for e in recent),
    }


def _update(campaign: Path, exp_id: str, **changes) -> None:
    path = _path(campaign, exp_id)
    meta, body = _read(path)
    meta.update(changes)
    _write(path, meta, body)


def _path(campaign: Path, exp_id: str) -> Path:
    matches = list((Path(campaign) / "experiments").glob(f"{exp_id} *.md"))
    if len(matches) != 1:
        raise KeyError(f"no experiment {exp_id} in {campaign}")
    return matches[0]


def _load(path: Path) -> Experiment:
    meta, _ = _read(path)
    return Experiment(
        id=meta["id"],
        path=path,
        question=meta.get("question", ""),
        status=meta.get("status", "proposed"),
        score=float(meta.get("score") or 0),
        decision=meta.get("decision", ""),
        outcomes=meta.get("outcomes") or [],
        est_hours=float(meta.get("est_hours") or 0),
        actual_hours=meta.get("actual_hours"),
        decision_changed=meta.get("decision_changed"),
        finished=str(meta["finished"]) if meta.get("finished") else None,
    )


def _read(path: Path) -> tuple[dict, str]:
    import yaml  # imported here so `ax sync` never depends on it

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    front, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(front) or {}, body.lstrip("\n")


def _write(path: Path, meta: dict, body: str) -> None:
    import yaml

    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000)
    path.write_text(f"---\n{front}---\n\n{body}", encoding="utf-8")


def _append_section(path: Path, text: str) -> None:
    meta, body = _read(path)
    _write(path, meta, body.rstrip("\n") + f"\n\n{text}\n")


def _append(path: Path, title: str, line: str) -> None:
    if not path.exists():
        path.write_text(f"# {title}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.now():%Y-%m-%d} {line}\n")


def _score(value, p_change, hours) -> float:
    return round(value * p_change / max(float(hours), 0.25), 3)


def _slug(text: str) -> str:
    words = re.sub(r"[^\w\s-]", "", text).split()
    return " ".join(words)[:60] or "experiment"


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S")

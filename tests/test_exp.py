import pytest
import yaml
from typer.testing import CliRunner

from ax import exp
from ax.cli import app

runner = CliRunner()

GOOD = {
    "question": "Do channel lists stay stable week to week?",
    "decision": "Whether to optimise channel lists weekly or monthly",
    "outcomes": [
        "overlap above 80% → optimise monthly",
        "overlap below 50% → optimise weekly",
    ],
    "cheaper": "Checked last quarter's exports; they lack channel ids",
    "stop": "Stop after two weeks of data or 4 hours",
    "est_hours": 3.0,
    "value": 5,
    "p_change": 0.6,
}


def front(path):
    return yaml.safe_load(path.read_text().split("\n---\n", 1)[0][4:])


@pytest.fixture
def campaign(env):
    return exp.init(
        env.vault, "demo", "pricing-study", "Find what moves buy rates", ["Bid caps"], 20
    )


def test_init_writes_a_campaign_note_and_refuses_to_overwrite(env, campaign):
    note = campaign / "Campaign.md"
    assert front(note)["type"] == "campaign"
    assert front(note)["budget_hours"] == 20
    assert "## Current answer" in note.read_text()
    with pytest.raises(FileExistsError):
        exp.init(env.vault, "demo", "pricing-study", "again", [], 1)
    assert exp.find_campaign(env.vault, "pricing-study") == campaign


def test_the_gate_names_every_missing_piece(campaign):
    with pytest.raises(exp.GateFailed) as failed:
        exp.propose(campaign, question="Run 10,000 more simulations?", outcomes=["more data"])
    problems = " ".join(failed.value.problems)
    for piece in ("decision", "two outcomes", "action", "cheaper", "stop rule", "hours"):
        assert piece in problems
    assert list(campaign.glob("experiments/*.md")) == []


def test_a_complete_proposal_becomes_a_scored_note(campaign):
    e = exp.propose(campaign, **GOOD)
    assert e.id == "E001"
    meta = front(e.path)
    assert meta["status"] == "proposed"
    assert meta["score"] == pytest.approx(5 * 0.6 / 3.0)
    assert meta["outcomes"] == GOOD["outcomes"]
    assert exp.propose(campaign, **{**GOOD, "question": "Second?"}).id == "E002"


def test_open_proposals_rank_by_value_per_hour(campaign):
    exp.propose(
        campaign, **{**GOOD, "question": "Cheap and decisive", "est_hours": 1, "p_change": 0.8}
    )
    exp.propose(campaign, **{**GOOD, "question": "Big simulation", "est_hours": 20, "value": 2})
    exp.propose(campaign, **{**GOOD, "question": "Middle", "est_hours": 4})
    order = [e.question for e in exp.rank(exp.experiments(campaign))]
    assert order == ["Cheap and decisive", "Middle", "Big simulation"]


def test_finishing_records_the_result_and_appends_insights_and_dead_ends(campaign):
    e = exp.propose(campaign, **GOOD)
    exp.start(campaign, e.id)
    assert front(e.path)["status"] == "running"
    exp.finish(
        campaign,
        e.id,
        result="Overlap 85%",
        hours=2.5,
        decision_changed=True,
        insight="Lists are stable",
    )
    meta = front(e.path)
    assert (meta["status"], meta["actual_hours"], meta["decision_changed"]) == ("done", 2.5, True)
    assert "Overlap 85%" in e.path.read_text()
    assert "Lists are stable" in (campaign / "Insights.md").read_text()
    other = exp.propose(campaign, **{**GOOD, "question": "Try a market simulator?"})
    exp.abandon(campaign, other.id, reason="No data on competitor bids", dead_end=True)
    assert "No data on competitor bids" in (campaign / "Dead ends.md").read_text()


def test_three_results_that_change_nothing_flag_a_stall(campaign):
    for i in range(3):
        e = exp.propose(campaign, **{**GOOD, "question": f"Tweak {i}"})
        exp.finish(campaign, e.id, result="noise", hours=1, decision_changed=False)
    summary = exp.summary(campaign)
    assert summary["stalled"] is True
    assert summary["spent_hours"] == 3
    assert summary["budget_hours"] == 20


def test_propose_command_explains_a_rejected_gate(env, campaign):
    environment = {"AX_CONFIG": str(env.config_path)}
    result = runner.invoke(
        app, ["exp", "propose", "pricing-study", "--question", "More sims?"], env=environment
    )
    assert result.exit_code == 1
    assert "decision" in result.output


def test_list_command_ranks_open_proposals(env, campaign):
    exp.propose(campaign, **{**GOOD, "question": "Low", "value": 1})
    exp.propose(campaign, **{**GOOD, "question": "High", "value": 5})
    result = runner.invoke(
        app, ["exp", "list", "pricing-study"], env={"AX_CONFIG": str(env.config_path)}
    )
    assert result.exit_code == 0, result.output
    assert result.output.index("High") < result.output.index("Low")

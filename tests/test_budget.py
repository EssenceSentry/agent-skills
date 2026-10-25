import pytest

from ax import budget


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


def made(data, name="annotations", cap=40.0, unit="usd", **kw):
    return budget.create(data, name, cap, unit, **kw)


def test_a_budget_counts_what_agents_add_and_says_what_is_left(data):
    made(data, why="Luna annotations for the News research", owner="ax:48402546")
    budget.add(data, "annotations", 3.2, note="batch 1", agent="ax:48402546")
    budget.add(data, "annotations", 9.0, note="batch 2")
    found = budget.status(data, "annotations")
    assert (found["spent"], found["reserved"], found["left"]) == (12.2, 0.0, 27.8)
    assert found["state"] == "ok" and found["unit"] == "usd" and found["owner"] == "ax:48402546"
    [second, first] = budget.entries(data, "annotations")
    assert first["note"] == "batch 1" and first["agent"] == "ax:48402546"
    assert second["amount"] == 9.0


def test_check_says_whether_the_next_amount_fits(data):
    made(data)
    budget.add(data, "annotations", 30)
    assert budget.fits(data, "annotations", 10) and not budget.fits(data, "annotations", 10.5)


def test_going_over_is_refused_unless_a_reason_is_given(data):
    made(data)
    budget.add(data, "annotations", 38)
    with pytest.raises(budget.OverLimit) as over:
        budget.add(data, "annotations", 5, note="one more batch")
    assert "43 of 40 usd" in str(over.value) and "3 over" in str(over.value)
    assert budget.status(data, "annotations")["spent"] == 38  # nothing recorded
    budget.add(data, "annotations", 5, note="one more batch", intent="the last batch matters")
    found = budget.status(data, "annotations")
    assert found["spent"] == 43 and found["state"] == "over"
    assert budget.entries(data, "annotations")[0]["intent"] == "the last batch matters"


def test_a_reservation_holds_until_it_is_settled_or_released(data):
    made(data)
    ticket = budget.reserve(data, "annotations", 5, note="batch 3")
    assert budget.status(data, "annotations")["reserved"] == 5
    assert budget.status(data, "annotations")["left"] == 35
    budget.settle(data, ticket, 4.1)
    found = budget.status(data, "annotations")
    assert (found["spent"], found["reserved"]) == (4.1, 0.0)
    other = budget.reserve(data, "annotations", 7)
    budget.release(data, other)
    assert budget.status(data, "annotations")["reserved"] == 0
    with pytest.raises(budget.BudgetError, match="already settled"):
        budget.settle(data, ticket, 1)
    with pytest.raises(budget.BudgetError, match="no reservation"):
        budget.settle(data, "R999", 1)


def test_reservations_keep_parallel_workers_from_overshooting_together(data):
    made(data, cap=10)
    budget.reserve(data, "annotations", 6, agent="worker-1")
    with pytest.raises(budget.OverLimit):
        budget.reserve(data, "annotations", 6, agent="worker-2")  # alone it would fit


def test_a_measured_budget_reads_its_folder(data, tmp_path):
    folder = tmp_path / "raw"
    (folder / "a").mkdir(parents=True)
    (folder / "a" / "one.bin").write_bytes(b"x" * 1_500_000)
    (folder / "two.bin").write_bytes(b"x" * 500_000)
    made(data, "downloads", 0.004, "GB", path=str(folder))
    found = budget.status(data, "downloads")
    assert found["spent"] == pytest.approx(0.002) and found["path"] == str(folder)
    with pytest.raises(budget.BudgetError, match="measures its folder"):
        budget.add(data, "downloads", 0.001)
    budget.reserve(data, "downloads", 0.0015, note="next shard")
    assert not budget.fits(data, "downloads", 0.001)
    (folder / "three.bin").write_bytes(b"x" * 1_000_000)
    assert budget.status(data, "downloads")["spent"] == pytest.approx(0.003)


def test_set_again_changes_the_limit_and_close_frees_the_name(data):
    made(data)
    budget.add(data, "annotations", 10)
    made(data, cap=60)
    assert budget.status(data, "annotations")["cap"] == 60
    assert budget.status(data, "annotations")["spent"] == 10  # the ledger stays
    budget.close(data, "annotations")
    assert budget.statuses(data) == []
    made(data, cap=20)
    assert budget.status(data, "annotations")["spent"] == 0


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda d: budget.add(d, "nope", 1), "no open budget nope"),
        (lambda d: budget.add(d, "annotations", -1), "positive"),
        (lambda d: budget.create(d, "x", 0, "usd"), "positive"),
        (lambda d: budget.create(d, "x", 5, "usd", path="/tmp"), "size unit"),
        (lambda d: budget.create(d, "Bad Name", 5, "usd"), "name"),
    ],
)
def test_bad_input_says_why(data, call, message):
    made(data)
    with pytest.raises(budget.BudgetError, match=message):
        call(data)


def test_states_are_near_at_eighty_percent_and_over_past_the_limit(data):
    made(data, cap=10)
    budget.add(data, "annotations", 7.9)
    assert budget.status(data, "annotations")["state"] == "ok"
    budget.add(data, "annotations", 0.1)
    assert budget.status(data, "annotations")["state"] == "near"


def test_a_budget_keeps_its_unit_until_it_is_closed(data):
    made(data)
    with pytest.raises(budget.BudgetError, match="counts usd; close it first"):
        made(data, unit="calls")


def test_settling_a_folder_budget_only_closes_the_hold(data, tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    made(data, "downloads", 1, "MB", path=str(folder))
    ticket = budget.reserve(data, "downloads", 0.5)
    (folder / "shard.bin").write_bytes(b"x" * 400_000)
    found = budget.settle(data, ticket)
    assert (found["spent"], found["reserved"]) == (0.4, 0.0)
    assert budget.entries(data, "downloads")[0]["state"] == "settled"


def test_a_missing_ledger_lists_no_budgets_without_creating_one(data):
    assert budget.statuses(data) == [] and not budget.ledger_path(data).exists()


# The commands


SESSION = "6942b4a0-7d35-4d5e-91a2-460a9fe6d7e6"


@pytest.fixture
def ax(env, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from ax.cli import app as cli

    monkeypatch.setenv("AX_CONFIG", str(env.config_path))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    monkeypatch.delenv("AX_INTENT", raising=False)
    work = tmp_path / "demo"
    work.mkdir()
    monkeypatch.chdir(work)

    def run(*args, intent=None):
        extra = {"AX_INTENT": intent} if intent else {}
        return CliRunner().invoke(cli, ["budget", *args], env=extra)

    run.data = env.config.data
    return run


def test_set_add_and_show_from_the_command_line(ax):
    import json

    made = ax("set", "annotations", "40", "--unit", "usd", "--why", "Luna labels")
    assert made.exit_code == 0 and "40 usd" in made.output
    assert ax("add", "annotations", "12.5", "--note", "batch 1").exit_code == 0
    shown = json.loads(ax("show", "annotations", "--json").output)
    assert shown["spent"] == 12.5 and shown["left"] == 27.5
    assert shown["owner"] == "ax:9fe6d7e6" and shown["scope"] == f"session:{SESSION}"
    assert shown["entries"][0]["note"] == "batch 1"
    assert shown["entries"][0]["agent"] == "ax:9fe6d7e6"
    listed = json.loads(ax("show", "--json").output)
    assert [b["name"] for b in listed] == ["annotations"]
    text = ax("show").output
    assert "annotations" in text and "12.5 of 40 usd" in text and "27.5 left" in text


def test_a_project_budget_belongs_to_the_repository(ax):
    import json

    ax("set", "downloads", "4", "--unit", "GB", "--project")
    found = json.loads(ax("show", "downloads", "--json").output)
    assert found["scope"] == "project:demo" and found["project"] == "demo"


def test_check_exits_zero_only_when_the_amount_fits(ax):
    ax("set", "annotations", "40", "--unit", "usd")
    ax("add", "annotations", "35")
    assert ax("check", "annotations", "5").exit_code == 0
    over = ax("check", "annotations", "6")
    assert over.exit_code == 1 and "1 over" in over.output


def test_going_over_pauses_and_a_reason_lets_it_through(ax):
    ax("set", "annotations", "40", "--unit", "usd")
    ax("add", "annotations", "38")
    paused = ax("add", "annotations", "5", "--note", "batch 9")
    assert paused.exit_code == 1 and paused.output.startswith("Pause:")
    assert "43 of 40 usd" in paused.output
    assert 'AX_INTENT="<why>" ax budget add annotations 5' in paused.output
    assert "agent that started" in paused.output  # what a subagent does instead
    passed = ax("add", "annotations", "5", "--note", "batch 9", intent="the user asked for it")
    assert passed.exit_code == 0
    assert budget.entries(ax.data, "annotations")[0]["intent"] == "the user asked for it"


def test_a_check_given_a_reason_goes_through_and_logs_it(ax):
    ax("set", "annotations", "10", "--unit", "usd")
    assert ax("check", "annotations", "11", intent="worth one more look").exit_code == 0
    [entry] = budget.entries(ax.data, "annotations")
    assert entry["kind"] == "pass" and entry["intent"] == "worth one more look"
    assert budget.status(ax.data, "annotations")["spent"] == 0


def test_reserve_settle_and_release_from_the_command_line(ax):
    import json

    ax("set", "annotations", "40", "--unit", "usd")
    held = json.loads(ax("reserve", "annotations", "5", "--note", "batch 3", "--json").output)
    assert held["ticket"] == "R1" and held["budget"]["reserved"] == 5
    assert ax("reserve", "annotations", "2").output.startswith("R2 ")
    assert ax("settle", "R1", "4.25").exit_code == 0
    assert ax("release", "R2").exit_code == 0
    found = budget.status(ax.data, "annotations")
    assert (found["spent"], found["reserved"]) == (4.25, 0)
    gone = ax("settle", "R1", "1")
    assert gone.exit_code == 2 and "already settled" in gone.output


def test_close_and_bad_input(ax):
    ax("set", "annotations", "40", "--unit", "usd")
    assert ax("close", "annotations").exit_code == 0
    missing = ax("add", "annotations", "1")
    assert missing.exit_code == 2 and "no open budget annotations" in missing.output
    assert ax("show").output.strip() == "no open budgets"

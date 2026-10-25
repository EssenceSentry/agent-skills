import json
from datetime import UTC, datetime

import pytest

from ax import learn, learn_guards, profile
from ax.store import Store
from learning import candidate, keep, messages, session

NOW = datetime(2026, 10, 25, tzinfo=UTC)
GOOD = r"git\s+push\s+(-f|--force)\b"


def answers(*replies):
    def model(prompt):
        model.prompts.append(prompt)
        return json.dumps(replies[min(len(model.prompts), len(replies)) - 1])

    model.prompts = []
    return model


def reply(pattern=GOOD, violations=("git push --force origin main", "git push -f origin feature")):
    return {"checkable": True, "pattern": pattern, "message": "Open a pull request instead.",
            "violations": list(violations)}  # fmt: skip


@pytest.fixture
def recent(archive):
    with Store(archive.config.db_path) as store:
        session(store.db, "recent")
        messages(store.db, "recent", ("tool", "ran `git push origin main`"),
                 ("tool", "ran `git status`"),
                 ("tool", 'ran `echo "git push --force is banned"`'))  # fmt: skip
        store.commit()
    return archive


@pytest.fixture
def pushes(recent):
    archive = recent
    cs = [candidate("a", "s1", "demo", commands=["git status", "git push --force origin main"]),
          candidate("b", "s2", "other", commands=["git push -f origin feature"])]  # fmt: skip
    labels = {c: keep("no-force-push", "Never force-push.", kind="never-rule") for c in "ab"}
    learn.propose(archive.config, cs, labels)
    return cs


def rule(archive, rule_id="no-force-push"):
    return next(r for r in profile.load_rules(archive.config) if r.id == rule_id)


def test_a_never_rule_gets_a_guard_that_catches_its_evidence_and_nothing_recent(archive, pushes):
    model = answers(reply())
    [result] = learn_guards.propose_guards(archive.config, pushes, model=model, now=NOW)
    assert result.status == "guarded" and (result.caught, result.evidence) == (2, 2)
    found = rule(archive)
    assert found.level == "block" and found.status == "proposed"
    assert found.guard == {"tool": "shell", "pattern": GOOD, "where": "command",
                           "message": "Open a pull request instead."}  # fmt: skip
    assert "caught 2 of 2" in found.why and "none of 3 commands" in found.why
    assert "git push --force origin main" in model.prompts[0]


def test_a_noisy_pattern_gets_one_retry_with_its_false_hits(archive, pushes):
    model = answers(reply(r"git\s+push"), reply())
    [result] = learn_guards.propose_guards(archive.config, pushes, model=model, now=NOW)
    assert result.status == "guarded" and len(model.prompts) == 2
    assert "git push origin main" in model.prompts[1]
    assert rule(archive).guard["pattern"] == GOOD


def test_a_pattern_noisy_twice_or_missing_its_evidence_is_dropped(archive, pushes):
    [noisy] = learn_guards.propose_guards(
        archive.config, pushes, model=answers(reply(r"git\s+push")), now=NOW
    )
    assert noisy.status == "noisy" and "git push origin main" in noisy.hits
    assert rule(archive).guard is None and rule(archive).level == "advice"
    learn_guards.forget(archive.config, "no-force-push")
    [missed] = learn_guards.propose_guards(
        archive.config, pushes, model=answers(reply(r"git\s+push\s+--force")), now=NOW
    )
    assert missed.status == "missed" and (missed.caught, missed.evidence) == (1, 2)
    assert rule(archive).guard is None


@pytest.mark.parametrize(
    "answer, status",
    [({"checkable": False}, "uncheckable"), (reply("git push ("), "invalid"),
     (reply(violations=["git log"]), "missed")],
)  # fmt: skip
def test_an_uncheckable_or_broken_answer_adds_no_guard(archive, pushes, answer, status):
    [result] = learn_guards.propose_guards(archive.config, pushes, model=answers(answer), now=NOW)
    assert result.status == status and rule(archive).guard is None


def test_only_never_rules_with_evidence_commands_are_asked_and_only_once(archive, pushes):
    cs = [candidate("c", "s3", "demo"), candidate("d", "s4", "demo")]
    labels = {c: keep("short-names", "Never use one-letter names.") for c in "cd"}
    labels |= {c["id"]: keep("no-force-push", "Never force-push.") for c in pushes}
    cs += [candidate("e", "s5", "demo", commands=["ls"]), candidate("f", "s6", "demo")]
    labels |= {c: keep("tests-first", "Write the tests first.") for c in "ef"}
    learn.propose(archive.config, cs + pushes, labels)
    model = answers(reply())
    results = learn_guards.propose_guards(archive.config, cs + pushes, model=model, now=NOW)
    assert [r.rule for r in results] == ["no-force-push"] and len(model.prompts) == 1
    assert learn_guards.propose_guards(archive.config, cs + pushes, model=model, now=NOW) == []
    assert len(model.prompts) == 1


def test_guarding_an_escalated_active_rule_enforces_the_pattern(recent):
    config = recent.config
    profile.add(config, "no-force-push", rule="Never force-push.", added="2026-09-01",
                review="escalate: corrected again in 2 sessions since 2026-09-01")  # fmt: skip
    cs = [candidate("a", "s1", "demo", ts="2026-10-10T10:00:00Z",
                    commands=["git push --force origin main"]),
          candidate("b", "s2", "other", ts="2026-10-12T10:00:00Z",
                    commands=["git push -f origin feature"])]  # fmt: skip
    labels = {c["id"]: keep("no-force-push", "Never force-push.") for c in cs}
    result = learn_guards.guard_rule(
        config, "no-force-push", cs, labels, model=answers(reply()), now=NOW
    )
    assert result.status == "guarded"
    found = rule(recent)
    assert found.status == "active" and found.level == "block" and not found.review
    assert found.guard["pattern"] == GOOD
    with pytest.raises(ValueError):
        learn_guards.guard_rule(config, "missing", cs, labels, model=answers(reply()), now=NOW)

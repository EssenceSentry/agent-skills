import json
from datetime import date

import pytest
from typer.testing import CliRunner

from ax import learn, learn_life, profile
from ax.cli import app
from ax.learn_life import Event
from learning import candidate, keep

TODAY = date(2026, 10, 25)


def rule(added, **fields):
    return profile.Rule(id="r", rule="Leave unrelated files alone.", added=added, **fields)


def assess(added, events=(), **fields):
    return learn_life.assess(rule(added, **fields), list(events), TODAY)


def test_confidence_halves_every_90_days_and_counts_what_goes_against_4x():
    assert assess("2026-10-25")["confidence"] == 1.0  # adopting the rule is its first evidence
    assert assess("2026-07-27")["confidence"] == 0.5
    assert assess("2026-10-25", [Event("2026-10-25", "recurrence")])["confidence"] == -3.0
    assert assess("2026-10-25", [Event("2026-10-25", "support", weight=3)])["confidence"] == 4.0


def test_maturity_grows_with_age_and_fresh_evidence():
    blocks = [Event("2026-10-20", "block"), Event("2026-10-22", "block")]
    assert assess("2026-10-01")["maturity"] == "new"
    assert assess("2026-09-01")["maturity"] == "established"
    assert assess("2026-06-01", blocks)["maturity"] == "proven"
    recurred = [*blocks, Event("2026-08-01", "recurrence")]
    assert assess("2026-06-01", recurred)["maturity"] == "established"
    assert assess("2026-10-01", [Event("2026-10-20", "override")])["maturity"] == "doubtful"


def test_two_recurrences_since_the_last_review_ask_for_a_guard_or_a_rewrite():
    two = [Event("2026-10-10", "recurrence", note="Sessions/a.md"),
           Event("2026-10-12", "recurrence", note="Sessions/b.md")]  # fmt: skip
    found = assess("2026-09-01", two)
    assert found["review"].startswith("escalate:") and "ax learn guard r" in found["review"]
    assert found["recurrences"] == 2
    assert assess("2026-09-01", two, reviewed="2026-10-11")["review"] == ""
    assert "widen the guard" in assess("2026-09-01", two, level="block")["review"]


def test_an_override_asks_for_a_narrower_scope():
    found = assess("2026-09-01", [Event("2026-10-10", "override", project="atelier")])
    assert found["review"].startswith("narrow:") and "atelier" in found["review"]
    assert found["overrides"] == 1


def test_a_rule_with_no_evidence_in_90_days_is_put_up_for_retirement():
    assert assess("2026-06-01")["review"].startswith("retire:")
    assert assess("2026-06-01", reviewed="2026-09-01")["review"] == ""
    assert assess("2026-06-01", [Event("2026-10-01", "block")])["review"] == ""


@pytest.fixture
def restated(archive):
    profile.add(archive.config, "unrelated-files", rule="Leave unrelated files alone.",
                added="2026-09-01")  # fmt: skip
    cs = [candidate("a", "s1", "demo", ts="2026-08-20T10:00:00Z"),
          candidate("b", "s2", "demo", ts="2026-10-10T10:00:00Z"),
          candidate("c", "s3", "other", ts="2026-10-12T10:00:00Z", signals=["frustration"]),
          candidate("d", "s4", "atelier", ts="2026-10-21T10:00:00Z")]  # fmt: skip
    labels = {
        "a": keep("unrelated-files"), "b": keep("unrelated-files"),
        "c": keep("unrelated-files", frustrated=True),
        "d": {**keep("typings", "Edit the typings this time.", kind="none", lasting=False),
              "against": "unrelated-files"},
    }  # fmt: skip
    (archive.config.data / "guard.jsonl").write_text(
        json.dumps({"ts": "2026-10-22T10:00:00-0300", "rule": "unrelated-files"}) + "\n"
    )
    return cs, labels


def test_events_come_from_restatements_overrides_and_guard_blocks(archive, restated):
    found = learn_life.events(archive.config, *restated)["unrelated-files"]
    assert sorted((e.day, e.kind, e.weight) for e in found) == [
        ("2026-08-20", "support", 1), ("2026-10-10", "recurrence", 1),
        ("2026-10-12", "recurrence", 3), ("2026-10-21", "override", 1),
        ("2026-10-22", "block", 1),
    ]  # fmt: skip


def test_refresh_writes_the_lifecycle_into_active_notes_only_when_it_changes(archive, restated):
    changed = learn_life.refresh(archive.config, *restated, today=TODAY)
    assert [r.id for r in changed] == ["unrelated-files"]
    [note] = profile.load_rules(archive.config)
    assert (note.support, note.recurrences, note.blocks, note.overrides) == (1, 2, 1, 1)
    assert note.maturity == "doubtful" and note.review.startswith("escalate:")
    assert note.last_evidence == "2026-10-22"
    assert learn_life.refresh(archive.config, *restated, today=TODAY) == []


def test_keep_clears_the_review_and_retire_ends_the_rule(archive, restated):
    learn_life.refresh(archive.config, *restated, today=TODAY)
    learn_life.keep(archive.config, "unrelated-files", today=TODAY)
    [note] = profile.load_rules(archive.config)
    assert note.reviewed == "2026-10-25" and not note.review
    learn_life.refresh(archive.config, *restated, today=TODAY)
    [note] = profile.load_rules(archive.config)
    assert not note.review  # the recurrences predate the review
    learn_life.retire(archive.config, "unrelated-files")
    [note] = profile.load_rules(archive.config)
    assert note.status == "retired"
    with pytest.raises(ValueError):
        learn_life.keep(archive.config, "unrelated-files")


def test_replacing_a_rule_keeps_when_the_user_last_reviewed_it(archive):
    profile.add(archive.config, "tabs", rule="Use tabs.", reviewed="2026-10-01")
    profile.add(archive.config, "tabs", rule="Indent with tabs.", replace=True)
    [note] = profile.load_rules(archive.config)
    assert note.reviewed == "2026-10-01" and note.rule == "Indent with tabs."


def test_labels_name_the_rule_a_message_overrides(archive):
    profile.add(archive.config, "unrelated-files", rule="Leave unrelated files alone.")

    def model(prompt):
        assert '"against"' in prompt
        return json.dumps([{"id": "a", "kind": "none", "against": "Unrelated Files"}])

    labels = learn.label(archive.config, [candidate("a", "s1", "demo")], model=model)
    assert labels["a"]["against"] == "unrelated-files"


def test_sync_refreshes_the_lifecycle_without_calling_a_model(env, monkeypatch):
    profile.add(env.config, "unrelated-files", rule="Leave unrelated files alone.")
    monkeypatch.setattr(learn, "label", lambda *a, **k: pytest.fail("labelled on sync"))
    result = CliRunner().invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 0, result.output
    [note] = profile.load_rules(env.config)
    assert note.maturity == "new" and note.confidence == 1.0
    assert (env.config.data / "learn" / "candidates.jsonl").exists()


def test_sync_labels_new_candidates_when_configured(env, monkeypatch):
    env.config_path.write_text(env.config_path.read_text() + "\n[learn]\nlabel_on_sync = true\n")
    asked = []
    monkeypatch.setattr(learn, "label", lambda config, found, **k: asked.append(found) or {})
    result = CliRunner().invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 0, result.output
    assert len(asked) == 1


def test_sync_refreshes_the_lifecycle_under_the_sync_lock(env, monkeypatch):
    from ax import sync as sync_module

    def check(config):
        with pytest.raises(sync_module.SyncBusy), sync_module.lock(config):
            pass
        return []

    monkeypatch.setattr(learn_life, "after_sync", check)
    result = CliRunner().invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 0, result.output


def test_accepting_dates_the_adoption_so_evidence_from_the_queue_supports_the_rule(archive):
    cs = [candidate("a", "s1", "demo", ts="2026-09-10T10:00:00Z"),
          candidate("b", "s2", "demo", ts="2026-09-20T10:00:00Z")]  # fmt: skip
    labels = {c["id"]: keep("tabs", "Use tabs.") for c in cs}
    learn.propose(archive.config, cs, labels)
    [note] = profile.load_rules(archive.config)
    note.added = "2026-09-01"  # proposed then; it waited in the queue
    profile._write(note, note.path)
    learn.accept(archive.config, "tabs", today=date(2026, 10, 1))
    [note] = profile.load_rules(archive.config)
    assert note.added == "2026-10-01"
    learn_life.refresh(archive.config, cs, labels, today=TODAY)
    [note] = profile.load_rules(archive.config)
    assert (note.support, note.recurrences) == (2, 0) and not note.review


def test_an_override_from_before_the_adoption_does_not_count(archive):
    profile.add(archive.config, "tabs", rule="Use tabs.", added="2026-09-01")
    cs = [candidate("a", "s1", "demo", ts="2026-08-20T10:00:00Z"),
          candidate("b", "s2", "demo", ts="2026-09-20T10:00:00Z")]  # fmt: skip
    labels = {c["id"]: {**keep("spaces", "Use spaces here.", kind="none"), "against": "tabs"}
              for c in cs}  # fmt: skip
    [override] = learn_life.events(archive.config, cs, labels)["tabs"]
    assert (override.kind, override.day) == ("override", "2026-09-20")

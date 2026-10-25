import json

from ax import learn, learn_tidy, profile
from learning import candidate, keep


def answer(duplicates=(), contradictions=()):
    def model(prompt):
        model.prompts.append(prompt)
        return json.dumps({"duplicates": list(duplicates), "contradictions": list(contradictions)})

    model.prompts = []
    return model


def compat(archive):
    cs = [candidate(c, f"s{c}", "ac") for c in "abcd"]
    labels = {
        "a": keep("no-backward-compatibility", "Never maintain backward compatibility."),
        "b": keep("no-backward-compatibility", "Never maintain backward compatibility."),
        "c": keep("no-multilabel-compat", "Do not keep compatibility for the multilabel API."),
        "d": keep("no-multilabel-compat", "Do not keep compatibility for the multilabel API."),
    }  # fmt: skip
    learn.propose(archive.config, cs, labels)
    return cs, labels


def rules(archive):
    return {r.id: r for r in profile.load_rules(archive.config)}


def test_tidy_merges_a_special_case_into_the_general_proposal(archive):
    cs, labels = compat(archive)
    model = answer(duplicates=[{"keep": "no-backward-compatibility",
                                "drop": "no-multilabel-compat", "why": "a special case"}])  # fmt: skip
    report = learn_tidy.tidy(archive.config, model=model)
    assert report.merged == [("no-multilabel-compat", "no-backward-compatibility")]
    found = rules(archive)
    assert "no-multilabel-compat" not in found
    kept = found["no-backward-compatibility"]
    assert "no-multilabel-compat" in kept.covers and set(kept.evidence) == set("abcd")
    assert "Do not keep compatibility for the multilabel API." in model.prompts[0]


def test_proposing_again_folds_a_merged_topic_in_and_keeps_the_wording(archive):
    cs, labels = compat(archive)
    learn_tidy.tidy(archive.config, model=answer(duplicates=[
        {"keep": "no-backward-compatibility", "drop": "no-multilabel-compat"}]))  # fmt: skip
    note = rules(archive)["no-backward-compatibility"]
    note.rule = "Never keep backward compatibility; make breaking changes directly."
    profile._write(note, note.path)  # the user fixed the wording before deciding
    learn.propose(archive.config, cs, labels)
    found = rules(archive)
    assert "no-multilabel-compat" not in found
    kept = found["no-backward-compatibility"]
    assert kept.rule == "Never keep backward compatibility; make breaking changes directly."
    assert "4 sessions" in kept.why and set(kept.evidence) == set("abcd")


def test_a_proposal_that_restates_an_active_rule_is_dropped_into_it(archive):
    profile.add(archive.config, "compat", rule="Never maintain backward compatibility.")
    cs = [candidate("c", "s1", "ac"), candidate("d", "s2", "ac")]
    labels = {c: keep("multilabel-api", "Drop compatibility for the multilabel API.") for c in "cd"}
    learn.propose(archive.config, cs, labels)
    learn_tidy.tidy(archive.config, model=answer(duplicates=[
        {"keep": "multilabel-api", "drop": "compat"}]))  # fmt: skip
    found = rules(archive)
    assert "multilabel-api" not in found and found["compat"].status == "active"
    assert found["compat"].rule == "Never maintain backward compatibility."
    assert "multilabel-api" in found["compat"].covers
    assert learn.propose(archive.config, cs, labels) == []
    assert learn.reinforcement(archive.config, cs, labels)["compat"]["support"] == 2


def test_tidy_flags_a_contradiction_once_and_ignores_unknown_ids(archive):
    profile.add(archive.config, "both-themes", rule="Give every page a light and a dark theme.")
    cs = [candidate("a", "s1", "demo"), candidate("b", "s2", "other")]
    labels = {
        c: keep("single-theme", "Use one theme without light and dark variants.") for c in "ab"
    }
    learn.propose(archive.config, cs, labels)
    model = answer(
        duplicates=[{"keep": "ghost", "drop": "single-theme"}],
        contradictions=[{"a": "single-theme", "b": "both-themes", "why": "one theme or two"}],
    )
    for _ in range(2):
        report = learn_tidy.tidy(archive.config, model=model)
    assert report.flagged == [("single-theme", "both-themes", "one theme or two")]
    single = rules(archive)["single-theme"]
    assert single.why.count("[[Profile/rules/both-themes|both-themes]]") == 1
    assert "both-themes" in rules(archive) and report.merged == []


def test_tidy_with_fewer_than_two_rules_asks_nothing(archive):
    model = answer()
    report = learn_tidy.tidy(archive.config, model=model)
    assert model.prompts == [] and report.merged == [] and report.flagged == []


def test_proposing_again_keeps_a_contradiction_note(archive):
    profile.add(archive.config, "both-themes", rule="Give every page a light and a dark theme.")
    cs = [candidate("a", "s1", "demo"), candidate("b", "s2", "other")]
    labels = {
        c: keep("single-theme", "Use one theme without light and dark variants.") for c in "ab"
    }
    learn.propose(archive.config, cs, labels)
    learn_tidy.tidy(archive.config, model=answer(contradictions=[
        {"a": "single-theme", "b": "both-themes", "why": "one theme or two"}]))  # fmt: skip
    learn.propose(archive.config, cs, labels)
    assert "May contradict [[Profile/rules/both-themes" in rules(archive)["single-theme"].why


def test_a_proposal_accepted_while_tidy_waits_is_not_merged_away(archive):
    compat(archive)

    def accepting(prompt):
        learn.accept(archive.config, "no-multilabel-compat")
        return json.dumps({"duplicates": [{"keep": "no-backward-compatibility",
                                           "drop": "no-multilabel-compat"}]})  # fmt: skip

    report = learn_tidy.tidy(archive.config, model=accepting)
    assert report.merged == [] and rules(archive)["no-multilabel-compat"].status == "active"


def test_ids_that_are_not_strings_are_ignored(archive):
    compat(archive)
    model = answer(duplicates=[{"keep": ["no-backward-compatibility"], "drop": "no-multilabel-compat"}],
                   contradictions=[{"a": {"x": 1}, "b": "no-backward-compatibility"}])  # fmt: skip
    report = learn_tidy.tidy(archive.config, model=model)
    assert report.merged == [] and report.flagged == []

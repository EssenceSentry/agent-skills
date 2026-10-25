import json

import pytest
from typer.testing import CliRunner

from ax import learn, profile
from ax.cli import app
from ax.store import Store
from learning import candidate, keep, messages, session


def test_scan_reads_only_the_users_own_corrections(archive):
    found = {c["text"]: c for c in learn.scan(archive.config)}
    assert "Don't touch files unrelated to what I asked for." in found
    first = found["Don't touch files unrelated to what I asked for."]
    assert first["signals"] == ["phrase"] and "typings" in first["context"]
    after = found["Use the bootstrap script, it keeps the editable install."]
    assert after["signals"] == ["interrupted"] and after["project"] == "other"
    assert "Stop adding compatibility shims." in found  # the request, without the attachments
    texts = " ".join(found)
    assert "delegated worker" not in texts and "Do not edit files." not in texts
    assert "PLEASE IMPLEMENT" not in texts and "I don't know" not in texts
    assert "Thanks, looks good." not in texts
    memory = next(c for c in found.values() if c["source"] == "codex-memory")
    assert memory["project"] == "auto-classifier" and "breaking changes" in memory["text"]


def test_scan_finds_frustration_explicit_requests_and_praise(env):
    with Store(env.config.db_path) as store:
        session(store.db, "f1")
        messages(store.db, "f1",
                 ("user", "Train the model on the reviewed rows and report the AUC on the test split."),
                 ("assistant", "Starting the run."),
                 ("tool", "ran `uv run python train.py --all-rows`"),
                 ("assistant", "Done: AUC 0.97 on all rows."),
                 ("user", "Very disappointing! You trained on the test rows."),
                 ("assistant", "I added the plotting cell; titles are gone and the axes are labelled."),
                 ("user", "Perfect, that's exactly how I want plots."),
                 ("assistant", "Pushed the branch and opened the dashboard for you to review."),
                 ("user", "Great, now run the audit."),
                 ("user", "Remember: the testing split is never used for training."))  # fmt: skip
        store.commit()
    found = {c["text"]: c for c in learn.scan(env.config)}
    angry = found["Very disappointing! You trained on the test rows."]
    assert angry["signals"] == ["frustration"]
    assert angry["episode"].startswith("user: Train the model on the reviewed rows")
    assert "tool: uv run python train.py --all-rows" in angry["episode"]
    assert "agent: Done: AUC 0.97 on all rows." in angry["episode"]
    assert angry["commands"] == ["uv run python train.py --all-rows"]
    praised = found["Perfect, that's exactly how I want plots."]
    assert praised["signals"] == ["praise"] and "titles are gone" in praised["context"]
    assert "Great, now run the audit." not in found  # praise that only moves on
    told = found["Remember: the testing split is never used for training."]
    assert told["signals"] == ["explicit", "phrase"]


@pytest.mark.parametrize(
    "text, marked",
    [
        ("I'm very disappointed with you.", True),
        ("Why did you run it on everything?!", True),
        ("DO NOT TOUCH THE CACHE FOLDER", True),
        ("How many times do I have to say it", True),
        ("You just had to run the repository that was proven to work!", True),
        ("Run the AWS S3 sync with the KMS key.", False),
        ("This looks good, thanks!", False),
        ("Use a LEFT OUTER JOIN here.", False),
        ("Check the GCP BQ API quota.", False),
        ("The regex (?!foo) is a negative lookahead.", False),
        ("Run this:\n```\nSELECT * FROM T WHERE X!!\n```", False),
        ("Why `git push --force`?!", True),
        ("PLEASE STOP NOW", True),
    ],
)
def test_frustration_markers(text, marked):
    assert bool(learn.frustrated(text)) is marked


def test_scan_reads_the_reason_for_a_rejected_tool_call(env):
    said = (
        "The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if "
        "it was a file edit, the new_string was NOT written to the file). To tell you how to "
        "proceed, the user said:\nNever force-push; open a pull request instead."
    )
    records = [
        {"type": "assistant", "timestamp": "2026-10-02T10:00:00Z", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "git push --force origin main"}}]}},
        {"type": "user", "timestamp": "2026-10-02T10:00:05Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": said}]}},
        {"type": "assistant", "timestamp": "2026-10-02T10:01:00Z", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/x/a.py"}}]}},
        {"type": "user", "timestamp": "2026-10-02T10:01:05Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t2",
             "content": "The user doesn't want to proceed with this tool use."}]}},
    ]  # fmt: skip
    transcript = env.root / "rejected.jsonl"
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
    with Store(env.config.db_path) as store:
        session(store.db, "c1", provider="claude", entrypoint="claude-desktop")
        store.db.execute("UPDATE sessions SET source_path = ? WHERE key = 'c1'", (str(transcript),))
        store.commit()
    [found] = [c for c in learn.scan(env.config) if c["source"] == "rejection"]
    assert found["text"] == "Never force-push; open a pull request instead."
    assert found["signals"] == ["rejection"] and found["commands"] == [
        "git push --force origin main"
    ]
    assert "git push --force origin main" in found["context"] and found["ts"].startswith(
        "2026-10-02"
    )


class FakeModel:
    def __init__(self, label):
        self.label, self.prompts = label, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        ids = [line.split('"id": "', 1)[1].split('"', 1)[0] for line in prompt.splitlines()
               if line.startswith('{"id": "')]  # fmt: skip
        return json.dumps([{**self.label(i), "id": i} for i in ids])


def test_label_redacts_batches_and_never_labels_twice(archive):
    candidates = learn.scan(archive.config)
    candidates[0]["text"] += " token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    model = FakeModel(lambda i: keep("scope"))
    labels = learn.label(archive.config, candidates, model=model, batch=2)
    assert set(labels) == {c["id"] for c in candidates}
    assert len(model.prompts) == (len(candidates) + 1) // 2
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in "".join(model.prompts)
    again = FakeModel(lambda i: keep("scope"))
    learn.label(archive.config, candidates, model=again)
    assert again.prompts == []


def test_frustration_moments_are_labelled_with_their_episode(archive):
    angry = {
        **candidate("f", "s1", "demo", text="Very disappointing!", signals=["frustration"]),
        "episode": "user: Train on the reviewed rows\ntool: python train.py --all-rows",
    }
    cs = [angry, candidate("p", "s2", "demo")]
    model = FakeModel(lambda i: keep("test-split", frustrated=i == "f"))
    labels = learn.label(archive.config, cs, model=model)
    assert labels["f"]["frustrated"] is True and "frustrated" not in labels["p"]
    [prompt] = [p for p in model.prompts if "train.py --all-rows" in p]
    assert '"id": "p"' not in prompt


def test_a_frustration_moment_labelled_without_its_episode_is_labelled_again(archive):
    angry = candidate("f", "s1", "demo", text="Very disappointing!", signals=["frustration"])
    learn.label(
        archive.config, [{**angry, "signals": ["phrase"]}], model=FakeModel(lambda i: keep("x"))
    )
    assert learn.unlabelled([angry], learn.load_labels(archive.config)) == [angry]
    model = FakeModel(lambda i: keep("x", frustrated=True))
    labels = learn.label(archive.config, [angry], model=model)
    assert labels["f"]["frustrated"] is True and len(model.prompts) == 1
    assert learn.unlabelled([angry], labels) == []


def test_two_sessions_make_a_repo_proposal_and_two_projects_a_global_one(archive):
    cs = [candidate("a", "s1", "demo"), candidate("b", "s2", "demo"),
          candidate("c", "s3", "demo"), candidate("d", "s4", "other"),
          candidate("e", "s5", "demo")]  # fmt: skip
    labels = {
        "a": keep("unrelated-files"), "b": keep("unrelated-files"),
        "c": keep("no-shims", "Drop backward compatibility shims."),
        "d": keep("no-shims", "Drop backward-compatibility shims."),
        "e": keep("one-off", "Use tabs."),
    }  # fmt: skip
    found = {p.id: p for p in learn.propose(archive.config, cs, labels)}
    assert found["unrelated-files"].scope == "repo:demo"
    assert found["no-shims"].scope == "global" and "one-off" not in found
    note = profile.load_rules(archive.config)
    proposed = {r.id: r for r in note if r.status == "proposed"}
    assert set(proposed) == {"unrelated-files", "no-shims"}
    assert (
        "2 sessions" in proposed["no-shims"].why and "[[Sessions/s3]]" in proposed["no-shims"].why
    )


def test_one_explicit_request_or_one_frustration_moment_is_enough(archive):
    cs = [candidate("a", "s1", "demo", signals=["explicit"]),
          candidate("b", "s2", "demo", signals=["frustration"]),
          candidate("c", "s3", "demo", signals=["frustration"]),
          candidate("d", "s4", "demo")]  # fmt: skip
    labels = {
        "a": keep("split-roles", "Never train on the testing split."),
        "b": keep("check-long-runs", "Check results before a long run goes on.", frustrated=True),
        "c": keep("tabs", "Use tabs.", frustrated=False),
        "d": keep("spaces", "Use spaces."),
    }  # fmt: skip
    found = {p.id: p for p in learn.propose(archive.config, cs, labels)}
    assert set(found) == {"split-roles", "check-long-runs"}
    assert "1 frustration moment" in found["check-long-runs"].why
    assert "asked to remember" in found["split-roles"].why


def test_a_group_that_restates_an_active_rule_reinforces_it(archive):
    profile.add(archive.config, "unrelated-files", rule="Leave unrelated files alone.",
                added="2026-10-05")  # fmt: skip
    cs = [candidate("a", "s1", "demo", ts="2026-10-01T10:00:00Z"),
          candidate("b", "s2", "demo", ts="2026-10-20T10:00:00Z")]  # fmt: skip
    labels = {"a": keep("unrelated-files"), "b": keep("unrelated-files")}
    assert learn.propose(archive.config, cs, labels) == []
    report = learn.reinforcement(archive.config, cs, labels)
    assert report["unrelated-files"] == {"support": 2, "recurrences": 1}


def test_a_rejected_proposal_returns_only_when_its_support_doubles(archive):
    cs = [candidate(str(i), f"s{i}", "demo") for i in range(2)]
    labels = {c["id"]: keep("tabs", "Use tabs.") for c in cs}
    learn.propose(archive.config, cs, labels)
    learn.reject(archive.config, "tabs")
    assert not any(r.id == "tabs" for r in profile.load_rules(archive.config))
    assert learn.propose(archive.config, cs, labels) == []
    more = [candidate(str(i), f"s{i}", "demo") for i in range(4)]
    labels = {c["id"]: keep("tabs", "Use tabs.") for c in more}
    assert [p.id for p in learn.propose(archive.config, more, labels)] == ["tabs"]


def test_accept_activates_a_proposal(archive):
    cs = [candidate(str(i), f"s{i}", "demo") for i in range(2)]
    learn.propose(archive.config, cs, {c["id"]: keep("tabs", "Use tabs.") for c in cs})
    learn.accept(archive.config, "tabs")
    [rule] = [r for r in profile.load_rules(archive.config) if r.id == "tabs"]
    assert rule.status == "active"
    with pytest.raises(ValueError):
        learn.accept(archive.config, "missing")


def test_recall_counts_known_rules_the_learner_rediscovered(archive):
    profile.add(archive.config, "no-trailer", rule="Never add a co-author trailer.")
    profile.add(archive.config, "no-green", rule="Avoid green in designs.")
    cs = [candidate("a", "s1", "demo"), candidate("b", "s2", "other")]
    labels = {"a": keep("no-trailer", "Never add a co-author trailer to commits."),
              "b": keep("no-trailer", "No co-author trailer.")}  # fmt: skip
    found = learn.recall(archive.config, cs, labels)
    assert found["found"] == ["no-trailer"] and found["missed"] == ["no-green"]


def test_cli_scan_and_list(archive):
    def run(*args):
        return CliRunner().invoke(
            app, ["learn", *args], env={"AX_CONFIG": str(archive.config_path)}
        )

    scanned = run("scan")
    assert scanned.exit_code == 0, scanned.output
    assert "candidates" in scanned.output
    assert (archive.config.data / "learn" / "candidates.jsonl").exists()
    assert run("list").exit_code == 0


def test_calls_counts_episodes_in_smaller_batches():
    plain = [candidate(str(i), "s", "demo") for i in range(21)]
    angry = [candidate(f"f{i}", "s", "demo", signals=["frustration"]) for i in range(6)]
    assert learn.calls(plain + angry, batch=20) == 2 + 2


@pytest.mark.parametrize(
    "text, explicit",
    [("Remember: never train on the testing split.", True),
     ("From now on, ask before pushing.", True),
     ("In the future, ask before pushing.", True),
     ("Keep the launcher there for potential future repurposing.", False),
     ("Set up SSO now so it is ready in the future.", False)],
)  # fmt: skip
def test_explicit_means_a_request_to_remember(text, explicit):
    assert ("explicit" in learn._signals(text, "", False)) is explicit


def test_only_the_strongest_proposals_wait_for_review_at_once(archive):
    cs = [candidate("a", "s1", "demo", signals=["frustration"]),
          candidate("b1", "s2", "demo", ts="2026-10-01T10:00:00Z"),
          candidate("b2", "s3", "demo", ts="2026-10-02T10:00:00Z"),
          candidate("c", "s4", "demo", signals=["explicit"]),
          candidate("d1", "s5", "demo", ts="2026-10-20T10:00:00Z"),
          candidate("d2", "s6", "demo", ts="2026-10-21T10:00:00Z")]  # fmt: skip
    labels = {"a": keep("check-runs", "Check results before long runs.", frustrated=True),
              "b1": keep("tabs", "Use tabs."), "b2": keep("tabs", "Use tabs."),
              "c": keep("no-pickle", "Never use pickle."),
              "d1": keep("short-names", "Use short names."),
              "d2": keep("short-names", "Use short names.")}  # fmt: skip
    found = learn.propose(archive.config, cs, labels, max_pending=2)
    assert [r.id for r in found] == ["check-runs", "short-names"] and found.waiting == 2
    again = learn.propose(archive.config, cs, labels, max_pending=2)
    assert again == [] or {r.id for r in again} <= {"check-runs", "short-names"}
    assert again.waiting == 2
    learn.reject(archive.config, "short-names")
    assert [r.id for r in learn.propose(archive.config, cs, labels, max_pending=2)
            if r.id not in ("check-runs",)] == ["tabs"]  # fmt: skip


def test_a_long_frustrated_message_still_gets_the_work_before_it():
    turns = [("user", "Train the model on the reviewed rows and report the AUC on the test split."),
             ("tool", "uv run python train.py --all-rows"), ("assistant", "Done: AUC 0.97.")]  # fmt: skip
    angry = "Very disappointing! You trained on the test rows again after I said to use the reviewed split."
    episode = learn._episode([*turns, ("user", angry)])
    assert episode.startswith("user: Train the model on the reviewed rows")
    assert "tool: uv run python train.py --all-rows" in episode and episode.endswith(angry)


def test_a_frustration_label_made_from_another_episode_is_made_again(archive):
    angry = {**candidate("f", "s1", "demo", text="Very disappointing!", signals=["frustration"]),
             "episode": "user: Very disappointing!"}  # fmt: skip
    learn.label(archive.config, [angry], model=FakeModel(lambda i: keep("x", frustrated=True)))
    assert learn.unlabelled([angry], learn.load_labels(archive.config)) == []
    fuller = {**angry, "episode": "user: Train on the reviewed rows\nuser: Very disappointing!"}
    assert learn.unlabelled([fuller], learn.load_labels(archive.config)) == [fuller]


def test_refreshing_a_proposal_replaces_only_its_own_summary(archive):
    cs = [candidate("a", "s1", "demo"), candidate("b", "s2", "demo")]
    labels = {c["id"]: keep("tabs", "Use tabs.") for c in cs}
    learn.propose(archive.config, cs, labels)
    [note] = profile.load_rules(archive.config)
    kept = ["Merged in `indent` (\"Indent with tabs.\"):\n- [[Sessions/s9]] 2026-10-01: \"tabs\"",
            "Guard: `\\t` caught 1 of 1 evidence commands.", "My note: ask the team first."]  # fmt: skip
    note.why = "\n\n".join([note.why, *kept])
    note.evidence = [*note.evidence, "recurring error: tab width"]
    profile._write(note, note.path)
    more = [*cs, candidate("c", "s3", "demo")]
    learn.propose(archive.config, more, {c["id"]: keep("tabs", "Use tabs.") for c in more})
    [note] = profile.load_rules(archive.config)
    assert note.why.count("Proposed by `ax learn`") == 1 and "3 sessions" in note.why
    assert all(note.why.count(k) == 1 for k in kept)
    assert {"a", "b", "c", "recurring error: tab width"} <= set(note.evidence)


def test_a_group_that_matches_a_fix_proposal_adds_its_evidence_below_it(archive):
    profile.add(archive.config, "no-timeout", rule="Use `gtimeout`, not `timeout`, on macOS.",
                status="proposed", why="Proposed by `ax learn fixes` from an error.",
                evidence=["recurring error: timeout"])  # fmt: skip
    cs = [candidate("a", "s1", "demo"), candidate("b", "s2", "demo")]
    labels = {c["id"]: keep("no-timeout", "Use gtimeout on macOS.") for c in cs}
    learn.propose(archive.config, cs, labels)
    [note] = profile.load_rules(archive.config)
    assert note.why.startswith("Proposed by `ax learn fixes`") and "2 sessions" in note.why
    assert {"recurring error: timeout", "a", "b"} <= set(note.evidence)


def test_a_group_matches_a_rule_through_any_of_its_topics():
    group = learn.Group("indent-with-tabs", [
        (candidate("a", "s1", "demo"), keep("indent-with-tabs", "Indent with tabs.")),
        (candidate("b", "s2", "demo"), keep("tabs", "Use tabs."))])  # fmt: skip
    merged = profile.Rule(id="whitespace", rule="Prefer spaces in YAML.", covers=["tabs"])
    assert learn._matches(group, merged)


def test_a_rejected_proposal_stays_rejected_under_a_new_topic(archive):
    cs = [candidate("a", "s1", "demo"), candidate("b", "s2", "demo")]
    learn.propose(archive.config, cs, {c["id"]: keep("tabs", "Use tabs.") for c in cs})
    learn.reject(archive.config, "tabs")
    more = [candidate("c", "s1", "demo"), candidate("d", "s2", "demo"),
            candidate("e", "s3", "demo")]  # fmt: skip
    labels = {c["id"]: keep("tabs", "Use tabs.") for c in cs}
    labels |= {c["id"]: keep("tab-indent", "Use tabs.") for c in more}
    assert learn.propose(archive.config, cs + more, labels) == []  # 3 sessions, not 4

"""The card a chat shows for a job its session is waiting on: only what is still going,
and only Haiku's last word on it."""

import json
from datetime import UTC, datetime, timedelta

from ax import job_card, job_sources, jobs

S1 = {"CLAUDE_CODE_SESSION_ID": "s-1"}


def append(env, key, *lines):
    with open(jobs.events_path(env.config, key), "a") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return jobs.refresh(env.config, key)


def test_a_card_shows_progress_stage_and_only_the_last_look(env):
    jobs.new(env.config, "score", total=40, unit="rows", label="Score rows; then audit", env=S1)
    job = append(env, "score", {"done": 10, "stage": "scoring"})
    for summary in ("Downloading shards.", "Scoring rows, 10 of 40 done."):
        jobs.record_event(env.config, "score", "look", {"summary": summary, "problem": None})
    card = job_card.card(env.config, job)
    assert (card["key"], card["label"], card["status"], card["stage"]) == (
        "score", "Score rows; then audit", "running", "scoring",
    )  # fmt: skip
    assert card["progress"] == {"done": 10, "total": 40, "unit": "rows", "percent": 25,
                                "text": "10/40 rows (25%)"}  # fmt: skip
    assert card["look"]["summary"] == "Scoring rows, 10 of 40 done."
    assert card["page"] == "/jobs/score/" and card["attention"] is None


def test_a_card_without_counts_has_no_bar(env):
    job = jobs.new(env.config, "push", label="Push the image", env=S1)
    card = job_card.card(env.config, job)
    assert card["progress"]["percent"] is None and card["look"] is None


def test_a_sessions_cards_are_its_own_running_jobs(env):
    jobs.new(env.config, "mine", label="Mine", env=S1)
    jobs.new(env.config, "theirs", label="Theirs", env={"CLAUDE_CODE_SESSION_ID": "s-2"})
    jobs.new(env.config, "finished", label="Finished", env=S1)
    append(env, "finished", {"status": "done"})
    jobs.new(env.config, "codex", label="Codex", env={"CODEX_THREAD_ID": "th-1"})
    assert [c["key"] for c in job_card.session_cards(env.config, "claude", "s-1")] == ["mine"]
    assert [c["key"] for c in job_card.session_cards(env.config, "codex", "th-1")] == ["codex"]
    assert job_card.session_cards(env.config, "codex", "s-1") == []


def test_a_failed_job_its_agent_never_heard_of_stays_with_a_warning(env):
    jobs.new(env.config, "lost", label="Lost", env=S1)
    append(env, "lost", {"status": "failed", "message": "exited with code 1"})
    jobs.record_event(env.config, "lost", "wake_failed", {"error": "claude exited with 1"})
    [card] = job_card.session_cards(env.config, "claude", "s-1")
    assert card["status"] == "failed" and "couldn't reach" in card["attention"]
    jobs.record_event(env.config, "lost", "woke", {"agent": "claude", "via": "inbox"})
    assert job_card.session_cards(env.config, "claude", "s-1") == []  # it got through later


def test_a_failure_from_long_ago_is_not_shown(env):
    jobs.new(env.config, "old", label="Old", env=S1)
    old = datetime.now(UTC) - timedelta(days=3)
    with open(jobs.events_path(env.config, "old"), "a") as f:
        f.write(json.dumps({"status": "failed"}) + "\n")
    jobs.refresh(env.config, "old", now=old)
    jobs.record_event(env.config, "old", "wake_failed", {"error": "x"})
    assert job_card.session_cards(env.config, "claude", "s-1") == []


CONTEXT = {
    "run": {"status": "running", "kernel_epoch": 2, "current_cell_index": 4},
    "cells": [
        {"cell_id": "a", "cell_index": 0, "label": "# Train", "status": "skipped"},
        {"cell_id": "b", "cell_index": 1, "label": "Train", "status": "succeeded"},
        {"cell_id": "c", "cell_index": 2, "label": "Train", "status": "succeeded"},
        {"cell_id": "d", "cell_index": 3, "label": "# Release", "status": "skipped"},
        {"cell_id": "e", "cell_index": 4, "label": "Release", "status": "running"},
        {"cell_id": "f", "cell_index": 5, "label": "Release", "status": "pending"},
    ],
    "resources": [
        {"display_label": "news-scoring-test", "provider": "sagemaker",
         "resource_type": "processing_job", "status": "InProgress", "terminal": False},
        {"display_label": "news-image-build", "provider": "docker", "resource_type": "image",
         "status": "Completed", "terminal": True},
    ],
}  # fmt: skip


def test_a_notebook_card_shows_its_cell_its_count_and_what_is_still_running(env, monkeypatch):
    job_card.clear_cache()
    monkeypatch.setattr(job_sources, "_runwatch_json", lambda rw, command: CONTEXT)
    jobs.new(env.config, "nb", label="Release notebook", env=S1)
    with jobs.connect(env.config) as db:  # a run job that launched Runwatch
        job = jobs._load(db, "nb")
        job.kind = "run"
        job.spec = {"runwatch": {"binary": "/bin/runwatch", "run": "/runs/r1"}}
        jobs._save(db, job)
    card = job_card.card(env.config, jobs.get(env.config, "nb"))
    assert card["notebook"] == {
        "cell": {"index": 4, "label": "Release"},
        "cells": {"done": 2, "total": 4},
        "resources": [{"label": "news-scoring-test", "kind": "sagemaker processing_job",
                       "status": "InProgress"}],
    }  # fmt: skip


def test_a_notebook_it_cannot_read_leaves_the_rest_of_the_card(env, monkeypatch):
    job_card.clear_cache()

    def broken(rw, command):
        raise job_sources.CheckError("runwatch context: gone")

    monkeypatch.setattr(job_sources, "_runwatch_json", broken)
    jobs.new(env.config, "nb", label="Release notebook", env=S1)
    with jobs.connect(env.config) as db:
        job = jobs._load(db, "nb")
        job.kind, job.spec = "runwatch", {"binary": "/bin/runwatch", "run": "/runs/r1"}
        jobs._save(db, job)
    card = job_card.card(env.config, jobs.get(env.config, "nb"))
    assert card["notebook"] is None and card["label"] == "Release notebook"


def test_a_notebook_is_read_at_most_every_few_seconds(env, monkeypatch):
    job_card.clear_cache()
    calls = []
    monkeypatch.setattr(job_sources, "_runwatch_json",
                        lambda rw, command: calls.append(command) or CONTEXT)  # fmt: skip
    jobs.new(env.config, "nb", label="Release notebook", env=S1)
    with jobs.connect(env.config) as db:
        job = jobs._load(db, "nb")
        job.kind, job.spec = "runwatch", {"binary": "/bin/runwatch", "run": "/runs/r1"}
        jobs._save(db, job)
    job = jobs.get(env.config, "nb")
    job_card.card(env.config, job)
    job_card.card(env.config, job)
    assert len(calls) == 1

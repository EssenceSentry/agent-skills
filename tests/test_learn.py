import json

import pytest
from typer.testing import CliRunner

from ax import learn, profile
from ax.cli import app
from ax.store import Store


def session(db, key, *, project="demo", entrypoint="codex_vscode", kind="main", provider="codex"):
    db.execute(
        "INSERT INTO sessions (key, provider, session_id, kind, title, project, entrypoint, "
        "started, ended, note_path, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, provider, key, kind, f"Title {key}", project, entrypoint, "2026-10-01T10:00:00Z",
         "2026-10-01T11:00:00Z", f"Sessions/{key}.md", "2026-10-01T11:00:00Z"),
    )  # fmt: skip


def messages(db, key, *pairs):
    for seq, (role, text) in enumerate(pairs):
        db.execute(
            "INSERT INTO messages (session_key, seq, ts, role, text) VALUES (?, ?, ?, ?, ?)",
            (key, seq, f"2026-10-0{1 + seq % 9}T10:00:00Z", role, text),
        )


@pytest.fixture
def archive(env):
    with Store(env.config.db_path) as store:
        db = store.db
        session(db, "s1")
        messages(db, "s1", ("assistant", "I also tidied the typings folder."),
                 ("user", "Don't touch files unrelated to what I asked for."),
                 ("user", "Thanks, looks good."))  # fmt: skip
        session(db, "s2", project="other")
        messages(db, "s2", ("assistant", "Running uv sync now."),
                 ("user", "[Request interrupted by user]"),
                 ("user", "Use the bootstrap script, it keeps the editable install."))  # fmt: skip
        session(db, "worker", entrypoint="sdk-cli")
        messages(db, "worker", ("user", "Never commit anything; you are a delegated worker."))
        session(db, "sub", kind="subagent")
        messages(db, "sub", ("user", "Do not edit files."))
        session(db, "s3")
        messages(db, "s3", ("user", "PLEASE IMPLEMENT THIS PLAN: never do X"),
                 ("user", "# Files mentioned by the user:\n\n## a.txt: /x/a.txt\n\n"
                          "## My request for Codex:\nStop adding compatibility shims."),
                 ("user", "I don't know, maybe."))  # fmt: skip
        store.commit()
    memories = env.config.codex_home / "memories"
    memories.mkdir(parents=True, exist_ok=True)
    (memories / "raw_memories.md").write_text(
        "# Raw Memories\n\n## Thread `t-1`\nupdated_at: 2026-09-01T10:00:00+00:00\n"
        "cwd: /Users/me/Repos/auto-classifier\n\n### Task 1: Scope\n\nPreference signals:\n"
        '- the user said: "I don\'t care about breaking changes" -> drop backward '
        "compatibility shims\n\nReusable knowledge:\n- not a preference\n"
    )
    return env


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


class FakeModel:
    def __init__(self, label):
        self.label, self.prompts = label, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        ids = [line.split('"id": "', 1)[1].split('"', 1)[0] for line in prompt.splitlines()
               if line.startswith('{"id": "')]  # fmt: skip
        return json.dumps([{**self.label(i), "id": i} for i in ids])


def keep(topic, rule="Leave unrelated files alone.", kind="preference", scope="global"):
    return {"kind": kind, "lasting": True, "rule": rule, "topic": topic, "scope": scope}


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


def candidate(cid, session_key, project, text="t", ts="2026-10-10T10:00:00Z"):
    return {"id": cid, "session": session_key, "project": project, "provider": "codex",
            "ts": ts, "text": text, "note": f"Sessions/{session_key}.md", "source": "message",
            "signals": ["phrase"], "context": ""}  # fmt: skip


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

"""Archive rows and labelled candidates for the learner's tests."""


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


def keep(topic, rule="Leave unrelated files alone.", kind="preference", scope="global", **more):
    return {"kind": kind, "lasting": True, "rule": rule, "topic": topic, "scope": scope, **more}


def candidate(
    cid, session_key, project, text="t", ts="2026-10-10T10:00:00Z", signals=("phrase",), commands=()
):
    return {"id": cid, "session": session_key, "project": project, "provider": "codex",
            "ts": ts, "text": text, "note": f"Sessions/{session_key}.md", "source": "message",
            "signals": list(signals), "context": "", "commands": list(commands)}  # fmt: skip

"""Private durable chat state. Provider transcripts remain the source of history."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager


@contextmanager
def connect(config):
    path = config.data / "chat.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    os.chmod(path, 0o600)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS outbox (
            provider TEXT, sid TEXT, id TEXT, body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', error TEXT, created REAL NOT NULL,
            owner_pid INTEGER,
            PRIMARY KEY(provider, sid, id));
        CREATE TABLE IF NOT EXISTS session_meta (
            provider TEXT, sid TEXT, body TEXT NOT NULL,
            PRIMARY KEY(provider, sid));
        CREATE TABLE IF NOT EXISTS failures (
            provider TEXT, sid TEXT, error TEXT NOT NULL, at REAL NOT NULL,
            PRIMARY KEY(provider, sid));
        CREATE TABLE IF NOT EXISTS starts (
            provider TEXT, id TEXT, signature TEXT NOT NULL, sid TEXT, status TEXT NOT NULL,
            PRIMARY KEY(provider,id));
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(outbox)")}
    if "owner_pid" not in columns:
        try:
            db.execute("ALTER TABLE outbox ADD COLUMN owner_pid INTEGER")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
    try:
        yield db
        db.commit()
    finally:
        db.close()


def client_id(value):
    if value is not None and (not isinstance(value, str) or not value or len(value) > 200):
        raise ValueError("client_message_id must be a nonempty string of at most 200 characters")
    return value or str(uuid.uuid4())


def enqueue(config, provider, sid, body, message_id=None):
    key = client_id(message_id)
    with connect(config) as db:
        db.execute(
            "INSERT OR IGNORE INTO outbox(provider,sid,id,body,status,error,created) VALUES(?,?,?,?,'queued',NULL,?)",
            (provider, sid, key, json.dumps(body), time.time()),
        )
        row = db.execute(
            "SELECT * FROM outbox WHERE provider=? AND sid=? AND id=?", (provider, sid, key)
        ).fetchone()
        if json.loads(row["body"]) != body:
            raise ValueError("that message id already belongs to different content")
    return key


def messages(config, provider, sid, *, all_statuses=False):
    with connect(config) as db:
        rows = db.execute(
            "SELECT * FROM outbox WHERE provider=? AND sid=? ORDER BY created,rowid",
            (provider, sid),
        ).fetchall()
    return [
        {**dict(r), **json.loads(r["body"])}
        for r in rows
        if all_statuses or r["status"] not in ("sent", "cancelled")
    ]


def claim(config, provider, sid, key):
    with connect(config) as db:
        return (
            db.execute(
                "UPDATE outbox SET status='dispatching',error=NULL,owner_pid=? WHERE provider=? "
                "AND sid=? AND id=? AND status='queued'",
                (os.getpid(), provider, sid, key),
            ).rowcount
            == 1
        )


def settle(config, provider, sid, key, status, error=None):
    with connect(config) as db:
        db.execute(
            "UPDATE outbox SET status=?,error=? WHERE provider=? AND sid=? AND id=?",
            (status, error, provider, sid, key),
        )


def change(config, provider, sid, key, action, text=None):
    with connect(config) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM outbox WHERE provider=? AND sid=? AND id=?", (provider, sid, key)
        ).fetchone()
        if row is None or row["status"] in ("sent", "cancelled", "dispatching"):
            raise ValueError("that pending message can no longer be changed")
        body = json.loads(row["body"])
        if action == "edit":
            if not isinstance(text, str) or not text.strip():
                raise ValueError("say what the pending message should contain")
            body["text"] = text
        status = (
            "cancelled" if action == "cancel" else "queued" if action == "retry" else row["status"]
        )
        db.execute(
            "UPDATE outbox SET body=?,status=?,error=NULL WHERE provider=? AND sid=? AND id=?",
            (json.dumps(body), status, provider, sid, key),
        )


def metadata(config, provider, sid, changes=None):
    with connect(config) as db:
        if changes is not None:
            db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT body FROM session_meta WHERE provider=? AND sid=?", (provider, sid)
        ).fetchone()
        found = json.loads(row[0]) if row else {}
        if changes is not None:
            found.update(changes)
            db.execute(
                "INSERT OR REPLACE INTO session_meta VALUES(?,?,?)",
                (provider, sid, json.dumps(found)),
            )
    return found


def all_metadata(config):
    with connect(config) as db:
        return [
            {"provider": row[0], "id": row[1], **json.loads(row[2])}
            for row in db.execute("SELECT provider,sid,body FROM session_meta")
        ]


def recover(config):
    with connect(config) as db:
        rows = db.execute(
            "SELECT provider,sid,id,owner_pid FROM outbox WHERE status='dispatching'"
        ).fetchall()
        for provider, sid, key, pid in rows:
            if pid:
                try:
                    os.kill(pid, 0)
                    continue
                except ProcessLookupError:
                    pass
                except PermissionError:
                    continue
            db.execute(
                "UPDATE outbox SET status='uncertain',error='The sender ended before acknowledgement' WHERE provider=? AND sid=? AND id=?",
                (provider, sid, key),
            )


def failure(config, provider, sid, error=None, *, clear=False):
    with connect(config) as db:
        if clear:
            db.execute("DELETE FROM failures WHERE provider=? AND sid=?", (provider, sid))
        elif error:
            db.execute(
                "INSERT OR REPLACE INTO failures VALUES(?,?,?,?)",
                (provider, sid, str(error)[-12000:], time.time()),
            )
        row = db.execute(
            "SELECT error FROM failures WHERE provider=? AND sid=?", (provider, sid)
        ).fetchone()
    return row[0] if row else None


def receipts(config, provider, sid):
    with connect(config) as db:
        return [
            row[0]
            for row in db.execute(
                "SELECT id FROM outbox WHERE provider=? AND sid=? "
                "AND status='sent' ORDER BY created DESC LIMIT 50",
                (provider, sid),
            )
        ]


def begin_start(config, provider, key, signature):
    with connect(config) as db:
        db.execute(
            "INSERT OR IGNORE INTO starts VALUES(?,?,?,NULL,'queued')", (provider, key, signature)
        )
        row = db.execute(
            "SELECT * FROM starts WHERE provider=? AND id=?", (provider, key)
        ).fetchone()
        if row["signature"] != signature:
            raise ValueError("This start id belongs to a different draft")
        if row["sid"]:
            return row["sid"]
        claimed = db.execute(
            "UPDATE starts SET status='creating' WHERE provider=? AND id=? AND status IN ('queued','failed')",
            (provider, key),
        ).rowcount
        if not claimed:
            raise ValueError(
                "This chat is already starting. Retry this same draft to check its result."
            )
    return None


def finish_start(config, provider, key, sid, body):
    with connect(config) as db:
        db.execute(
            "INSERT OR IGNORE INTO outbox(provider,sid,id,body,status,error,created) VALUES(?,?,?,?,'queued',NULL,?)",
            (provider, sid, key, json.dumps(body), time.time()),
        )
        db.execute(
            "UPDATE starts SET sid=?,status='ready' WHERE provider=? AND id=?", (sid, provider, key)
        )


def fail_start(config, provider, key):
    with connect(config) as db:
        db.execute(
            "UPDATE starts SET status='failed' WHERE provider=? AND id=? AND sid IS NULL",
            (provider, key),
        )

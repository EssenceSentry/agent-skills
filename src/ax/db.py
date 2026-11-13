"""Private durable state, numeric progress events and a separate search catalog."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, purpose TEXT NOT NULL, owner TEXT NOT NULL, cwd TEXT NOT NULL,
 kind TEXT NOT NULL, command TEXT, pid INTEGER, identity TEXT, status TEXT NOT NULL,
 started REAL NOT NULL, updated REAL NOT NULL, every INTEGER NOT NULL CHECK(every BETWEEN 10 AND 60),
 next_review REAL NOT NULL, reviewing INTEGER NOT NULL DEFAULT 0,
 done REAL, total REAL, unit TEXT, stage TEXT, exit_code INTEGER,
 environment TEXT, tty INTEGER NOT NULL DEFAULT 0, inbox TEXT, inbox_token TEXT
);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, type TEXT NOT NULL,
 at REAL NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_task ON events(task,seq);
CREATE TABLE IF NOT EXISTS escalations (
 id TEXT PRIMARY KEY, task TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS memories (
 origin TEXT PRIMARY KEY, provider TEXT NOT NULL, digest TEXT NOT NULL,
 target TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS samples (
 provider TEXT, name TEXT, observed REAL, used REAL, resets REAL,
 PRIMARY KEY(provider,name,observed)
);
"""


@contextmanager
def connect(config):
    config.prepare()
    db = sqlite3.connect(config.database, timeout=30, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(config):
    with connect(config) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
    os.chmod(config.database, 0o600)


def event(db, task, kind, data):
    from ax.redact import redact

    payload = redact(json.dumps(data, allow_nan=False, ensure_ascii=False))
    cursor = db.execute(
        "INSERT INTO events(task,type,at,data) VALUES(?,?,?,?)", (task, kind, time.time(), payload)
    )
    return cursor.lastrowid


def public_task(row):
    value = dict(row)
    for field in ("inbox", "inbox_token", "identity", "reviewing", "environment"):
        value.pop(field, None)
    value["command"] = json.loads(value["command"]) if value.get("command") else None
    from ax.redact import redact

    return json.loads(redact(json.dumps(value)))


def events(config, after=0, task=None):
    with connect(config) as db:
        sql = "SELECT * FROM events WHERE seq>?"
        args = [after]
        if task:
            sql += " AND task=?"
            args.append(task)
        rows = db.execute(sql + " ORDER BY seq LIMIT 500", args).fetchall()
    return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

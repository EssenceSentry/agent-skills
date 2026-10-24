"""The SQLite store behind every ax view: sessions, searchable messages, sync state."""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ax.model import Session
from ax.redact import redact

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    session_key TEXT,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    parent_key TEXT,
    title TEXT,
    project TEXT,
    cwd TEXT,
    branch TEXT,
    model TEXT,
    effort TEXT,
    entrypoint TEXT,
    version TEXT,
    started TEXT,
    ended TEXT,
    user_turns INTEGER,
    tool_calls INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    source_path TEXT,
    raw_path TEXT,
    note_path TEXT,
    excluded INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_parent ON sessions(parent_key);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    session_key TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT,
    role TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_key);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text, content='messages', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS unknown_records (
    session_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    version TEXT,
    record_type TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (session_key, record_type)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS usage_snapshots (
    provider TEXT NOT NULL,
    window TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    used REAL NOT NULL,
    resets_at TEXT,
    window_minutes INTEGER,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (provider, window, observed_at)
);
"""


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *exc):
        # Never commit half a sync: a crash leaves the store as it was before the run.
        if exc_type is None:
            self.db.commit()
        else:
            self.db.rollback()
        self.db.close()

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    def commit(self) -> None:
        self.db.commit()

    @contextmanager
    def savepoint(self):
        """Apply every write in the block, or none of them."""
        self.db.execute("SAVEPOINT unit")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK TO unit")
            self.db.execute("RELEASE unit")
            raise
        self.db.execute("RELEASE unit")

    def note_owner(self, note_path: str) -> str | None:
        row = self.db.execute(
            "SELECT key FROM sessions WHERE note_path = ?", (note_path,)
        ).fetchone()
        return row["key"] if row else None

    def set_note_path(self, key: str, note_path: str | None) -> None:
        self.db.execute("UPDATE sessions SET note_path = ? WHERE key = ?", (note_path, key))

    def all_sessions(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT key, provider, session_id, title, source_path, raw_path, note_path FROM sessions"
        ).fetchall()
        return [dict(r) for r in rows]

    def file_state(self, path: Path) -> tuple[int, int] | None:
        row = self.db.execute(
            "SELECT size, mtime_ns FROM files WHERE path = ?", (str(path),)
        ).fetchone()
        return (row["size"], row["mtime_ns"]) if row else None

    def record_file(self, path: Path, provider: str, size: int, mtime_ns: int, key: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?)",
            (str(path), provider, size, mtime_ns, key, _now()),
        )

    def session(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM sessions WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def children(self, key: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM sessions WHERE parent_key = ? ORDER BY started", (key,)
        ).fetchall()
        return [dict(r) for r in rows]

    def titles(self, provider: str) -> dict[str, str]:
        rows = self.db.execute(
            "SELECT session_id, title FROM sessions WHERE provider = ?", (provider,)
        ).fetchall()
        return {r["session_id"]: r["title"] for r in rows}

    def save_session(
        self,
        session: Session,
        *,
        note_path: str | None,
        raw_path: str | None,
        excluded: bool,
        index_messages: bool,
    ) -> None:
        """Replace a session's row, its searchable messages and its unknown-record tally."""
        s = session
        self.db.execute(
            "INSERT OR REPLACE INTO sessions VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                s.key, s.provider, s.session_id, s.kind, s.parent_key, redact(s.title or ""),
                s.project, s.cwd, s.branch, s.model, s.effort, s.entrypoint, s.version,
                _iso(s.started), _iso(s.ended), s.user_turns, s.tool_calls, s.tokens_in,
                s.tokens_out, s.cost_usd, str(s.source_path) if s.source_path else None,
                raw_path, note_path, int(excluded), _now(),
            ),
        )  # fmt: skip
        self.db.execute("DELETE FROM messages WHERE session_key = ?", (s.key,))
        if index_messages:
            self.db.executemany(
                "INSERT INTO messages (session_key, seq, ts, role, text) VALUES (?, ?, ?, ?, ?)",
                [
                    (s.key, i, _iso(e.ts), e.kind, redact(e.text))
                    for i, e in enumerate(s.events)
                    if e.text
                ],
            )
        self.db.execute("DELETE FROM unknown_records WHERE session_key = ?", (s.key,))
        self.db.executemany(
            "INSERT INTO unknown_records VALUES (?, ?, ?, ?, ?)",
            [(s.key, s.provider, s.version, kind, n) for kind, n in s.unknown.items()],
        )

    def search(
        self,
        query: str,
        limit: int = 20,
        *,
        provider: str | None = None,
        project: str | None = None,
        role: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        """Full-text search over redacted message text: the best-matching sessions first.

        Every word must match; each is quoted so FTS5 syntax in a query is literal text.
        """
        terms = " ".join('"' + t.replace('"', '""') + '"' for t in query.split())
        if not terms:
            return []
        where, params = ["messages_fts MATCH ?"], [terms]
        for column, value in (("s.provider", provider), ("s.project", project), ("m.role", role)):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        if since:
            where.append("s.ended >= ?")
            params.append(since)
        # Each session's best message only, so one long session can't fill every slot.
        # snippet() is not allowed beside a window function, so it is fetched afterwards.
        best = self.db.execute(
            f"""
            SELECT id, session_key, role, ts, provider, project, title, started, note_path
            FROM (
                SELECT m.id, m.session_key, m.role, m.ts, s.provider, s.project, s.title,
                       s.started, s.note_path, messages_fts.rank AS score,
                       ROW_NUMBER() OVER (
                           PARTITION BY m.session_key ORDER BY messages_fts.rank
                       ) AS nth
                FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid
                JOIN sessions s ON s.key = m.session_key
                WHERE {" AND ".join(where)}
            )
            WHERE nth = 1 ORDER BY score LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        if not best:
            return []
        ids = [row["id"] for row in best]
        snippets = dict(
            self.db.execute(
                f"""
                SELECT rowid, snippet(messages_fts, 0, '[', ']', '…', 12)
                FROM messages_fts WHERE messages_fts MATCH ?
                AND rowid IN ({",".join("?" * len(ids))})
                """,
                (terms, *ids),
            ).fetchall()
        )
        hits = []
        for row in best:
            hit = dict(row)
            hit["snippet"] = snippets.get(hit.pop("id"), "")
            hits.append(hit)
        return hits

    def unknown_totals(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT provider, record_type, SUM(count) AS count, MAX(version) AS version "
            "FROM unknown_records GROUP BY provider, record_type ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT provider, kind, COUNT(*) AS n, SUM(note_path IS NOT NULL) AS rendered "
            "FROM sessions GROUP BY provider, kind ORDER BY provider, kind"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_usage(self, provider, window, observed_at, used, resets_at, window_minutes) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO usage_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
            (provider, window, observed_at, used, resets_at, window_minutes, _now()),
        )

    def usage_history(self, provider: str, window: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT observed_at, used, resets_at FROM usage_snapshots "
            "WHERE provider = ? AND window = ? ORDER BY observed_at",
            (provider, window),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

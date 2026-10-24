"""Full-text search over archived sessions, one hit per session."""

import re
from datetime import UTC, datetime, timedelta

from ax.config import Config
from ax.store import Store

_PERIOD = re.compile(r"^(\d+)([hdw])$")
_UNITS = {"h": "hours", "d": "days", "w": "weeks"}


def parse_since(text: str, now: datetime | None = None) -> datetime:
    """A start time: `2026-10-01` (local midnight) or a period back from now (`12h`, `7d`, `2w`)."""
    text = text.strip()
    period = _PERIOD.match(text)
    if period:
        now = now or datetime.now(UTC)
        return now - timedelta(**{_UNITS[period.group(2)]: int(period.group(1))})
    try:
        day = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"expected YYYY-MM-DD or a period like 7d, got {text!r}") from None
    return day.astimezone()


def search(
    config: Config,
    query: str,
    *,
    provider: str | None = None,
    project: str | None = None,
    role: str | None = None,
    since: datetime | None = None,
    limit: int = 10,
) -> list[dict]:
    """The best-matching sessions, each with its best snippet and the note's full path."""
    if not config.db_path.exists():
        return []
    with Store(config.db_path) as store:
        rows = store.search(
            query,
            limit=limit * 20,
            provider=provider,
            project=project,
            role=role,
            since=since.astimezone(UTC).isoformat() if since else None,
        )
    hits: dict[str, dict] = {}
    for row in rows:
        if row["session_key"] in hits:
            continue
        note = str(config.vault / row["note_path"]) if row["note_path"] else None
        hits[row["session_key"]] = {**row, "note": note}
        if len(hits) == limit:
            break
    return list(hits.values())

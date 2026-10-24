import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from ax.cli import app
from ax.search import parse_since, search
from ax.sync import sync
from conftest import CLAUDE_SESSION, CODEX_SESSION

runner = CliRunner()


def keys(hits):
    return [hit["session_key"] for hit in hits]


def test_hits_are_grouped_one_per_session_with_the_note_path(env):
    sync(env.config)
    hits = search(env.config, "retry")
    assert len(keys(hits)) == len(set(keys(hits)))
    claude_hit = next(h for h in hits if h["session_key"] == f"claude:{CLAUDE_SESSION}")
    assert claude_hit["title"] == "Retry for fetch helper"
    assert claude_hit["note"] == str(
        env.vault / "Sessions/2026/10/2026-10-20 claude demo - Retry for fetch helper (11111111).md"
    )
    assert "retry" in claude_hit["snippet"].lower()


def test_filters_narrow_by_provider_project_role_and_date(env):
    sync(env.config)
    assert all(k.startswith("codex:") for k in keys(search(env.config, "retry", provider="codex")))
    assert search(env.config, "retry", project="elsewhere") == []
    user_only = search(env.config, "fetch helper", role="user")
    assert keys(user_only) == [f"claude:{CLAUDE_SESSION}"]
    assert search(env.config, "retry", since=datetime(2026, 11, 1, tzinfo=UTC)) == []


def test_guardian_reviews_and_secrets_are_not_searchable(env):
    sync(env.config)
    assert search(env.config, "Approved") == []
    assert search(env.config, "AKIAABCDEFGHIJKLMNOP") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-01", datetime(2026, 10, 1).astimezone()),
        ("7d", datetime(2026, 10, 17, 12, tzinfo=UTC)),
        ("2w", datetime(2026, 10, 10, 12, tzinfo=UTC)),
    ],
)
def test_since_accepts_dates_and_relative_periods(text, expected):
    now = datetime(2026, 10, 24, 12, tzinfo=UTC)
    assert parse_since(text, now=now) == expected


def test_since_rejects_nonsense():
    with pytest.raises(ValueError):
        parse_since("last tuesday")


def test_search_command_prints_json_for_agents(env):
    runner.invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    result = runner.invoke(
        app, ["search", "retry", "--json"], env={"AX_CONFIG": str(env.config_path)}
    )
    assert result.exit_code == 0, result.output
    hits = json.loads(result.output)
    assert {f"claude:{CLAUDE_SESSION}", f"codex:{CODEX_SESSION}"} <= set(keys(hits))


def test_search_command_prints_readable_lines(env):
    runner.invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    result = runner.invoke(
        app, ["search", "retry", "--provider", "claude"], env={"AX_CONFIG": str(env.config_path)}
    )
    assert result.exit_code == 0, result.output
    assert "Retry for fetch helper" in result.output
    assert "claude · demo" in result.output


def test_search_command_says_when_nothing_matches(env):
    runner.invoke(app, ["sync"], env={"AX_CONFIG": str(env.config_path)})
    result = runner.invoke(app, ["search", "zebra"], env={"AX_CONFIG": str(env.config_path)})
    assert result.exit_code == 1
    assert "no matches" in result.output

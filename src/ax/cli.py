"""The ax command line."""

import json

import typer

from ax import sync as sync_module
from ax.config import load
from ax.store import Store

app = typer.Typer(no_args_is_help=True, add_completion=False)

# Below this many days Claude Code deletes transcripts before most archives notice.
MIN_RETENTION_DAYS = 365


@app.command()
def sync(quiet: bool = typer.Option(False, "--quiet", "-q", help="Print nothing unless it fails.")):
    """Archive new and changed sessions into the vault."""
    try:
        report = sync_module.sync(load())
    except sync_module.SyncBusy as busy:
        # Hooks fire from many sessions at once; the running sync will pick their files up.
        typer.echo(f"{busy}; skipping")
        raise typer.Exit(0) from None
    if not quiet or report.errors:
        typer.echo(
            f"discovered {report.discovered} · parsed {report.parsed} · wrote {report.written}"
            f" · renamed {report.renamed} · removed {report.removed}"
            f" · excluded {report.excluded} · not rendered {report.not_rendered}"
        )
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
    raise typer.Exit(1 if report.errors else 0)


@app.command()
def doctor():
    """Check retention, the vault, the last sync and transcript-format drift."""
    config = load()
    failed = False

    def line(ok: bool | None, text: str):
        mark = {True: "✓", False: "✗", None: "!"}[ok]
        typer.echo(f"{mark} {text}")

    days = _claude_retention(config.claude_home / "settings.json")
    if days is None:
        line(False, "Claude Code cleanupPeriodDays is unset: transcripts are deleted after 30 days")
        failed = True
    elif days < MIN_RETENTION_DAYS:
        line(
            False,
            f"Claude Code cleanupPeriodDays {days}: transcripts are deleted after {days} days",
        )
        failed = True
    else:
        line(True, f"Claude Code cleanupPeriodDays {days}")

    if not config.vault.is_dir():
        line(False, f"vault {config.vault} does not exist")
        failed = True
    elif not (config.vault / ".git").exists():
        line(False, f"vault {config.vault} is not a Git repository")
        failed = True
    else:
        line(True, f"vault {config.vault}")

    if not config.db_path.exists():
        line(None, "no sync yet: run `ax sync`")
        raise typer.Exit(1 if failed else 0)
    with Store(config.db_path) as store:
        last = store.get_meta("last_sync")
        errors = int(store.get_meta("last_sync_errors") or 0)
        line(errors == 0, f"last sync {last} with {errors} errors")
        failed |= errors > 0
        for row in store.counts():
            line(
                True,
                f"{row['provider']} {row['kind']}: {row['n']} sessions, {row['rendered']} notes",
            )
        unknown = store.unknown_totals()
        if unknown:
            line(None, "record types ax doesn't recognise (check for a transcript-format change):")
            for row in unknown:
                version = f" (v{row['version']})" if row["version"] else ""
                typer.echo(f"    {row['provider']} {row['record_type']} ×{row['count']}{version}")
    raise typer.Exit(1 if failed else 0)


def _claude_retention(settings) -> int | None:
    try:
        value = json.loads(settings.read_text()).get("cleanupPeriodDays")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, int) else None

"""The ax command line."""

import json

import typer

from ax import search as search_module
from ax import sync as sync_module
from ax import vault as vault_module
from ax.config import load
from ax.store import Store

app = typer.Typer(no_args_is_help=True, add_completion=False)
vault_app = typer.Typer(no_args_is_help=True, help="Commit and push the vault safely.")
app.add_typer(vault_app, name="vault")


@vault_app.command("init")
def vault_init():
    """Add the starter Obsidian views and Home note where they are missing."""
    for path in vault_module.init(load().vault):
        typer.echo(f"created {path}")


@vault_app.command("commit")
def vault_commit():
    """Commit every vault change, unless gitleaks finds a secret in it."""
    try:
        result = vault_module.commit(load())
    except vault_module.ScanFailed as exc:
        typer.echo(f"secret scan failed, nothing committed: {exc}")
        raise typer.Exit(1) from None
    if result.findings:
        typer.echo(f"gitleaks found {len(result.findings)} possible secrets; nothing committed:")
        for f in result.findings:
            typer.echo(f"    {f.rule}  {f.file}:{f.line}  {f.fingerprint}")
        typer.echo(
            "Teach ax to redact the shape (then `ax sync`), or, for a false positive,"
            " add its fingerprint to the vault's .gitleaksignore."
        )
        raise typer.Exit(1)
    typer.echo(f"committed {result.notes} notes" if result.committed else "nothing to commit")


@vault_app.command("push")
def vault_push():
    """Push the vault, only to a GitHub repository confirmed to be private."""
    try:
        vault_module.push(load())
    except vault_module.UnsafeRemote as exc:
        typer.echo(f"not pushed: {exc}")
        raise typer.Exit(1) from None
    typer.echo("pushed")


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
def search(
    query: str = typer.Argument(..., help="Words that must all appear in a message."),
    provider: str = typer.Option(None, help="claude or codex."),
    project: str = typer.Option(None, help="Project (git repository) name."),
    role: str = typer.Option(None, help="user, assistant, tool, notice or message."),
    since: str = typer.Option(None, help="YYYY-MM-DD or a period such as 7d or 2w."),
    limit: int = typer.Option(10, help="Most sessions to return."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output for agents."),
):
    """Find past sessions by what was said in them."""
    try:
        start = search_module.parse_since(since) if since else None
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--since") from None
    hits = search_module.search(
        load(), query, provider=provider, project=project, role=role, since=start, limit=limit
    )
    if as_json:
        typer.echo(json.dumps(hits, indent=2, ensure_ascii=False))
    elif not hits:
        typer.echo("no matches")
    for hit in [] if as_json else hits:
        day = (hit["started"] or "")[:10]
        typer.echo(f"{day} · {hit['provider']} · {hit['project']} · {hit['title']}")
        typer.echo(f"    {hit['snippet']}")
        if hit["note"]:
            typer.echo(f"    {hit['note']}")
    raise typer.Exit(0 if hits else 1)


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

"""The ax command line."""

import difflib
import json
import os
import subprocess
from datetime import UTC, datetime

import typer

from ax import glue
from ax import search as search_module
from ax import sync as sync_module
from ax import usage as usage_module
from ax import vault as vault_module
from ax.config import load
from ax.store import Store

app = typer.Typer(no_args_is_help=True, add_completion=False)
vault_app = typer.Typer(no_args_is_help=True, help="Commit and push the vault safely.")
app.add_typer(vault_app, name="vault")
usage_app = typer.Typer(invoke_without_command=True, help="Remaining allowance and forecasts.")
app.add_typer(usage_app, name="usage")

_CACHED = typer.Option(False, "--cached", help="Use the last readings; don't ask Claude /usage.")


def _windows(config, cached: bool):
    windows = usage_module.claude_windows(config, refresh=not cached)
    windows += usage_module.codex_windows(config.codex_home)
    usage_module.record(config, windows)
    return windows


@usage_app.callback()
def usage_show(
    ctx: typer.Context,
    cached: bool = _CACHED,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Show used and remaining allowance per tool and window, with a forecast to reset."""
    if ctx.invoked_subcommand:
        return
    config = usage_module.load_config()
    now = datetime.now(UTC)
    rows = []
    for w in _windows(config, cached):
        history = usage_module.history(config, w.provider, w.name)
        rows.append((w, usage_module.forecast(w, history, now)))
    if as_json:
        typer.echo(json.dumps([_usage_json(w, f) for w, f in rows], indent=2, default=str))
        return
    for w, f in rows:
        typer.echo(_usage_line(w, f, now))


@usage_app.command("guard")
def usage_guard(
    provider: str = typer.Option(..., help="claude or codex."),
    window: str = typer.Option("weekly", help="session, weekly or weekly_fable."),
    min_remaining: float = typer.Option(None, help="Percent that must be left; default: reserve."),
    cached: bool = _CACHED,
):
    """Exit 0 when enough allowance is left, 1 when not, 69 when it can't be known."""
    config = usage_module.load_config()
    if min_remaining is None:
        min_remaining = usage_module.reserve_for(config, provider, window)
    code = usage_module.guard(_windows(config, cached), provider, window, min_remaining)
    verdict = {0: "safe", 1: "below threshold", 69: "unknown"}[code]
    typer.echo(f"{provider} {window}: {verdict} (needs {min_remaining:g}% left)")
    raise typer.Exit(code)


def _usage_line(w, f, now) -> str:
    head = f"{w.provider:<6} {w.name:<12}"
    if w.used is None:
        return f"{head} unknown ({w.status})"
    line = f"{head} {w.used:.0f}% used · {100 - w.used:.0f}% left"
    if w.resets_at:
        left = w.resets_at - now
        hours = int(left.total_seconds() // 3600)
        line += f" · resets {w.resets_at.astimezone():%a %H:%M} (in {hours // 24}d {hours % 24}h)"
    if f:
        if f.lasts:
            low, high = round(f.projected_low), round(f.projected_high)
            pace = f"{low}%" if low == high else f"{low}–{high}%"
            line += f" · on pace for {pace} at reset"
        elif f.runs_out_at:
            line += f" · may run out {f.runs_out_at.astimezone():%a %H:%M}"
    if w.status != "fresh":
        line += f" [{w.status}]"
    return line


def _usage_json(w, f) -> dict:
    out = {**w.__dict__, "remaining": None if w.used is None else 100 - w.used}
    out["forecast"] = f.__dict__ if f else None
    return out


hooks_app = typer.Typer(no_args_is_help=True, help="Claude Code and Codex hooks that sync.")
schedule_app = typer.Typer(no_args_is_help=True, help="A launchd job that syncs every 30 min.")
skills_app = typer.Typer(no_args_is_help=True, help="Link this repository's skills.")
app.add_typer(hooks_app, name="hooks")
app.add_typer(schedule_app, name="schedule")
app.add_typer(skills_app, name="skills")
_APPLY = typer.Option(False, "--apply", help="Make the changes; without it, only print them.")


def _report(changes, apply: bool):
    for change in changes:
        if change.before == change.after:
            typer.echo(f"unchanged {change.path}")
        elif not apply:
            # Only the changed lines: settings files can hold secrets in other keys.
            typer.echo(f"would write {change.path}:")
            diff = difflib.unified_diff(
                (change.before or "").splitlines(), change.after.splitlines(), lineterm="", n=1
            )
            for line in list(diff)[2:]:
                typer.echo(f"    {line}")
    if apply:
        for path in glue.apply(changes):
            typer.echo(f"wrote {path} (previous version backed up beside it)")


@hooks_app.command("install")
def hooks_install(apply: bool = _APPLY):
    """Run a background `ax sync` when a session ends or a turn stops, in both tools."""
    _report(glue.plan_hooks(load(), ax=glue.ax_path()), apply)
    if apply:
        typer.echo("In Codex, run /hooks once to review and trust the new hooks.")


@schedule_app.command("install")
def schedule_install(
    apply: bool = _APPLY,
    with_vault: bool = typer.Option(False, help="Also commit and push the vault each run."),
):
    """Sync and record usage every 30 minutes with launchd, even with no session open."""
    changes = glue.plan_schedule(
        load(), ax=glue.ax_path(), launch_agents=glue.launch_agents_dir(), with_vault=with_vault
    )
    _report(changes, apply)
    if apply:
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(changes[0].path)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(changes[0].path)], check=True)
        typer.echo(f"loaded {glue.LABEL}")


@skills_app.command("link")
def skills_link(
    names: list[str] = typer.Argument(..., help="Skill folder names under skills/."),
    apply: bool = _APPLY,
):
    """Symlink skills into ~/.claude/skills and ~/.agents/skills where none is installed."""
    actions = glue.plan_skill_links(
        load(), names=names, repo_skills=glue.repo_skills(), agents_skills=glue.agents_skills_dir()
    )
    for a in actions:
        if a.kind == "conflict":
            typer.echo(f"skip {a.name} for {a.tool}: {a.reason}")
        elif a.kind == "linked":
            typer.echo(f"already linked {a.target}")
        elif not apply:
            typer.echo(f"would link {a.target} -> {a.source}")
    if apply:
        for target in glue.apply_links(actions):
            typer.echo(f"linked {target}")


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

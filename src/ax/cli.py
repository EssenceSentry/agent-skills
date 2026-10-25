"""The ax command line."""

import contextlib
import difflib
import io
import json
import os
import select
import shlex
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime

import typer

from ax import exp as exp_module
from ax import glue, job_eta, job_follow, job_service, job_wake
from ax import jobs as jobs_module
from ax import profile as profile_module
from ax import runs as runs_module
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
runs_app = typer.Typer(invoke_without_command=True, help="Delegated and background runs.")
app.add_typer(runs_app, name="runs")
_SINCE = typer.Option(1.0, help="Days back to include finished runs.")
_ALL = typer.Option(False, "--all", help="Include finished runs of any age.")


def _collect(since: float, all_: bool):
    config = runs_module.load_config()
    return runs_module.collect(config, since_days=36500 if all_ else since)


def _ago(when) -> str:
    if not when:
        return "?"
    seconds = int((datetime.now(UTC) - when).total_seconds())
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return "now"


def _runs_table(found) -> str:
    lines = [f"{'id':<9} {'source':<17} {'state':<12} {'project':<16} {'updated':<9} title"]
    for r in found:
        lines.append(
            f"{r.id:<9} {r.source:<17} {r.state:<12} {r.project[:16]:<16} {_ago(r.updated):<9} "
            f"{r.title[:60]}"
        )
    return "\n".join(lines)


@runs_app.callback()
def runs_list(
    ctx: typer.Context,
    since: float = _SINCE,
    all_: bool = _ALL,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """List running runs and recently finished ones, newest first."""
    if ctx.invoked_subcommand:
        return
    found = _collect(since, all_)
    if as_json:
        rows = [{**r.__dict__, "active": r.active} for r in found]
        typer.echo(json.dumps(rows, indent=2, default=str))
    else:
        typer.echo(_runs_table(found) if found else "no runs")


@runs_app.command("watch")
def runs_watch(interval: float = typer.Option(3.0, help="Seconds between refreshes.")):
    """Refresh the list of active and recent runs until Ctrl-C."""
    try:
        while True:
            found = _collect(1.0, False)
            typer.clear()
            typer.echo(f"ax runs · {datetime.now():%H:%M:%S} · Ctrl-C to stop\n")
            typer.echo(_runs_table(found) if found else "no runs")
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


@runs_app.command("show")
def runs_show(run_id: str = typer.Argument(..., help="An id, or its start, from `ax runs`.")):
    """Details of one run: where it lives, its note and the start of its brief."""
    run = runs_module.find(_collect(1.0, True), run_id)
    if not run:
        typer.echo(f"no single run matches {run_id}")
        raise typer.Exit(1)
    for key, value in run.__dict__.items():
        if value is not None:
            typer.echo(f"{key:<11} {value}")
    brief = run.path / "brief.md" if run.path and run.path.is_dir() else None
    if brief and brief.exists():
        typer.echo("\nbrief:")
        for line in brief.read_text(errors="replace").splitlines()[:15]:
            typer.echo(f"    {line}")


@runs_app.command("stop")
def runs_stop(run_id: str = typer.Argument(..., help="An id, or its start, from `ax runs`.")):
    """Ask a running delegation helper to stop; its own runner ends its processes."""
    run = runs_module.find(_collect(1.0, True), run_id)
    if not run:
        typer.echo(f"no single run matches {run_id}")
        raise typer.Exit(1)
    try:
        runs_module.stop(run)
    except runs_module.CannotStop as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from None
    typer.echo(f"asked {run.id} to stop")


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
    try:
        code = usage_module.guard(_windows(config, cached), provider, window, min_remaining)
    except Exception as exc:  # a failure must read as unknown, never as below threshold
        typer.echo(f"{provider} {window}: unknown ({type(exc).__name__}: {exc})")
        raise typer.Exit(usage_module.UNKNOWN) from None
    verdict = {0: "safe", 1: "below threshold", 69: "unknown"}[code]
    typer.echo(f"{provider} {window}: {verdict} (needs {min_remaining:g}% left)")
    raise typer.Exit(code)


def _usage_line(w, f, now) -> str:
    head = f"{w.provider:<6} {w.name:<12}"
    if w.used is None:
        return f"{head} unknown ({w.status})"
    line = f"{head} {w.used:.0f}% used · {100 - w.used:.0f}% left"
    if w.resets_at and w.resets_at <= now:
        line += " · reset passed"
    elif w.resets_at:
        left = w.resets_at - now
        hours = int(left.total_seconds() // 3600)
        line += f" · resets {w.resets_at.astimezone():%a %H:%M} (in {hours // 24}d {hours % 24}h)"
    if f:
        if f.lasts:
            low, high = round(f.projected_low), round(f.projected_high)
            pace = f"{low}%" if low == high else f"{low}–{high}%"
            line += f" · on pace for {pace} at reset"
        elif f.runs_out_at and f.runs_out_at <= now:
            line += " · may already have run out"
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
            before, after = _visible(change)
            diff = difflib.unified_diff(before, after, lineterm="", n=1)
            for line in list(diff)[2:]:
                typer.echo(f"    {line}")
    if apply:
        existed = {c.path for c in changes if c.before is not None}
        for path in glue.apply(changes):
            note = "previous version backed up beside it" if path in existed else "created"
            typer.echo(f"wrote {path} ({note})")


def _visible(change) -> tuple[list[str], list[str]]:
    """The lines to show: for a JSON settings file, only its `hooks` key."""
    if change.path.suffix != ".json":
        return (change.before or "").splitlines(), change.after.splitlines()

    def hooks(text):
        value = json.loads(text).get("hooks", {}) if text else {}
        return json.dumps({"hooks": value}, indent=2).splitlines()

    return hooks(change.before), hooks(change.after)


@hooks_app.command("install")
def hooks_install(
    apply: bool = _APPLY,
    guard: bool = typer.Option(
        True, "--guard/--no-guard", help="Also run ax-guard before every shell command."
    ),
):
    """Run a background `ax sync` when a session ends or a turn stops, in both tools.

    With --guard (the default), also block shell commands your profile rules forbid.
    """
    config = load()
    changes = glue.plan_hooks(config, ax=glue.ax_path(), guard=glue.guard_path() if guard else None)
    _report(changes, apply)
    if apply:
        typer.echo("In Codex, run /hooks once to review and trust the new hooks.")
        if guard and not (config.data / "guard_rules.json").exists():
            typer.echo("No guard rules yet: run `ax profile compile --apply`.")


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


exp_app = typer.Typer(no_args_is_help=True, help="Research campaigns with a value gate.")
app.add_typer(exp_app, name="exp")


def _campaign(slug: str):
    folder = exp_module.find_campaign(load().vault, slug)
    if not folder:
        typer.echo(f"no single campaign named {slug} under Projects/*/Research/")
        raise typer.Exit(1)
    return folder


@exp_app.command("init")
def exp_init(
    project: str = typer.Argument(..., help="Project folder under the vault's Projects/."),
    campaign: str = typer.Argument(..., help="Short name for the campaign, e.g. pricing-study."),
    objective: str = typer.Option(..., help="What the campaign is for, in a sentence."),
    decision: list[str] = typer.Option([], help="A decision the research serves (repeatable)."),
    budget_hours: float = typer.Option(..., help="Hours the campaign may spend."),
):
    """Start a campaign: its folder and Campaign.md in the vault."""
    folder = exp_module.init(load().vault, project, campaign, objective, decision, budget_hours)
    typer.echo(f"created {folder / 'Campaign.md'}")


@exp_app.command("propose")
def exp_propose(
    campaign: str = typer.Argument(...),
    question: str = typer.Option(None, help="What the experiment asks."),
    decision: str = typer.Option(None, help="The decision or claim it informs."),
    outcome: list[str] = typer.Option([], help="'result → action' (repeat, at least two)."),
    cheaper: str = typer.Option(None, help="Cheaper evidence considered, and why it isn't enough."),
    stop: str = typer.Option(None, help="The result, failure or cost that ends it."),
    hours: float = typer.Option(None, help="Estimated cost in hours."),
    value: int = typer.Option(None, help="How much the decision matters, 1-5."),
    p_change: float = typer.Option(None, help="Chance the result changes the decision, 0-1."),
):
    """Propose an experiment; it is recorded only if it passes the value gate."""
    try:
        e = exp_module.propose(
            _campaign(campaign),
            question=question,
            decision=decision,
            outcomes=outcome,
            cheaper=cheaper,
            stop=stop,
            est_hours=hours,
            value=value,
            p_change=p_change,
        )
    except exp_module.GateFailed as failed:
        typer.echo("not recorded; the gate needs you to:")
        for problem in failed.problems:
            typer.echo(f"  - {problem}")
        raise typer.Exit(1) from None
    typer.echo(f"proposed {e.id} (score {e.score:g}): {e.path}")


@exp_app.command("list")
def exp_list(
    campaign: str = typer.Argument(...),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Open proposals ranked by value per hour, with budget and stall warnings."""
    folder = _campaign(campaign)
    found = exp_module.experiments(folder)
    summary = exp_module.summary(folder)
    if as_json:
        rows = [{**e.__dict__, "path": str(e.path)} for e in found]
        typer.echo(json.dumps({"summary": summary, "experiments": rows}, indent=2))
        return
    typer.echo(
        f"spent {summary['spent_hours']:g} of {summary['budget_hours']:g} h · "
        f"{summary['proposed']} proposed · {summary['running']} running · {summary['done']} done"
    )
    if summary["stalled"]:
        typer.echo("! the last three results changed no decision: reconsider the direction")
    for e in [e for e in found if e.status == "running"]:
        typer.echo(f"  running  {e.id}  {e.question}")
    for e in exp_module.rank(found):
        typer.echo(f"  {e.score:>7.2f}  {e.id}  {e.question}  ({e.est_hours:g} h)")


@exp_app.command("start")
def exp_start(campaign: str = typer.Argument(...), exp_id: str = typer.Argument(...)):
    """Mark a proposed experiment as running."""
    exp_module.start(_campaign(campaign), exp_id)
    typer.echo(f"{exp_id} running")


@exp_app.command("finish")
def exp_finish(
    campaign: str = typer.Argument(...),
    exp_id: str = typer.Argument(...),
    result: str = typer.Option(..., help="What was found, in a sentence or two."),
    hours: float = typer.Option(..., help="Hours actually spent."),
    decision_changed: bool = typer.Option(
        ..., "--decision-changed/--no-decision-changed", help="Did it change the decision?"
    ),
    insight: str = typer.Option(None, help="A lasting insight to add to Insights.md."),
):
    """Record a result, the hours spent and whether it changed the decision."""
    folder = _campaign(campaign)
    exp_module.finish(
        folder,
        exp_id,
        result=result,
        hours=hours,
        decision_changed=decision_changed,
        insight=insight,
    )
    if exp_module.summary(folder)["stalled"]:
        typer.echo("! the last three results changed no decision: reconsider the direction")
    typer.echo(f"{exp_id} done")


@exp_app.command("abandon")
def exp_abandon(
    campaign: str = typer.Argument(...),
    exp_id: str = typer.Argument(...),
    reason: str = typer.Option(..., help="Why it stopped."),
    dead_end: bool = typer.Option(False, help="Also record it in Dead ends.md."),
):
    """Stop an experiment, optionally recording it as a dead end."""
    exp_module.abandon(_campaign(campaign), exp_id, reason=reason, dead_end=dead_end)
    typer.echo(f"{exp_id} abandoned")


@app.command()
def serve(
    port: int = typer.Option(8765, help="Port on 127.0.0.1."),
    open_browser: bool = typer.Option(False, "--open", help="Open the page in your browser."),
):
    """A local dashboard of usage, runs, research campaigns and recent sessions."""
    from ax import serve as serve_module

    server = serve_module.make_server(load(), port=port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    typer.echo(f"ax dashboard at {url} (Ctrl-C to stop)")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


@vault_app.command("init")
def vault_init(
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Also replace the starter views and Home note with the current ones.",
    ),
):
    """Add the starter Obsidian views, Home note and Obsidian settings where they are missing."""
    written = vault_module.init(load().vault, refresh=refresh)
    for path in written:
        typer.echo(f"wrote {path}")
    if not written:
        typer.echo("nothing to change")


@vault_app.command("commit")
def vault_commit():
    """Commit every vault change, unless gitleaks finds a secret in it."""
    try:
        result = vault_module.commit(load())
    except (vault_module.ScanFailed, vault_module.NotAVault) as exc:
        typer.echo(f"nothing committed: {exc}")
        raise typer.Exit(1) from None
    if result.findings:
        typer.echo(f"gitleaks found {len(result.findings)} possible secrets; nothing committed:")
        for f in result.findings:
            typer.echo(f"    {f.rule}  {f.file}:{f.line}  {f.fingerprint}")
        typer.echo(
            "Teach ax to redact the shape and run `ax sync`; for a false positive, narrow"
            " the allowlist in ax's own templates/gitleaks.toml (never the vault's .gitleaksignore)."
        )
        raise typer.Exit(1)
    typer.echo(f"committed {result.notes} notes" if result.committed else "nothing to commit")


@vault_app.command("push")
def vault_push():
    """Push the vault, only to a GitHub repository confirmed to be private."""
    try:
        vault_module.push(load())
    except (
        vault_module.UnsafeRemote,
        vault_module.UnsafeContent,
        vault_module.ScanFailed,
        vault_module.NotAVault,
    ) as exc:
        typer.echo(f"not pushed: {exc}")
        raise typer.Exit(1) from None
    typer.echo("pushed")


# Below this many days Claude Code deletes transcripts before most archives notice.
MIN_RETENTION_DAYS = 365


@app.command()
def sync(quiet: bool = typer.Option(False, "--quiet", "-q", help="Print nothing unless it fails.")):
    """Archive new and changed sessions into the vault, then refresh the rules' lifecycle."""
    from ax import learn_life

    config = load()
    try:
        report = sync_module.sync(config)
    except sync_module.SyncBusy as busy:
        # Hooks fire from many sessions at once; the running sync will pick their files up.
        typer.echo(f"{busy}; skipping")
        raise typer.Exit(0) from None
    updated, unreadable = [], []
    try:
        with sync_module.lock(config):  # syncs from many sessions must not write notes at once
            updated, unreadable = learn_life.after_sync(config)
    except sync_module.SyncBusy:
        pass  # the sync that holds the lock refreshes the rules
    except Exception as exc:  # the archive is synced either way; report, don't hide it
        report.errors.append(f"learn: {type(exc).__name__}: {exc}")
    for path, problem in unreadable:  # the user's to fix; the other rules were refreshed
        typer.echo(f"warning: rule note {path} skipped: {problem}")
    if not quiet or report.errors:
        typer.echo(
            f"discovered {report.discovered} · parsed {report.parsed} · wrote {report.written}"
            f" · renamed {report.renamed} · removed {report.removed}"
            f" · excluded {report.excluded} · not rendered {report.not_rendered}"
            f" · rules updated {len(updated)}"
        )
        for error in report.errors:
            typer.echo(f"error: {error}", err=True)
    raise typer.Exit(1 if report.errors else 0)


@app.command()
def here(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """This conversation's handle and note, for building on it from another conversation."""
    from ax import handles

    config = load()
    found = handles.current(config)
    if not found:
        typer.echo("not inside a Claude Code or Codex conversation", err=True)
        raise typer.Exit(2)
    provider, session_id = found
    with contextlib.suppress(sync_module.SyncBusy):  # a running sync writes it instead
        sync_module.sync(config)  # so the note exists and has this turn
    try:
        row = handles.resolve(config, f"{provider}:{session_id}")
    except handles.NotFound:
        row = {"title": None, "note_path": None}
    result = {"handle": handles.tag(session_id), "session_id": session_id, "provider": provider,
              "title": row["title"], "note": row["note_path"]}  # fmt: skip
    if as_json:
        typer.echo(json.dumps(result, indent=2))
        return
    typer.echo(f"{result['handle']}  {row['title'] or '(not archived yet)'}")
    if row["note_path"]:
        typer.echo(str(config.vault / row["note_path"]))


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


job_app = typer.Typer(no_args_is_help=True, help="Long jobs any agent can register and wait on.")
app.add_typer(job_app, name="job")
_JSON = typer.Option(False, "--json", help="Machine-readable output.")
_SHARE = typer.Option(
    None, "--share", help="Start a follower with a dashboard: none (this Mac), lan or cloudflare."
)
_NOTIFY = typer.Option(False, "--notify", help="Start a follower that sends ntfy messages.")
_WAKE = typer.Option(
    None,
    "--wake",
    help="auto, claude or codex: when the job ends, resume the session that registered it.",
)


def _start_follower(
    config, key: str, share: str | None, notify: bool, show_log=False, wake=None
) -> None:
    """Start a detached follower when asked; its link goes to stderr, so stdout stays capturable."""
    if share is None and not notify and not wake:
        return
    args = ["--share", share or "none"] + (["--notify"] if notify else [])
    args += ["--show-log"] if show_log else []
    args += ["--wake", wake] if wake else []
    try:
        info = job_follow.start_detached(config, key, args)
    except RuntimeError as exc:
        typer.echo(f"follower not started: {exc}", err=True)
        raise typer.Exit(2) from None
    typer.echo(f"dashboard: {info['link']}", err=True)


def _jobs_config():
    return load()


def _progress(job) -> str:
    return jobs_module.progress_text(job)


def _left(config, job) -> str:
    eta = None if job.terminal else job_eta.estimate(config, job)
    return job_eta.duration_text(eta["remaining"]["p50"]) if eta else ""


def _jobs_table(config, found) -> str:
    lines = [
        f"{'key':<28} {'kind':<9} {'status':<8} {'progress':<20} {'left':<9} {'updated':<9} stage"
    ]
    for j in found:
        updated = _ago(jobs_module.parse_iso(j.updated))
        flag = " ⚠ " + j.check_error if j.check_error else ""
        lines.append(
            f"{j.key[:28]:<28} {j.kind:<9} {j.status:<8} {_progress(j)[:20]:<20} "
            f"{_left(config, j):<9} {updated:<9} {j.stage or ''}{flag}"
        )
    return "\n".join(lines)


def _no_such_job(key: str):
    typer.echo(f"no job {key!r}; see `ax job ls --all`", err=True)
    raise typer.Exit(69)


def _job_or_exit(fn):
    try:
        return fn()
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None


@job_app.command("new")
def job_new(
    key: str = typer.Argument(..., help="A short name for the job, used as its folder."),
    total: float = typer.Option(None, help="Total units of work, if known."),
    unit: str = typer.Option(None, help="What the counts measure, e.g. rows."),
    label: str = typer.Option(None, help="A human description."),
    share: str = _SHARE,
    notify: bool = _NOTIFY,
    wake: str = _WAKE,
    as_json: bool = _JSON,
):
    """Register a job fed through its events file, and print that file's path.

    Producers append one JSON object per line, e.g. {"done": 10} or {"status": "done"}.
    """
    config = _jobs_config()
    job = _job_or_exit(lambda: jobs_module.new(config, key, total=total, unit=unit, label=label))
    path = jobs_module.events_path(config, job.key)
    if as_json:
        typer.echo(json.dumps({"key": job.key, "events_file": str(path)}))
    else:
        typer.echo(str(path))
    _start_follower(config, job.key, share, notify, wake=wake)


@job_app.command("watch")
def job_watch(
    kind: str = typer.Argument(..., help="file, pid, sagemaker, seamless, runwatch or tools."),
    ref: str = typer.Argument(
        ..., help="A path, process id, SageMaker job name, Runwatch run folder or Tools MCP job id."
    ),
    key: str = typer.Option(None, help="Name the job; defaults to one derived from REF."),
    label: str = typer.Option(None, help="A human description."),
    type_: str = typer.Option(None, "--type", help="sagemaker: processing, training or transform."),
    region: str = typer.Option(None, help="sagemaker, seamless: AWS region."),
    profile: str = typer.Option(None, help="sagemaker, seamless: AWS profile."),
    state_url: str = typer.Option(None, help="seamless: its dashboard's /api/state address."),
    done_key: str = typer.Option(None, help="file (.json): dotted path of the done count."),
    total_key: str = typer.Option(None, help="file (.json): dotted path of the total."),
    status_key: str = typer.Option(None, help="file (.json): dotted path of the status."),
    stage_key: str = typer.Option(None, help="file (.json): dotted path of the stage."),
    message_key: str = typer.Option(None, help="file (.json): dotted path of a message."),
    done_when: str = typer.Option(None, help="file: a path whose appearance means done."),
    format_: str = typer.Option(None, "--format", help="file: json or jsonl (default: by suffix)."),
    runwatch: str = typer.Option(None, help="runwatch: its command, if not on PATH."),
    state_root: str = typer.Option(None, help="tools: the Tools MCP state folder."),
    share: str = _SHARE,
    notify: bool = _NOTIFY,
    wake: str = _WAKE,
    as_json: bool = _JSON,
):
    """Register a job that ax checks itself, check it once, and print its key."""
    options = {
        "type": type_, "region": region, "profile": profile, "state_url": state_url,
        "done_key": done_key, "total_key": total_key, "status_key": status_key,
        "stage_key": stage_key, "message_key": message_key, "done_when": done_when,
        "format": format_, "runwatch": runwatch, "state_root": state_root,
    }  # fmt: skip
    config = _jobs_config()
    job = _job_or_exit(
        lambda: jobs_module.watch(config, kind, ref, key=key, label=label, options=options)
    )
    if as_json:
        typer.echo(json.dumps(job.to_dict(), indent=2))
        return
    typer.echo(job.key)
    if job.check_error:
        typer.echo(f"warning: {job.check_error}", err=True)
    _start_follower(config, job.key, share, notify, wake=wake)


def _piped_stdin() -> bytes | None:
    """Bytes piped into ax, such as a heredoc; None for a terminal or an idle pipe.

    An agent's shell may leave stdin as an open pipe nobody writes to, so a pipe is
    read only if data is ready almost at once.
    """
    stream = sys.stdin
    if stream is None or stream.isatty():
        return None
    try:
        mode = os.fstat(stream.fileno()).st_mode
    except (OSError, ValueError, io.UnsupportedOperation):
        return stream.buffer.read() or None  # an in-memory stream, as in tests
    if stat.S_ISREG(mode):
        return stream.buffer.read() or None
    if stat.S_ISFIFO(mode) and select.select([stream], [], [], 0.2)[0]:
        return stream.buffer.read() or None
    return None


@job_app.command("run")
def job_run(
    command: list[str] = typer.Argument(..., help="The command, after --."),
    key: str = typer.Option(None, help="Name the job; defaults to the program and the time."),
    label: str = typer.Option(None, help="A human description."),
    no_stdin: bool = typer.Option(False, "--no-stdin", help="Don't pass piped input on."),
    share: str = _SHARE,
    notify: bool = _NOTIFY,
    show_log: bool = typer.Option(
        False, "--show-log", help="Show the output's tail on the dashboard."
    ),
    wake: str = _WAKE,
    as_json: bool = _JSON,
):
    """Start a command detached, record its exit code, and print the job's key.

    A heredoc piped in is replayed to the command: ax job run -- python - <<'PY' ... PY.
    The command can report progress by appending JSON lines to $AX_JOB_FILE.
    """
    config = _jobs_config()
    stdin = None if no_stdin else _piped_stdin()
    job = _job_or_exit(lambda: jobs_module.run(config, command, key=key, label=label, stdin=stdin))
    if as_json:
        typer.echo(json.dumps({**job.to_dict(), "output_log": job.spec["log"]}, indent=2))
    else:
        typer.echo(job.key)
    _start_follower(config, job.key, share, notify, show_log, wake)


@job_app.command("ls")
def job_ls(
    all_: bool = typer.Option(False, "--all", help="Include finished jobs."),
    as_json: bool = _JSON,
):
    """Refresh active jobs and list them, most recently updated first."""
    config = _jobs_config()
    found = jobs_module.list_jobs(config, include_finished=all_)
    if as_json:
        typer.echo(json.dumps([j.to_dict() for j in found], indent=2))
    else:
        typer.echo(_jobs_table(config, found) if found else "no jobs")


@job_app.command("show")
def job_show(
    key: str = typer.Argument(...),
    events: int = typer.Option(10, help="How many recent events to include."),
    as_json: bool = _JSON,
):
    """One job, refreshed, with its recent events."""
    config = _jobs_config()
    job = jobs_module.refresh(config, key)
    if job is None:
        _no_such_job(key)
    recent = jobs_module.events(config, key, limit=events, latest=True) if events else []
    data = {
        **job.to_dict(),
        "events_file": str(jobs_module.events_path(config, key)),
        "follower": job_follow.running(config, key),
        "eta": None if job.terminal else job_eta.estimate(config, job),
        "events": recent,
    }
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    for name in ("key", "kind", "ref", "label", "status", "stage", "message", "check_error"):
        if data[name]:
            typer.echo(f"{name:<12} {data[name]}")
    typer.echo(f"{'progress':<12} {_progress(job)}")
    if data["eta"]:
        eta = data["eta"]
        typer.echo(f"{'eta':<12} {eta['text']}, likely at {job_eta.finish_clock(eta)}")
    typer.echo(f"{'updated':<12} {data['updated']}")
    typer.echo(f"{'events file':<12} {data['events_file']}")
    if data["follower"]:
        typer.echo(f"{'dashboard':<12} {data['follower']['link']}")
    for event in recent:
        typer.echo(f"  {event['ts']} {event['type']} {json.dumps(event['data'])}")


@job_app.command("wait")
def job_wait(
    key: str = typer.Argument(...),
    until: str = typer.Option(
        "done,failed,stopped,ended", help="Statuses to stop at; add 'stalled' to stop on stalls."
    ),
    timeout: float = typer.Option(None, help="Give up after this many seconds (exit 124)."),
    interval: float = typer.Option(15.0, help="Seconds between checks."),
    stall_after: float = typer.Option(None, help="Seconds without change that count as stalled."),
    error_after: float = typer.Option(
        600.0, help="Give up after the job's check has failed this long (exit 4); 0 never."
    ),
    as_json: bool = _JSON,
):
    """Block until the job ends; spends no tokens while waiting.

    Exit codes: 0 done, 1 failed, 2 stopped or ended, 3 stalled, 4 its check kept failing,
    124 timed out, 69 no such job.
    """
    wanted = {part.strip() for part in until.split(",") if part.strip()}
    unknown = wanted - set(jobs_module.STATUSES) - {"stalled"}
    if unknown:
        typer.echo(f"unknown status in --until: {', '.join(sorted(unknown))}", err=True)
        raise typer.Exit(2)
    try:
        outcome, job = jobs_module.wait(
            _jobs_config(),
            key,
            until=wanted,
            timeout=timeout,
            interval=interval,
            stall_after=stall_after,
            error_after=error_after or None,
        )
    except KeyError:
        _no_such_job(key)
    if as_json:
        typer.echo(json.dumps({"outcome": outcome, "job": job.to_dict()}, indent=2))
    else:
        note = f" · {job.message}" if job.message else ""
        if outcome == "check_error":
            note = f" · {job.check_error}"
        typer.echo(f"{job.key}: {outcome} · {_progress(job)}{note}")
    raise typer.Exit(jobs_module.WAIT_CODES.get(outcome, 1))


@job_app.command("poll")
def job_poll(
    background: bool = typer.Option(
        False,
        "--background",
        help="The service's pass: skip followed jobs, restart dead followers, and check "
        "AWS only for jobs with a named profile.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Print only what changed."),
    as_json: bool = _JSON,
):
    """Refresh every active job once (for a scheduler)."""
    config = _jobs_config()
    if not background:
        active = jobs_module.poll(config)
        if as_json:
            typer.echo(json.dumps([j.to_dict() for j in active], indent=2))
        elif not quiet:
            typer.echo(f"{len(active)} active")
        return
    found = job_service.tick(config)
    if as_json:
        typer.echo(json.dumps(found, indent=2))
        return
    for name in ("revived", "gave_up"):
        if found[name]:
            typer.echo(f"{jobs_module.now_iso()} {name}: {', '.join(found[name])}")
    if not quiet:
        typer.echo(", ".join(f"{len(keys)} {name}" for name, keys in found.items()))


@job_app.command("service")
def job_service_cmd(
    apply: bool = typer.Option(False, "--apply", help="Write and load it; otherwise preview."),
    remove: bool = typer.Option(False, "--remove", help="Unload and delete it."),
):
    """Run `ax job poll --background` every minute with launchd (com.ax.jobs)."""
    config = _jobs_config()
    path = glue.launch_agents_dir() / f"{glue.JOBS_LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    if remove:
        if not apply:
            typer.echo(
                f"would unload and delete {path}"
                if path.exists()
                else f"nothing would change: {path} is not there"
            )
            return
        subprocess.run(["launchctl", "bootout", domain, str(path)], capture_output=True)
        path.unlink(missing_ok=True)
        typer.echo(f"removed {glue.JOBS_LABEL}")
        return
    changes = glue.plan_jobs_service(
        config, ax=glue.ax_path(), launch_agents=glue.launch_agents_dir()
    )
    _report(changes, apply)
    if apply:
        subprocess.run(["launchctl", "bootout", domain, str(path)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
        typer.echo(f"loaded {glue.JOBS_LABEL}")


@job_app.command("eta-report")
def job_eta_report(as_json: bool = _JSON):
    """How often finished jobs landed inside their 80% finish-time intervals."""
    found = job_eta.report(_jobs_config())
    if as_json:
        typer.echo(json.dumps(found, indent=2))
        return
    if not found["predictions"]:
        typer.echo("no finished job has stored estimates yet")
        return
    error = found["median_error_s"]
    typer.echo(
        f"coverage {found['coverage']:.0%} of {found['predictions']} predictions over "
        f"{found['jobs']} jobs (target {found['target']:.0%}): {found['verdict']}"
        + (f"; median miss {job_eta.duration_text(error)}" if error is not None else "")
    )


@job_app.command("forget")
def job_forget(key: str = typer.Argument(...)):
    """Drop a job and its folder in ax's data; nothing outside ax is touched."""
    config = _jobs_config()
    _job_or_exit(lambda: jobs_module.check_key(key))
    job_follow.stop(config, key)
    if not _job_or_exit(lambda: jobs_module.forget(config, key)):
        _no_such_job(key)
    typer.echo(f"forgot {key}")


@job_app.command("follow")
def job_follow_cmd(
    key: str = typer.Argument(...),
    share: str = typer.Option("none", help="Dashboard reach: none (this Mac), lan or cloudflare."),
    notify: bool = typer.Option(False, "--notify", help="Send ntfy messages."),
    every: float = typer.Option(15.0, help="Minutes between progress messages; 0 for none."),
    notify_stages: bool = typer.Option(False, "--notify-stages", help="Message each new stage."),
    stall_after: float = typer.Option(None, help="Minutes without change before a stall message."),
    linger: float = typer.Option(120.0, help="Seconds the dashboard stays up after the job ends."),
    show_log: bool = typer.Option(False, "--show-log", help="Show output.log's tail on the page."),
    port: int = typer.Option(0, help="Local port for the dashboard; 0 picks a free one."),
    interval: float = typer.Option(3.0, help="Seconds between refreshes."),
    detach: bool = typer.Option(False, "--detach", help="Run in the background; print the link."),
    wake: str = _WAKE,
    resumed: bool = typer.Option(
        False, "--resumed", hidden=True, help="Restarted by the poller: send nothing twice."
    ),
    as_json: bool = _JSON,
):
    """Follow a job: a mini dashboard, optional sharing, ntfy messages and a wake-up at the end."""
    config = _jobs_config()
    options = job_follow.FollowOptions(
        share=share, notify=notify, every=every * 60, notify_stages=notify_stages,
        stall_after=None if stall_after is None else stall_after * 60, linger=linger,
        show_log=show_log, interval=interval, port=port, wake=wake, resumed=resumed,
    )  # fmt: skip
    if detach:
        args = job_follow.options_args(options)
        if jobs_module.get(config, key) is None:
            _no_such_job(key)
        try:
            info = job_follow.start_detached(config, key, args)
        except RuntimeError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(info, indent=2) if as_json else info["link"])
        return

    def ready(info):
        typer.echo(json.dumps(info) if as_json else f"dashboard: {info['link']}", err=not as_json)

    try:
        status = job_follow.follow(config, key, options, on_ready=ready)
    except job_follow.AlreadyFollowing as exc:
        typer.echo(exc.info["link"])
        return
    except KeyError:
        _no_such_job(key)
    except (ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"{key}: {status}", err=True)


@job_app.command("wake")
def job_wake_cmd(
    key: str = typer.Argument(...),
    agent: str = typer.Option("auto", help="auto, claude or codex."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the command; run nothing."),
    as_json: bool = _JSON,
):
    """Resume the session that registered the job, with a note on its state."""
    config = _jobs_config()
    job = jobs_module.refresh(config, key)
    if job is None:
        _no_such_job(key)
    try:
        if dry_run:
            found = job_wake.plan(config, job, agent, require=False)
        else:
            found = job_wake.wake(config, job, agent)
    except job_wake.WakeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    if as_json:
        typer.echo(json.dumps(found, indent=2))
    elif dry_run:
        typer.echo(job_wake.describe(found))
        typer.echo(found["argv"][-1])
    else:
        typer.echo(f"woke the {found['agent']} session (pid {found['pid']}); log: {found['log']}")


@job_app.command("unfollow")
def job_unfollow(key: str = typer.Argument(...)):
    """Stop a job's follower; the job itself carries on."""
    if not job_follow.stop(_jobs_config(), key):
        typer.echo(f"{key} has no follower", err=True)
        raise typer.Exit(1)
    typer.echo(f"stopped the follower of {key}")


@app.command("brief")
def brief_cmd(
    kind: str = typer.Argument(..., help="implement, review, scout or continue."),
    repo: str = typer.Option(".", help="The repository the worker works in."),
    task: str = typer.Option(None, help="What the worker should do or answer."),
    task_file: str = typer.Option(None, help="Read the task from this file."),
    path: list[str] = typer.Option(
        [], "--path", help="A file it owns (implement) or should look at; repeatable."
    ),
    accept: list[str] = typer.Option([], "--accept", help="An acceptance criterion; repeatable."),
    diff: str = typer.Option(None, help="review: the revision range to review, e.g. main..HEAD."),
    session: str = typer.Option(None, help="continue: the archived session id or its start."),
    provider: str = typer.Option("claude", help="claude (worker.py) or codex (codex exec)."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Write a worker brief that carries your rules, and print the launch plan.

    Nothing is launched: show the plan to the user and start the worker only after they
    approve its count, model and effort.
    """
    from ax import brief as brief_module

    if provider not in ("claude", "codex"):
        typer.echo("--provider must be claude or codex", err=True)
        raise typer.Exit(2)
    if task_file:
        with open(task_file) as f:
            task = f.read()
    if not task:
        typer.echo("give the task with --task or --task-file", err=True)
        raise typer.Exit(2)
    config = load()
    try:
        found = brief_module.build(
            config, kind, repo=repo, task=task.strip(), paths=path, accept=accept, diff=diff,
            session=session, provider=provider,
        )  # fmt: skip
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    found = brief_module.write(config, found)
    plan = found.plan
    if as_json:
        typer.echo(json.dumps(plan, indent=2))
        return
    typer.echo(f"brief: {plan['brief']}")
    typer.echo(
        f"plan, for the user's approval: {plan['agents']} {plan['provider']} worker · "
        f"{plan['model']} · effort {plan['effort']} · {plan['profile']} · "
        f"about ${plan['budget_usd']:g}"
    )
    typer.echo(f"  {plan['usage_note']}")
    typer.echo(f"after approval: {shlex.join(plan['command'])}")


@app.command("scorecard")
def scorecard_cmd(
    weeks: int = typer.Option(6, help="How many weeks back, this one included."),
    note: bool = typer.Option(False, "--note", help="Also write it to Scorecard.md in the vault."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """Corrections, nudges, guard blocks, worker denials, recurring errors and cost, by week."""
    from ax import scorecard

    config = load()
    card = scorecard.build(config, weeks=weeks)
    if note:
        path = config.vault / "Scorecard.md"
        path.write_text(scorecard.markdown(card), encoding="utf-8")
        typer.echo(f"wrote {path}", err=True)
    typer.echo(json.dumps(card, indent=2) if as_json else scorecard.text(card))


lab_app = typer.Typer(no_args_is_help=True, help="Replay evals that test the profile.")
app.add_typer(lab_app, name="lab")


@lab_app.command("build")
def lab_build():
    """Package the profile as a plugin and seed the starter cases."""
    from ax import lab

    root = lab.build(load())
    cases = sorted(p.parent.name for p in (root / "evals").glob("*/prompt.md"))
    typer.echo(f"{root} · {len(cases)} cases: {', '.join(cases)}")


@lab_app.command("cut")
def lab_cut(
    session: str = typer.Argument(..., help="A Claude session id, or its start."),
    turn: int = typer.Option(..., help="Which request (1 = the first) becomes the prompt."),
    name: str = typer.Option(..., help="The case's folder name."),
    rubric: str = typer.Option(
        None, help="The grader's PASS/FAIL rubric; default: the next message."
    ),
):
    """Make a case from a past Claude session, cut just before one of its requests."""
    from ax import lab

    try:
        case = lab.cut(load(), session, turn=turn, name=name, rubric=rubric)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"wrote {case}; read graders/avoids-correction.md before running it")


@lab_app.command("run")
def lab_run(
    runs: int = typer.Option(1, help="Runs per case and arm."),
    model: str = typer.Option("sonnet", help="The model under test."),
    max_cost: float = typer.Option(5.0, help="Stop once this many dollars are spent."),
    case: str = typer.Option(None, help="Only cases whose name matches this glob."),
    no_shell: bool = typer.Option(
        False, "--no-shell", help="Grant no Bash and run only the cases that need none."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the command; run nothing."),
):
    """Run the cases with and without the profile plugin, and print the scores.

    Exits 1 when any run errored instead of being scored.
    """
    from ax import lab

    config = load()
    lab.build(config)
    options = {"runs": runs, "model": model, "max_cost": max_cost, "case": case,
               "no_shell": no_shell}  # fmt: skip
    if dry_run:
        typer.echo(shlex.join(lab.command(config, **options)))
        return
    lines, errored = lab.summary(lab.run(config, **options))
    typer.echo("\n".join(lines))
    if errored:
        raise typer.Exit(1)


learn_app = typer.Typer(
    no_args_is_help=True, help="Propose profile rules from your corrections, for approval."
)
app.add_typer(learn_app, name="learn")


@learn_app.command("scan")
def learn_scan():
    """Collect correction candidates from both tools' sessions and Codex's memories (no model)."""
    from ax import learn

    config = load()
    found = learn.scan(config)
    path = learn.save_candidates(config, found)
    by_signal = {}
    for c in found:
        for signal in c["signals"]:
            by_signal[signal] = by_signal.get(signal, 0) + 1
    detail = ", ".join(f"{n} {name}" for name, n in sorted(by_signal.items()))
    typer.echo(f"{len(found)} candidates ({detail}) in {path}")


@learn_app.command("label")
def learn_label(
    model: str = typer.Option("haiku", help="The Claude model that labels candidates."),
    limit: int = typer.Option(None, help="Label at most this many new candidates (a pilot)."),
    batch: int = typer.Option(20, help="Candidates per model call."),
    workers: int = typer.Option(4, help="Model calls at once."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count what would be sent."),
):
    """Label new candidates with Claude through `claude -p`, redacting them first."""
    from ax import learn

    config = load()
    candidates = learn.load_candidates(config)
    if not candidates:
        typer.echo("no candidates; run `ax learn scan` first", err=True)
        raise typer.Exit(1)
    labels = learn.load_labels(config)
    todo = learn.unlabelled(candidates, labels)[: limit or None]
    calls = learn.calls(todo, batch=batch)
    if dry_run:
        typer.echo(f"would label {len(todo)} candidates in {calls} calls to {model}")
        return
    labels = learn.label(
        config, todo, model=learn.claude_model(model), batch=batch, workers=workers
    )
    kept = sum(1 for c in candidates if labels.get(c["id"], {}).get("lasting"))
    typer.echo(f"{len(labels)} labelled, {kept} of them lasting rules")


def _learn_inputs():
    from ax import learn

    config = load()
    return config, learn.load_candidates(config), learn.load_labels(config)


@learn_app.command("propose")
def learn_propose(
    max_pending: int = typer.Option(20, help="Most proposals waiting for review at once."),
):
    """Write proposal notes for groups with enough support, and report reinforced rules."""
    from ax import learn

    config, candidates, labels = _learn_inputs()
    found = learn.propose(config, candidates, labels, max_pending=max_pending)
    for rule in found:
        typer.echo(f"proposed {rule.id} ({rule.scope}): {rule.rule}")
    if found.waiting:
        typer.echo(f"{found.waiting} more wait for room; settle some proposals to see them")
    for rule_id, counts in sorted(learn.reinforcement(config, candidates, labels).items()):
        typer.echo(
            f"reinforces {rule_id}: {counts['support']} sessions, "
            f"{counts['recurrences']} after it was added"
        )


@learn_app.command("tidy")
def learn_tidy_cmd(
    model: str = typer.Option("haiku", help="The Claude model that compares the rules."),
):
    """Merge duplicate proposals and flag ones that contradict a rule (one model call)."""
    from ax import learn, learn_tidy

    report = learn_tidy.tidy(load(), model=learn.claude_model(model))
    for dropped, kept in report.merged:
        typer.echo(f"merged {dropped} into {kept}")
    for rule_id, other, why in report.flagged:
        typer.echo(f"{rule_id} may contradict {other}: {why}")
    if not report.merged and not report.flagged:
        typer.echo("no duplicates or contradictions")


@learn_app.command("guards")
def learn_guards_cmd(
    model: str = typer.Option("haiku", help="The Claude model that writes the patterns."),
):
    """Give "never" proposals a guard pattern, tested on the archive's commands."""
    from ax import learn, learn_guards

    config = load()
    results = learn_guards.propose_guards(
        config, learn.load_candidates(config), model=learn.claude_model(model)
    )
    typer.echo("\n".join(learn_guards.report(results)) or "no proposals to guard")


@learn_app.command("fixes")
def learn_fixes_cmd(
    weeks: int = typer.Option(8, help="Look for recurring errors over this many weeks."),
    model: str = typer.Option("haiku", help="The Claude model that words the fixes."),
):
    """Propose a rule for each error that keeps recurring across sessions."""
    from ax import learn, learn_fixes, scorecard

    config = load()
    errors = scorecard.recurring(config, weeks=weeks)
    for rule in learn_fixes.propose_fixes(config, errors, model=learn.claude_model(model)):
        typer.echo(f"proposed {rule.id} ({rule.scope}): {rule.rule}")
    typer.echo(f"{len(errors)} recurring errors checked")


@learn_app.command("review")
def learn_review(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """Each active rule's maturity and evidence, those that need a decision first."""
    rules = [r for r in profile_module.load_rules(load()) if r.status == "active"]
    rules.sort(key=lambda r: (not r.review, r.id))
    if as_json:
        typer.echo(json.dumps([r.to_dict() for r in rules], indent=2))
        return
    for r in rules:
        counts = (
            f"support {r.support or 0} · recurrences {r.recurrences or 0} · "
            f"blocks {r.blocks or 0} · overrides {r.overrides or 0}"
        )
        typer.echo(f"{r.id:<32} {r.maturity or '-':<12} {r.confidence or 0:>5}  {counts}")
        if r.review:
            typer.echo(f"    {r.review}")
    if not rules:
        typer.echo("no active rules")


@learn_app.command("keep")
def learn_keep(rule_id: str = typer.Argument(...)):
    """Keep a flagged rule; it counts as fresh evidence and clears the flag."""
    from ax import learn_life

    try:
        learn_life.keep(load(), rule_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"kept {rule_id}")


@learn_app.command("retire")
def learn_retire(rule_id: str = typer.Argument(...)):
    """Retire an active rule; `ax profile compile --apply` then drops it from both tools."""
    from ax import learn_life

    try:
        learn_life.retire(load(), rule_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"retired {rule_id}; run `ax profile compile --apply` to unload it")


@learn_app.command("guard")
def learn_guard(
    rule_id: str = typer.Argument(..., help="An active rule, usually one flagged to escalate."),
    model: str = typer.Option("haiku", help="The Claude model that writes the pattern."),
):
    """Give an active rule a guard, tested on the archive, and enforce it if it passes."""
    from ax import learn, learn_guards

    config = load()
    try:
        result = learn_guards.guard_rule(
            config, rule_id, learn.load_candidates(config), learn.load_labels(config),
            model=learn.claude_model(model),
        )  # fmt: skip
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo("\n".join(learn_guards.report([result])))
    if result.status == "guarded":
        typer.echo("run `ax profile compile --apply` to load the guard")


@learn_app.command("list")
def learn_list(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """Proposals waiting for your decision."""
    found = [r for r in profile_module.load_rules(load()) if r.status == "proposed"]
    if as_json:
        typer.echo(json.dumps([r.to_dict() for r in found], indent=2))
        return
    for rule in found:
        typer.echo(f"{rule.id:<32} {rule.scope:<22} {rule.rule}")
    if not found:
        typer.echo("no proposals")


@learn_app.command("accept")
def learn_accept(rule_id: str = typer.Argument(...)):
    """Make a proposal an active rule; edit its note first if the wording is off."""
    from ax import learn

    try:
        rule = learn.accept(load(), rule_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"accepted {rule.id}; run `ax profile compile --apply` to load it")


@learn_app.command("reject")
def learn_reject(rule_id: str = typer.Argument(...)):
    """Drop a proposal; it returns only if its support doubles."""
    from ax import learn

    try:
        learn.reject(load(), rule_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(f"rejected {rule_id}")


@learn_app.command("recall")
def learn_recall(as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """How many active rules the labelled corrections rediscover."""
    from ax import learn

    found = learn.recall(*_learn_inputs())
    if as_json:
        typer.echo(json.dumps(found, indent=2))
        return
    total = len(found["found"]) + len(found["missed"])
    typer.echo(f"rediscovered {len(found['found'])} of {total} active rules")
    for name in ("found", "missed"):
        if found[name]:
            typer.echo(f"  {name}: {', '.join(found[name])}")


profile_app = typer.Typer(no_args_is_help=True, help="One set of working rules for both tools.")
app.add_typer(profile_app, name="profile")


@profile_app.command("seed")
def profile_seed():
    """Write the starting rules into the vault's Profile/rules (never overwrites)."""
    written = profile_module.seed(load())
    typer.echo(
        f"wrote {len(written)} rules" + (": " + ", ".join(r.id for r in written) if written else "")
    )


@profile_app.command("list")
def profile_list(as_json: bool = _JSON):
    """The rules, with scope, level and status."""
    rules = profile_module.load_rules(load())
    if as_json:
        typer.echo(json.dumps([r.to_dict() for r in rules], indent=2))
        return
    for r in rules:
        typer.echo(f"{r.id:<24} {r.scope:<18} {r.level:<7} {r.status:<9} {r.rule[:70]}")


@profile_app.command("add")
def profile_add(
    rule_id: str = typer.Argument(..., help="lowercase-with-dashes"),
    rule: str = typer.Option(..., help="The rule, as agents should read it."),
    scope: str = typer.Option("global", help="global or repo:NAME."),
    level: str = typer.Option("advice", help="advice, check or block."),
    tools: str = typer.Option("claude,codex", help="Which tools get it."),
    status: str = typer.Option("active", help="active, proposed or retired."),
    evidence: list[str] = typer.Option([], help="Where the rule comes from; repeatable."),
    retire_when: str = typer.Option("", help="When the rule stops being needed."),
    replace: bool = typer.Option(False, "--replace", help="Change an existing rule."),
):
    """Add or change one rule note in the vault."""
    try:
        r = profile_module.add(
            load(), rule_id, rule=rule, scope=scope, level=level, status=status,
            tools=[t.strip() for t in tools.split(",") if t.strip()],
            evidence=list(evidence), retire_when=retire_when, replace=replace,
        )  # fmt: skip
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    typer.echo(str(r.path))


@profile_app.command("compile")
def profile_compile(apply: bool = typer.Option(False, "--apply", help="Write the changes.")):
    """Show (or with --apply, write) the rules' blocks in each tool's instruction files."""
    config = load()
    changes = profile_module.compile_profile(config, apply=apply)
    for change in changes:
        typer.echo(change.diff())
    for name in profile_module.missing_repos(config):
        typer.echo(f"warning: repo {name!r} not found; set [profile.repos] {name} = PATH", err=True)
    if not changes:
        typer.echo("nothing to change")
    elif not apply:
        typer.echo(f"{len(changes)} files would change; run with --apply to write them")
    else:
        typer.echo(f"wrote {len(changes)} files")


@profile_app.command("check")
def profile_check(as_json: bool = _JSON):
    """Instructions that contradict a rule, required settings, and uncovered memories.

    Exits 1 when a conflict or a setting needs attention.
    """
    findings = profile_module.check(load())
    if as_json:
        typer.echo(
            json.dumps(
                [{**f.__dict__, "path": str(f.path) if f.path else None} for f in findings],
                indent=2,
            )
        )
    else:
        groups: dict = {}
        for f in findings:  # one line per finding, however many copies of a skill repeat it
            groups.setdefault((f.kind, f.rule, f.message), []).append(f)
        for (kind, rule, message), same in groups.items():
            first = same[0]
            where = f"{first.path}:{first.line}" if first.line else f"{first.path}"
            more = f" (and {len(same) - 1} more copies)" if len(same) > 1 else ""
            typer.echo(f"{kind:<12} {rule or '-':<22} {where}{more}\n             {message}")
        if not findings:
            typer.echo("no conflicts")
    if any(f.kind in ("conflict", "setting") for f in findings):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

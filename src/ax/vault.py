"""The vault as a Git repository: starter views, a secret-scanned commit, a private-only push.

The vault holds work transcripts, so nothing is committed while gitleaks
reports a finding, and nothing is pushed to a remote GitHub does not confirm
is private.
"""

import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ax.config import Config

_TEMPLATES = Path(__file__).parent / "templates"
# Template name → where it goes in the vault.
_STARTERS = {
    "Sessions.base": "Bases/Sessions.base",
    "Home.md": "Home.md",
    "gitleaks.toml": ".gitleaks.toml",
}
_GITHUB = re.compile(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$")


class UnsafeRemote(RuntimeError):
    """The vault's remote is not a GitHub repository confirmed to be private."""


class ScanFailed(RuntimeError):
    """gitleaks could not run, so the commit cannot be shown to be clean."""


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    fingerprint: str = ""


@dataclass
class CommitResult:
    committed: bool
    notes: int = 0
    findings: list[Finding] = field(default_factory=list)


def init(path: Path) -> list[Path]:
    """Write the starter views and Home note where they are missing; never overwrite."""
    created = []
    for template, relative in _STARTERS.items():
        target = Path(path) / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((_TEMPLATES / template).read_text(encoding="utf-8"), encoding="utf-8")
        created.append(target)
    return created


def commit(config: Config, *, scan: Callable[[Path], list[Finding]] | None = None) -> CommitResult:
    """Stage every vault change and commit it, unless the secret scan finds anything."""
    scan = scan or gitleaks_scan
    repo = config.vault
    _git(repo, "add", "-A")
    # -z gives raw names; git otherwise quotes any name with non-ASCII characters.
    staged = [n for n in _git(repo, "diff", "--cached", "--name-only", "-z").split("\0") if n]
    if not staged:
        return CommitResult(committed=False)
    try:
        findings = scan(repo)
    except Exception:
        _git(repo, "reset", "-q")
        raise
    if findings:
        _git(repo, "reset", "-q")
        return CommitResult(committed=False, findings=findings)
    notes = sum(name.endswith(".md") for name in staged)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    _git(repo, "commit", "-q", "-m", f"Sync {notes} notes ({stamp})")
    return CommitResult(committed=True, notes=notes)


def push(config: Config, *, visibility_of: Callable[[str], str | None] | None = None) -> None:
    """Push the current branch, but only to a remote confirmed to be private."""
    visibility_of = visibility_of or gh_visibility
    url = _git(config.vault, "remote", "get-url", "origin").strip()
    visibility = visibility_of(url)
    if visibility is None:
        raise UnsafeRemote(f"could not confirm that {url} is a private GitHub repository")
    if visibility != "PRIVATE":
        raise UnsafeRemote(f"{url} is {visibility}; the vault only goes to a PRIVATE repository")
    _git(config.vault, "push", "-q", "origin", "HEAD")


def github_slug(url: str) -> str | None:
    match = _GITHUB.search(url)
    return f"{match.group(1)}/{match.group(2)}" if match else None


def gh_visibility(url: str) -> str | None:
    """PRIVATE, PUBLIC or INTERNAL as GitHub reports it; None when it can't be checked."""
    slug = github_slug(url)
    if not slug:
        return None
    result = subprocess.run(
        ["gh", "repo", "view", slug, "--json", "visibility", "-q", ".visibility"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def gitleaks_scan(repo: Path) -> list[Finding]:
    """Scan the staged changes with gitleaks; secrets never appear in its output."""
    config = Path(repo) / ".gitleaks.toml"
    extra = ["--config", str(config)] if config.exists() else []
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        result = subprocess.run(
            [
                "gitleaks", "git", "--staged", "--redact", "--no-banner", *extra,
                "--report-format", "json", "--report-path", str(report), str(repo),
            ],
            capture_output=True,
            text=True,
        )  # fmt: skip
        if result.returncode not in (0, 1) or not report.exists():
            raise ScanFailed(result.stderr.strip() or f"gitleaks exited {result.returncode}")
        rows = json.loads(report.read_text() or "[]")
    return [
        Finding(
            r.get("RuleID", "?"),
            r.get("File", "?"),
            r.get("StartLine", 0),
            r.get("Fingerprint", ""),
        )
        for r in rows
    ]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout

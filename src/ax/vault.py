"""The vault as a Git repository: starter views, a secret-scanned commit, a private-only push.

The vault holds work transcripts. A commit records exactly the tree that
gitleaks scanned, and nothing is committed while it reports a finding. A push
goes only to a remote GitHub confirms is private, after scanning the tree it
sends. The scan uses the config shipped with ax, never one from the vault, and
runs on a copy with neutral file names and NUL bytes blanked, so gitleaks'
path allowlist and binary detection cannot skip a note.
"""

import json
import os
import re
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

from ax.config import Config

_TEMPLATES = Path(__file__).parent / "templates"
GITLEAKS_CONFIG = _TEMPLATES / "gitleaks.toml"
# Template name → where it goes in the vault.
_STARTERS = {
    "Sessions.base": "Bases/Sessions.base",
    "Experiments.base": "Bases/Experiments.base",
    "Rules.base": "Bases/Rules.base",
    "Home.md": "Home.md",
}
# Obsidian's own settings: written when the vault has none, never replaced, since the
# app rewrites them as you change settings.
_OBSIDIAN = ("app.json", "core-plugins.json", "bookmarks.json")
_GITHUB = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

Scan = Callable[[Path], list["Finding"]]


class UnsafeRemote(RuntimeError):
    """The vault's remote is not a GitHub repository confirmed to be private."""


class UnsafeContent(RuntimeError):
    """The tree about to be pushed contains a possible secret."""


class ScanFailed(RuntimeError):
    """gitleaks could not run, so the content cannot be shown to be clean."""


class NotAVault(RuntimeError):
    """The vault folder is not the root of its own Git repository."""


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


def init(path: Path, *, refresh: bool = False) -> list[Path]:
    """Write the starter views, the Home note and Obsidian's settings where they are missing.

    `refresh` also replaces the starter views and Home note with the current templates,
    for a vault set up by an older ax. Obsidian's settings and every other note are
    never overwritten.
    """
    written = []
    starters = {_TEMPLATES / t: Path(path) / r for t, r in _STARTERS.items()}
    settings = {_TEMPLATES / "obsidian" / n: Path(path) / ".obsidian" / n for n in _OBSIDIAN}
    for source, target in [*starters.items(), *settings.items()]:
        text = source.read_text(encoding="utf-8")
        replace = refresh and target in starters.values()
        if target.exists() and (not replace or target.read_text(encoding="utf-8") == text):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def commit(config: Config, *, scan: Scan | None = None) -> CommitResult:
    """Stage every vault change and commit exactly the scanned tree, or nothing."""
    scan = scan or gitleaks_scan
    repo = _check_root(config.vault)
    _git(repo, "add", "-A")
    staged = [n for n in _git(repo, "diff", "--cached", "--name-only", "-z").split("\0") if n]
    if not staged:
        return CommitResult(committed=False)
    tree = _git(repo, "write-tree").strip()
    try:
        findings = _scan_tree(repo, tree, scan)
    except Exception:
        _git(repo, "reset", "-q")
        raise
    if findings:
        _git(repo, "reset", "-q")
        return CommitResult(committed=False, findings=findings)
    notes = sum(name.endswith(".md") for name in staged)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    head = _head(repo)
    parents = ["-p", head] if head else []
    message = f"Sync {notes} notes ({stamp})"
    new = _git(repo, "commit-tree", tree, *parents, "-m", message).strip()
    # Fails if HEAD moved since it was read, rather than dropping someone's commit.
    _git(repo, "update-ref", "-m", "ax vault commit", "HEAD", new, *([head] if head else []))
    return CommitResult(committed=True, notes=notes)


def push(
    config: Config,
    *,
    visibility_of: Callable[[str], str | None] | None = None,
    scan: Scan | None = None,
) -> None:
    """Push HEAD to its branch on origin: only to a private GitHub repo, only a clean tree."""
    visibility_of = visibility_of or gh_visibility
    scan = scan or gitleaks_scan
    repo = _check_root(config.vault)
    # Every URL git would really push to, after pushurl and pushInsteadOf.
    urls = _git(repo, "remote", "get-url", "--push", "--all", "origin").split()
    if len(urls) != 1:
        raise UnsafeRemote(f"origin pushes to {len(urls)} URLs; expected exactly one")
    url = urls[0]
    visibility = visibility_of(url)
    if visibility is None:
        raise UnsafeRemote(f"could not confirm that {url} is a private GitHub repository")
    if visibility != "PRIVATE":
        raise UnsafeRemote(f"{url} is {visibility}; the vault only goes to a PRIVATE repository")
    head = _head(repo)
    if not head:
        raise UnsafeContent("nothing to push: the vault has no commits")
    findings = _scan_tree(repo, head, scan)
    if findings:
        listed = ", ".join(f"{f.rule} in {f.file}:{f.line}" for f in findings[:5])
        raise UnsafeContent(f"possible secrets in what would be pushed: {listed}")
    branch = _git(repo, "symbolic-ref", "--short", "HEAD").strip()
    _git(repo, "push", "-q", url, f"{head}:refs/heads/{branch}")


def github_slug(url: str) -> str | None:
    match = _GITHUB.match(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def gh_visibility(url: str) -> str | None:
    """PRIVATE, PUBLIC or INTERNAL as GitHub reports it; None when it can't be checked."""
    slug = github_slug(url)
    if not slug:
        return None
    try:
        result = subprocess.run(
            ["gh", "repo", "view", slug, "--json", "visibility", "-q", ".visibility"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def gitleaks_scan(directory: Path) -> list[Finding]:
    """Scan every file under `directory` with ax's own gitleaks config."""
    directory = Path(directory)
    with tempfile.TemporaryDirectory() as tmp:
        neutral = Path(tmp) / "files"
        neutral.mkdir()
        names: dict[str, str] = {}
        for i, path in enumerate(p for p in sorted(directory.rglob("*")) if p.is_file()):
            alias = f"{i:06d}.txt"
            names[alias] = path.relative_to(directory).as_posix()
            (neutral / alias).write_bytes(path.read_bytes().replace(b"\0", b" "))
        report = Path(tmp) / "report.json"
        command = [
            "gitleaks", "dir", "--no-banner", "--redact", "--config", str(GITLEAKS_CONFIG),
            "--report-format", "json", "--report-path", str(report), str(neutral),
        ]  # fmt: skip
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError:
            raise ScanFailed("gitleaks is not installed or not on PATH") from None
        if result.returncode not in (0, 1) or not report.exists():
            raise ScanFailed(result.stderr.strip() or f"gitleaks exited {result.returncode}")
        rows = json.loads(report.read_text() or "[]")
    return [
        Finding(
            r.get("RuleID", "?"),
            names.get(Path(r.get("File", "")).name, r.get("File", "?")),
            r.get("StartLine", 0),
            r.get("Fingerprint", ""),
        )
        for r in rows
    ]


def _scan_tree(repo: Path, treeish: str, scan: Scan) -> list[Finding]:
    """Export a tree (not the working copy, which can change) and scan it."""
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", treeish], capture_output=True
    )
    if archive.returncode != 0:
        raise ScanFailed(archive.stderr.decode(errors="replace").strip())
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=BytesIO(archive.stdout)) as tar:
            tar.extractall(tmp, filter="data")
        return scan(Path(tmp))


def _check_root(path: Path) -> Path:
    repo = Path(path).resolve()
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if result.returncode != 0 or Path(result.stdout.strip()).resolve() != repo:
        raise NotAVault(f"{repo} is not the root of its own Git repository")
    return repo


def _head(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "-q", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout

"""Where ax reads sessions from and writes notes, backups and its database."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("~/.config/ax/config.toml")


@dataclass(frozen=True)
class Config:
    vault: Path
    data: Path
    claude_home: Path
    codex_home: Path
    exclude: tuple[str, ...] = ()
    render_guardian: bool = False
    # Claude Code's global config, where /usage caches the allowance it last saw.
    claude_json: Path = Path("~/.claude.json").expanduser()
    # The delegation skill's usage helper; None means the copy in this repository.
    claude_usage_script: Path | None = None
    # Percent of a window to keep free, e.g. (("claude.weekly", 25),); guards default to it.
    reserve: tuple[tuple[str, float], ...] = ()
    # Folders holding delegation run directories; empty means ask Spotlight.
    run_roots: tuple[Path, ...] = ()
    # ntfy for `ax job` notifications; no topic means none are sent.
    notify_server: str = "https://ntfy.sh"
    notify_topic: str | None = None
    # Codex's newer skills folder, beside ~/.codex/skills.
    agents_home: Path = Path("~/.agents").expanduser()
    # `ax profile`: where repo-scoped rules land (a repo is <root>/<name> unless listed).
    profile_repos_root: Path = Path("~/Repos").expanduser()
    profile_repos: dict = field(default_factory=dict)
    # Extra folders whose SKILL.md files `ax profile check` reads, e.g. the desktop app's plugins.
    profile_extra_dirs: tuple[Path, ...] = ()
    # `ax sync` labels up to 40 new learner candidates with Haiku (a model call) unless false.
    learn_label_on_sync: bool = True
    # `ax find`: the repos Semble searches (empty: every git checkout under the repos root),
    # more repos to add to those, qmd's config folder, and whether sync refreshes the index.
    find_repos: tuple[Path, ...] = ()
    find_extra_repos: tuple[Path, ...] = ()
    find_qmd_dir: Path = Path("~/.config/qmd").expanduser()
    find_refresh_on_sync: bool = True
    find_qmd_port: int = 8181  # where `ax index serve` keeps qmd's daemon
    # `ax sync` copies Claude's memories into Codex's ad-hoc memory notes unless false.
    share_memories: bool = True

    @property
    def db_path(self) -> Path:
        return self.data / "ax.db"

    @property
    def raw_dir(self) -> Path:
        return self.data / "raw"


def load(path: Path | None = None) -> Config:
    """Read the config file; every key is optional and falls back to the defaults."""
    path = Path(path or os.environ.get("AX_CONFIG") or DEFAULT_PATH).expanduser()
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    paths = raw.get("paths", {})
    sync = raw.get("sync", {})
    usage = raw.get("usage", {})
    runs = raw.get("runs", {})
    notify = raw.get("notify", {})
    prof = raw.get("profile", {})
    learning = raw.get("learn", {})
    finding = raw.get("find", {})
    qmd_dir = os.environ.get("QMD_CONFIG_DIR") or (
        f"{os.environ['XDG_CONFIG_HOME']}/qmd"
        if os.environ.get("XDG_CONFIG_HOME")
        else "~/.config/qmd"
    )
    desktop_plugins = Path(
        "~/Library/Application Support/Claude/local-agent-mode-sessions"
    ).expanduser()

    def p(key, default):
        return Path(paths.get(key, default)).expanduser()

    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    script = paths.get("claude_usage_script")
    return Config(
        vault=p("vault", "~/Vaults/agents"),
        data=p("data", "~/.local/share/ax"),
        claude_home=p("claude_home", claude_dir or "~/.claude"),
        codex_home=p("codex_home", os.environ.get("CODEX_HOME", "~/.codex")),
        exclude=tuple(os.path.expanduser(pattern) for pattern in sync.get("exclude", ())),
        render_guardian=bool(sync.get("render_guardian", False)),
        claude_json=p(
            "claude_json", f"{claude_dir}/.claude.json" if claude_dir else "~/.claude.json"
        ),
        claude_usage_script=Path(script).expanduser() if script else None,
        reserve=tuple((k, float(v)) for k, v in usage.get("reserve", {}).items()),
        run_roots=tuple(Path(r).expanduser() for r in runs.get("roots", ())),
        notify_server=str(notify.get("server", "https://ntfy.sh")),
        notify_topic=notify.get("topic") or None,
        agents_home=p("agents_home", "~/.agents"),
        profile_repos_root=Path(prof.get("repos_root", "~/Repos")).expanduser(),
        profile_repos={k: Path(v).expanduser() for k, v in prof.get("repos", {}).items()},
        profile_extra_dirs=tuple(
            Path(d).expanduser()
            for d in prof.get(
                "extra_dirs", [str(desktop_plugins)] if desktop_plugins.is_dir() else []
            )
        ),
        learn_label_on_sync=bool(learning.get("label_on_sync", True)),
        find_repos=tuple(Path(r).expanduser() for r in finding.get("repos", ())),
        find_extra_repos=tuple(Path(r).expanduser() for r in finding.get("extra_repos", ())),
        find_qmd_dir=Path(finding.get("qmd_config_dir", qmd_dir)).expanduser(),
        find_refresh_on_sync=bool(finding.get("refresh_on_sync", True)),
        find_qmd_port=int(finding.get("qmd_port", 8181)),
        share_memories=bool(raw.get("memory", {}).get("share", True)),
    )

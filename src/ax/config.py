"""Where ax reads sessions from and writes notes, backups and its database."""

import os
import tomllib
from dataclasses import dataclass
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
    )

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

    def p(key, default):
        return Path(paths.get(key, default)).expanduser()

    return Config(
        vault=p("vault", "~/Vaults/agents"),
        data=p("data", "~/.local/share/ax"),
        claude_home=p("claude_home", os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")),
        codex_home=p("codex_home", os.environ.get("CODEX_HOME", "~/.codex")),
        exclude=tuple(os.path.expanduser(pattern) for pattern in sync.get("exclude", ())),
        render_guardian=bool(sync.get("render_guardian", False)),
    )

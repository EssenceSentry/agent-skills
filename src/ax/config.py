"""Local configuration. Agent-facing policy stays fixed in ax."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data: Path
    claude_home: Path
    codex_home: Path
    vault: Path
    claude_json: Path
    claude_desktop: Path | None = None

    @property
    def database(self):
        return self.data / "core.sqlite3"

    @property
    def socket(self):
        return self.data / "daemon.sock"

    def prepare(self):
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.data / "tasks").mkdir(exist_ok=True, mode=0o700)


def load():
    path = Path(os.environ.get("AX_CONFIG", "~/.config/ax/config.toml")).expanduser()
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    paths = raw.get("paths", {})

    def location(key, default):
        return Path(paths.get(key, default)).expanduser().resolve()

    return Config(
        location("data", "~/.local/share/ax"),
        location("claude_home", os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")),
        location("codex_home", os.environ.get("CODEX_HOME", "~/.codex")),
        location("vault", "~/Vaults/agents"),
        location("claude_json", "~/.claude.json"),
        location("claude_desktop", "~/Library/Application Support/Claude"),
    )

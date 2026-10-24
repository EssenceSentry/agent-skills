import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from ax.config import load

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_SESSION = "11111111-1111-4111-8111-111111111111"
CLAUDE_AGENT = "agent-a1b2c3d4e5f6a7b8c"
CODEX_SESSION = "22222222-2222-4222-8222-222222222222"
CODEX_SUBAGENT = "33333333-3333-4333-8333-333333333333"
CODEX_GUARDIAN = "44444444-4444-4444-8444-444444444444"
CODEX_FORK = "55555555-5555-4555-8555-555555555555"

CLAUDE_PROJECT = FIXTURES / "claude" / "projects" / "-Users-me-Repos-demo"
CLAUDE_MAIN = CLAUDE_PROJECT / f"{CLAUDE_SESSION}.jsonl"
CLAUDE_SUB = CLAUDE_PROJECT / CLAUDE_SESSION / "subagents" / f"{CLAUDE_AGENT}.jsonl"
CODEX_DAY = FIXTURES / "codex" / "sessions" / "2026" / "10" / "20"
CODEX_MAIN = CODEX_DAY / f"rollout-2026-10-20T10-00-00-{CODEX_SESSION}.jsonl"
CODEX_SUB = CODEX_DAY / f"rollout-2026-10-20T10-05-00-{CODEX_SUBAGENT}.jsonl"
CODEX_GUARD = CODEX_DAY / f"rollout-2026-10-20T10-06-00-{CODEX_GUARDIAN}.jsonl"
CODEX_FORKED = CODEX_DAY / f"rollout-2026-10-20T11-00-00-{CODEX_SESSION}_{CODEX_FORK}.jsonl"


@pytest.fixture
def env(tmp_path):
    """A throwaway Claude home, Codex home, vault and config built from the fixtures."""
    claude_home = tmp_path / "claude"
    codex_home = tmp_path / "codex"
    shutil.copytree(FIXTURES / "claude", claude_home)
    shutil.copytree(FIXTURES / "codex", codex_home)
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[paths]\n"
        f'vault = "{vault}"\n'
        f'data = "{tmp_path / "data"}"\n'
        f'claude_home = "{claude_home}"\n'
        f'codex_home = "{codex_home}"\n'
    )
    return SimpleNamespace(
        root=tmp_path,
        claude_home=claude_home,
        codex_home=codex_home,
        vault=vault,
        config_path=config_path,
        config=load(config_path),
        claude_main=claude_home / CLAUDE_MAIN.relative_to(FIXTURES / "claude"),
        codex_main=codex_home / CODEX_MAIN.relative_to(FIXTURES / "codex"),
    )

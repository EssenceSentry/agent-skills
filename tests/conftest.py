import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from ax.config import load
from ax.store import Store
from learning import messages, session

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
        f'[find]\nqmd_config_dir = "{tmp_path / "qmd"}"\n'
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


@pytest.fixture
def archive(env):
    """An archive with corrections in human sessions, a worker, a subagent and Codex memories."""
    with Store(env.config.db_path) as store:
        db = store.db
        session(db, "s1")
        messages(db, "s1", ("assistant", "I also tidied the typings folder."),
                 ("user", "Don't touch files unrelated to what I asked for."),
                 ("user", "Thanks, looks good."))  # fmt: skip
        session(db, "s2", project="other")
        messages(db, "s2", ("assistant", "Running uv sync now."),
                 ("user", "[Request interrupted by user]"),
                 ("user", "Use the bootstrap script, it keeps the editable install."))  # fmt: skip
        session(db, "worker", entrypoint="sdk-cli")
        messages(db, "worker", ("user", "Never commit anything; you are a delegated worker."))
        session(db, "sub", kind="subagent")
        messages(db, "sub", ("user", "Do not edit files."))
        session(db, "s3")
        messages(db, "s3", ("user", "PLEASE IMPLEMENT THIS PLAN: never do X"),
                 ("user", "# Files mentioned by the user:\n\n## a.txt: /x/a.txt\n\n"
                          "## My request for Codex:\nStop adding compatibility shims."),
                 ("user", "I don't know, maybe."))  # fmt: skip
        store.commit()
    memories = env.config.codex_home / "memories"
    memories.mkdir(parents=True, exist_ok=True)
    (memories / "raw_memories.md").write_text(
        "# Raw Memories\n\n## Thread `t-1`\nupdated_at: 2026-09-01T10:00:00+00:00\n"
        "cwd: /Users/me/Repos/auto-classifier\n\n### Task 1: Scope\n\nPreference signals:\n"
        '- the user said: "I don\'t care about breaking changes" -> drop backward '
        "compatibility shims\n\nReusable knowledge:\n- not a preference\n"
    )
    return env


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    """Tests never reach a real model: one that needs a model passes its own fake."""
    from ax import learn

    asked = []

    def refuse(*args, **kwargs):
        def ask(prompt):
            asked.append(prompt)
            raise RuntimeError("tests never call a real model")

        return ask

    monkeypatch.setattr(learn, "claude_model", refuse)
    yield
    assert not asked, "a test reached the real model"


@pytest.fixture(autouse=True)
def no_search_tools(monkeypatch):
    """Tests never run the real qmd or Semble: one that needs them passes its own runner."""
    from ax import find

    def refuse(argv, **kwargs):
        raise AssertionError(f"a test ran the real {argv[0]}")

    monkeypatch.setattr(find, "_run", refuse)

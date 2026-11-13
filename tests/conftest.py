import pytest

from ax.config import Config
from ax.db import initialize


@pytest.fixture
def config(tmp_path):
    config = Config(
        tmp_path / "data",
        tmp_path / "claude",
        tmp_path / "codex",
        tmp_path / "vault",
        tmp_path / "claude.json",
    )
    initialize(config)
    return config

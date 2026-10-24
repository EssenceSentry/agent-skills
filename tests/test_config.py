from pathlib import Path

from ax.config import load


def test_exclude_patterns_expand_the_home_directory(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[sync]\nexclude = ["~/secret/*", "/abs/*"]\n')
    assert load(path).exclude == (str(Path.home() / "secret/*"), "/abs/*")

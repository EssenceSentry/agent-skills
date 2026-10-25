from pathlib import Path

import typer.main
import yaml

from ax.cli import app

SKILL = Path(__file__).parent.parent / "skills" / "ax" / "SKILL.md"


def commands() -> list[str]:
    return sorted(typer.main.get_command(app).commands)


def test_the_ax_skill_teaches_every_top_level_command():
    text = SKILL.read_text()
    missing = [name for name in commands() if f"`ax {name}" not in text]
    assert missing == [], f"teach these in skills/ax/SKILL.md: {missing}"


def test_the_ax_skill_has_a_name_and_a_description_that_says_when():
    meta = yaml.safe_load(SKILL.read_text().split("---\n")[1])
    assert meta["name"] == "ax" and "Use when" in meta["description"]
    assert len(SKILL.read_text().splitlines()) <= 160

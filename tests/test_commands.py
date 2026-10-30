"""The / menu of a session's message box: what its tool offers there, asked of the tool
in the session's folder without a model call."""

from ax import commands


def test_claude_offers_its_commands_and_skills_to_type_after_a_slash():
    found = commands.claude_items([
        {"name": "compact", "description": "Compact the context", "argumentHint": "<instructions>"},
        {"name": "atelier", "description": "Build dashboards"},
        {"name": "__remote-workflow", "description": "internal"},
    ])  # fmt: skip
    assert [f["name"] for f in found] == ["compact", "atelier"]
    assert found[0] == {"name": "compact", "title": "compact", "description": "Compact the context",
                        "hint": "<instructions>", "insert": "/compact ", "scope": None}  # fmt: skip


def test_codex_offers_its_skills_by_their_display_names_and_scope():
    found = commands.codex_items({"data": [{"cwd": "/repo", "skills": [
        {"name": "atelier", "description": "Start and build dashboards", "scope": "user"},
        {"name": "classification-workflow", "description": "Long description", "scope": "repo",
         "interface": {"displayName": "Classification Workflow", "shortDescription": "Classify"}},
    ]}]})  # fmt: skip
    assert [(f["title"], f["insert"], f["scope"]) for f in found] == [
        ("atelier", "$atelier ", "Personal"),
        ("Classification Workflow", "$classification-workflow ", "Project"),
    ]
    assert found[1]["description"] == "Classify"


def test_what_a_folder_offers_is_asked_once_in_a_while(env, tmp_path):
    asked = []

    def ask_claude(config, folder):
        asked.append(folder)
        return [{"name": "compact", "description": "Compact"}]

    first = commands.offered(env.config, "claude", str(tmp_path), ask_claude=ask_claude, now=100.0)
    again = commands.offered(env.config, "claude", str(tmp_path), ask_claude=ask_claude, now=200.0)
    assert first == again and asked == [str(tmp_path)]
    assert first["commands"][0]["insert"] == "/compact "
    commands.offered(env.config, "claude", str(tmp_path), ask_claude=ask_claude, now=1000.0)
    assert len(asked) == 2  # ten minutes on, asked again


def test_a_tool_that_cannot_answer_offers_nothing_and_says_why(env, tmp_path):
    def broken(config, folder):
        raise OSError("claude isn't installed")

    found = commands.offered(env.config, "claude", str(tmp_path), ask_claude=broken, now=1.0)
    assert found["commands"] == [] and "claude isn't installed" in found["error"]

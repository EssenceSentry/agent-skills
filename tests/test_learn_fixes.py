import json

from ax import learn_fixes, profile

TIMEOUT = {"signature": "(eval):N: command not found: timeout", "sessions": 12,
           "last_seen": "2026-10-25", "projects": ["agent-skills", "ds-models"],
           "examples": ["timeout 600 ax scorecard --weeks 8"]}  # fmt: skip
PYRIGHT = {"signature": "warning: there is a new pyright version available (vN.N.N -> vN.N.N).",
           "sessions": 44, "last_seen": "2026-10-25", "projects": ["demo"],
           "examples": ["uv run pyright src"]}  # fmt: skip
CACHE = {"signature": "filenotfounderror: [errno N] no such file or directory: '…'",
         "sessions": 4, "last_seen": "2026-10-20", "projects": ["ds-models"],
         "examples": ["uv run python scripts/report.py"]}  # fmt: skip


def fixes(**by_signature):
    def model(prompt):
        model.prompts.append(prompt)
        items = [json.loads(line) for line in prompt.splitlines() if line.startswith('{"id"')]
        return json.dumps([{"id": i["id"], **by_signature.get(i["error"][:7], {"fix": ""})}
                           for i in items])  # fmt: skip

    model.prompts = []
    return model


def test_a_recurring_error_with_a_fix_becomes_a_proposal(env):
    model = fixes(**{
        "(eval):": {"fix": "On macOS there is no `timeout`; run long commands in the background.",
                    "topic": "no-timeout-on-macos"},
        "filenot": {"fix": "Run `make data` before `scripts/report.py`.",
                    "topic": "check-report-inputs"},
        "warning": {"fix": "Validate inputs before using them.", "topic": "validate-inputs"},
    })  # fmt: skip
    written = learn_fixes.propose_fixes(env.config, [TIMEOUT, PYRIGHT, CACHE], model=model)
    assert [r.id for r in written] == ["no-timeout-on-macos", "check-report-inputs"]
    rules = {r.id: r for r in profile.load_rules(env.config)}
    timeout = rules["no-timeout-on-macos"]
    assert timeout.status == "proposed" and timeout.scope == "global"
    assert "12 sessions" in timeout.why and "timeout 600 ax scorecard" in timeout.why
    assert rules["check-report-inputs"].scope == "repo:ds-models"
    assert "new pyright version" in model.prompts[0]
    assert "validate-inputs" not in rules  # a fix that names no command is generic advice


def test_each_error_is_asked_about_once(env):
    model = fixes()
    learn_fixes.propose_fixes(env.config, [TIMEOUT, PYRIGHT], model=model)
    assert learn_fixes.propose_fixes(env.config, [TIMEOUT, PYRIGHT], model=model) == []
    assert len(model.prompts) == 1


def test_a_fix_an_existing_rule_already_gives_is_not_proposed_again(env):
    profile.add(env.config, "no-timeout-on-macos", rule="There is no `timeout` on macOS.")
    model = fixes(**{"(eval):": {"fix": "Don't call `timeout` on macOS.",
                                 "topic": "no-timeout-on-macos"}})  # fmt: skip
    assert learn_fixes.propose_fixes(env.config, [TIMEOUT], model=model) == []
    assert "no-timeout-on-macos: There is no `timeout` on macOS." in model.prompts[0]

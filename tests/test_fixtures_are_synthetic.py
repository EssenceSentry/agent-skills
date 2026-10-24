"""This repo is public: fixtures must never contain real transcripts or home paths."""

import getpass
import re

from conftest import FIXTURES


def fixture_texts():
    for path in FIXTURES.rglob("*"):
        if path.is_file() and path.suffix in {".jsonl", ".json", ".py"}:
            yield path, path.read_text(encoding="utf-8")


def test_home_paths_are_the_placeholder_user():
    for path, text in fixture_texts():
        users = set(re.findall(r"/Users/([^/\"\s]+)/", text))
        assert users <= {"me"}, f"{path} mentions {users - {'me'}}"


def test_the_local_account_name_never_appears():
    name = getpass.getuser()
    for path, text in fixture_texts():
        assert name not in text, f"{path} contains the local account name"

import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from ax import vault
from ax.cli import app
from ax.sync import sync

runner = CliRunner()


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(env):
    git(env.vault, "init", "-q", "-b", "main")
    git(env.vault, "config", "user.email", "me@example.com")
    git(env.vault, "config", "user.name", "Me")
    vault.init(env.config.vault)
    git(env.vault, "add", "-A")
    git(env.vault, "commit", "-qm", "skeleton")
    return env


def clean_scan(path):
    return []


def test_init_writes_views_and_home_without_overwriting(env):
    created = vault.init(env.config.vault)
    assert (env.vault / "Bases" / "Sessions.base").exists()
    assert (env.vault / "Home.md").exists()
    assert "Sessions.base" in (env.vault / "Home.md").read_text()
    (env.vault / "Home.md").write_text("mine")
    assert vault.init(env.config.vault) == []
    assert (env.vault / "Home.md").read_text() == "mine"
    assert created


def test_commit_records_new_notes_when_the_scan_is_clean(repo):
    sync(repo.config)
    result = vault.commit(repo.config, scan=clean_scan)
    assert result.committed
    assert "5 notes" in git(repo.vault, "log", "-1", "--format=%s")
    assert git(repo.vault, "status", "--porcelain") == ""


def test_commit_refuses_and_unstages_when_the_scan_finds_a_secret(repo):
    sync(repo.config)

    def leaky(path):
        return [vault.Finding("generic-api-key", "Sessions/x.md", 12)]

    result = vault.commit(repo.config, scan=leaky)
    assert not result.committed
    assert result.findings[0].rule == "generic-api-key"
    assert git(repo.vault, "log", "--format=%s") == "skeleton\n"
    assert git(repo.vault, "diff", "--cached", "--name-only") == ""


def test_commit_with_nothing_new_is_a_no_op(repo):
    result = vault.commit(repo.config, scan=clean_scan)
    assert not result.committed
    assert result.findings == []


def test_push_refuses_a_remote_that_is_not_private(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo.vault, "remote", "add", "origin", str(remote))
    with pytest.raises(vault.UnsafeRemote, match="PUBLIC"):
        vault.push(repo.config, visibility_of=lambda url: "PUBLIC")
    with pytest.raises(vault.UnsafeRemote, match="could not confirm"):
        vault.push(repo.config, visibility_of=lambda url: None)
    assert (
        subprocess.run(["git", "-C", str(remote), "log"], capture_output=True).returncode != 0
    )  # nothing reached the remote


def test_push_sends_commits_to_a_private_remote(repo, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo.vault, "remote", "add", "origin", str(remote))
    vault.push(repo.config, visibility_of=lambda url: "PRIVATE")
    assert git(remote, "log", "--format=%s", "main") == "skeleton\n"


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://github.com/me/agent-vault.git", "me/agent-vault"),
        ("https://github.com/me/agent-vault", "me/agent-vault"),
        ("git@github.com:me/agent-vault.git", "me/agent-vault"),
        ("/tmp/remote.git", None),
        ("https://gitlab.com/me/agent-vault.git", None),
    ],
)
def test_github_slugs_are_read_from_remote_urls(url, slug):
    assert vault.github_slug(url) == slug


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_real_gitleaks_findings_block_the_commit(repo):
    # A made-up key in the shape gitleaks' aws-access-token rule matches.
    (repo.vault / "Projects").mkdir(exist_ok=True)
    (repo.vault / "Projects" / "leak.md").write_text("aws_access_key_id = AKIAQWERTYUIOPASDFGH\n")
    result = vault.commit(repo.config)
    assert not result.committed
    assert [f.file for f in result.findings] == ["Projects/leak.md"]


def test_vault_commit_command_lists_findings_and_fails(repo, monkeypatch):
    sync(repo.config)
    monkeypatch.setattr(
        vault, "gitleaks_scan", lambda path: [vault.Finding("jwt", "Sessions/a.md", 3, "fp1")]
    )
    result = runner.invoke(app, ["vault", "commit"], env={"AX_CONFIG": str(repo.config_path)})
    assert result.exit_code == 1
    assert "jwt" in result.output
    assert "Sessions/a.md:3" in result.output
    assert ".gitleaksignore" in result.output


def test_vault_push_command_refuses_public_remotes(repo, monkeypatch):
    git(repo.vault, "remote", "add", "origin", "https://github.com/me/agent-vault.git")
    monkeypatch.setattr(vault, "gh_visibility", lambda url: "PUBLIC")
    result = runner.invoke(app, ["vault", "push"], env={"AX_CONFIG": str(repo.config_path)})
    assert result.exit_code == 1
    assert "PRIVATE" in result.output


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_known_hash_fields_pass_but_real_keys_still_fail(repo):
    hashes = (
        '"prompt_cache_key": "a8a7f2c49d1e4b6a8c3e5f7091b2d4c6e8f0a1b3c5d7e9f1"\n'
        '"input_cache_key": "bfc61d3e5f7a9b1c3d5e7f9a1b3c5d7e9f1a3b5c7d9e1f3a"\n'
    )
    (repo.vault / "Projects").mkdir(exist_ok=True)
    (repo.vault / "Projects" / "hashes.md").write_text(hashes)
    assert vault.commit(repo.config).committed
    (repo.vault / "Projects" / "leak.md").write_text("aws_access_key_id = AKIAQWERTYUIOPASDFGH\n")
    assert not vault.commit(repo.config).committed


def test_init_adds_the_gitleaks_allowlist(env):
    vault.init(env.config.vault)
    config = (env.vault / ".gitleaks.toml").read_text()
    assert "useDefault = true" in config
    assert "prompt_cache_key" in config


def test_notes_with_non_ascii_names_are_counted(repo):
    (repo.vault / "Projects").mkdir(exist_ok=True)
    (repo.vault / "Projects" / "Café plan — résumé.md").write_text("notes\n")
    assert vault.commit(repo.config, scan=clean_scan).notes == 1

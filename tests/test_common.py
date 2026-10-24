from ax.sources.common import project_name


def test_project_is_the_git_root_of_the_working_directory(tmp_path):
    (tmp_path / "shop" / ".git").mkdir(parents=True)
    (tmp_path / "shop" / "src" / "api").mkdir(parents=True)
    assert project_name(str(tmp_path / "shop" / "src" / "api")) == "shop"


def test_worktrees_resolve_to_their_main_repository(tmp_path):
    main = tmp_path / "shop"
    (main / ".git" / "worktrees" / "feature").mkdir(parents=True)
    worktree = tmp_path / "elsewhere" / "feature"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'feature'}\n")
    assert project_name(str(worktree)) == "shop"


def test_missing_directory_falls_back_to_the_repository_url():
    assert project_name("/nowhere/x", "https://github.com/me/demo.git") == "demo"
    assert project_name("/nowhere/x", "git@github.com:me/demo.git") == "demo"


def test_missing_directory_without_url_uses_the_folder_name():
    assert project_name("/nowhere/Repos/demo") == "demo"


def test_unknown_when_nothing_is_known():
    assert project_name(None) == "unknown"

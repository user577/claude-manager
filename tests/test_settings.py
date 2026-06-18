import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.config.settings import Settings, RepoInfo, GitHubAccount, LEGACY_USERNAME


def test_repo_info_exists(tmp_path):
    repo = RepoInfo(path=str(tmp_path), label="test")
    assert repo.exists()

    repo2 = RepoInfo(path=str(tmp_path / "nonexistent"), label="bad")
    assert not repo2.exists()


def test_settings_save_load(tmp_path):
    config_file = tmp_path / "settings.json"
    with patch("src.config.settings.CONFIG_FILE", config_file), \
         patch("src.config.settings.CONFIG_DIR", tmp_path):
        s = Settings(
            repos=[RepoInfo(path="/foo", label="foo")],
            layout="vertical",
            instance_count=2,
            permission_mode="auto",
            github_dir="/bar",
        )
        s.save()

        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["layout"] == "vertical"
        assert data["instance_count"] == 2
        assert data["permission_mode"] == "auto"
        # New format: repos live under the (single, legacy) account.
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["folder"] == "/bar"
        assert len(data["accounts"][0]["repos"]) == 1

        s2 = Settings.load()
        assert s2.layout == "vertical"
        assert s2.instance_count == 2
        assert s2.permission_mode == "auto"
        assert s2.repos[0].label == "foo"
        assert s2.github_dir == "/bar"


def test_settings_load_missing_file(tmp_path):
    config_file = tmp_path / "nope.json"
    empty_dir = tmp_path / "empty_github"
    empty_dir.mkdir()
    # Patch both the module-level default AND the dataclass field default
    original_init = Settings.__init__

    def patched_init(self, *args, **kwargs):
        if "github_dir" not in kwargs:
            kwargs["github_dir"] = str(empty_dir)
        original_init(self, *args, **kwargs)

    with patch("src.config.settings.CONFIG_FILE", config_file), \
         patch("src.config.settings.CONFIG_DIR", tmp_path), \
         patch.object(Settings, "__init__", patched_init):
        s = Settings.load()
        assert s.layout == "grid_2x2"
        assert s.repos == []


def test_settings_load_corrupt_json(tmp_path):
    config_file = tmp_path / "settings.json"
    config_file.write_text("{bad json!!", encoding="utf-8")
    with patch("src.config.settings.CONFIG_FILE", config_file), \
         patch("src.config.settings.CONFIG_DIR", tmp_path):
        s = Settings.load()
        assert s.layout == "grid_2x2"


def test_discover_repos(tmp_path):
    # Create fake git repos
    for name in ["repo-a", "repo-b", "not-a-repo"]:
        d = tmp_path / name
        d.mkdir()
    (tmp_path / "repo-a" / ".git").mkdir()
    (tmp_path / "repo-b" / ".git").mkdir()

    s = Settings(github_dir=str(tmp_path))
    s.discover_repos()
    labels = {r.label for r in s.repos}
    assert "repo-a" in labels
    assert "repo-b" in labels
    assert "not-a-repo" not in labels


def test_discover_repos_no_duplicates(tmp_path):
    (tmp_path / "myrepo").mkdir()
    (tmp_path / "myrepo" / ".git").mkdir()

    s = Settings(
        repos=[RepoInfo(path=str(tmp_path / "myrepo"), label="myrepo")],
        github_dir=str(tmp_path),
    )
    s.discover_repos()
    assert len(s.repos) == 1


def test_get_enabled_repos(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / ".git").mkdir()

    s = Settings(repos=[
        RepoInfo(path=str(tmp_path / "a"), label="a", enabled=True),
        RepoInfo(path=str(tmp_path / "missing"), label="missing", enabled=True),
        RepoInfo(path=str(tmp_path / "a"), label="a-disabled", enabled=False),
    ])
    enabled = s.get_enabled_repos()
    assert len(enabled) == 1
    assert enabled[0].label == "a"


def test_load_migrates_legacy_format(tmp_path):
    """An old config (top-level github_dir + repos) loads into one account."""
    config_file = tmp_path / "settings.json"
    config_file.write_text(json.dumps({
        "layout": "grid_2x2",
        "github_dir": "/legacy/path",
        "repos": [{"path": "/legacy/path/r1", "label": "r1", "tags": ["x"]}],
    }), encoding="utf-8")
    with patch("src.config.settings.CONFIG_FILE", config_file), \
         patch("src.config.settings.CONFIG_DIR", tmp_path):
        s = Settings.load()
        assert len(s.accounts) == 1
        assert s.accounts[0].username == LEGACY_USERNAME
        assert s.github_dir == "/legacy/path"
        assert s.repos[0].label == "r1"
        assert s.repos[0].tags == ["x"]


def test_sync_accounts_adopts_legacy_into_active():
    """The legacy bucket is renamed to the active gh account, keeping repos."""
    s = Settings(github_dir="/work", repos=[RepoInfo(path="/work/a", label="a")])
    changed = s.sync_accounts(["user577"], "user577")
    assert changed
    assert [a.username for a in s.accounts] == ["user577"]
    assert s.active_account == "user577"
    assert s.repos[0].label == "a"  # folder + repos preserved


def test_sync_accounts_adds_new_accounts():
    s = Settings(github_dir="/work")
    s.sync_accounts(["user577"], "user577")  # adopt legacy -> user577
    changed = s.sync_accounts(["user577", "acct2"], "user577")
    assert changed
    names = {a.username for a in s.accounts}
    assert names == {"user577", "acct2"}
    # New account starts with no folder.
    acct2 = next(a for a in s.accounts if a.username == "acct2")
    assert acct2.folder == ""


def test_sync_accounts_tracks_active_switch():
    s = Settings(github_dir="/work")
    s.sync_accounts(["user577", "acct2"], "user577")
    assert s.active_account == "user577"
    # gh active changed (e.g. user ran gh auth switch elsewhere)
    s.sync_accounts(["user577", "acct2"], "acct2")
    assert s.active_account == "acct2"


def test_per_account_repos_are_isolated():
    s = Settings(accounts=[
        GitHubAccount(username="user577", folder="/a",
                      repos=[RepoInfo(path="/a/x", label="x")]),
        GitHubAccount(username="acct2", folder="/b",
                      repos=[RepoInfo(path="/b/y", label="y")]),
    ], active_account="user577")
    assert [r.label for r in s.repos] == ["x"]
    assert s.github_dir == "/a"
    s.active_account = "acct2"
    assert [r.label for r in s.repos] == ["y"]
    assert s.github_dir == "/b"

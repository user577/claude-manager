import subprocess

from src.config.settings import RepoInfo
from src.core.git_operations import pull_repo, push_repo
from src.core.repo_scanner import classify_sync, scan_one


def git(path, *args) -> str:
    r = subprocess.run(["git", "-C", str(path), *args],
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


def commit(path, name):
    (path / name).write_text(name)
    git(path, "add", name)
    git(path, "commit", "-qm", name)


def new_repo(path):
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")


def untracked_clone(tmp_path):
    """A repo whose main was pushed with `git push origin main` (no -u)."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    local = tmp_path / "local"
    new_repo(local)
    git(local, "remote", "add", "origin", str(remote))
    commit(local, "a")
    git(local, "push", "-q", "origin", "main")
    return remote, local


def other_clone_pushes(tmp_path, remote, name):
    other = tmp_path / f"other-{name}"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    commit(other, name)
    git(other, "push", "-q")


def scan(path, fetch=False):
    return scan_one(RepoInfo(path=str(path), label="t"), fetch=fetch)


def test_ahead_is_seen_without_an_upstream(tmp_path):
    _, local = untracked_clone(tmp_path)
    commit(local, "b")
    s = scan(local)
    assert (s.ahead, s.behind) == (1, 0)
    assert s.has_remote
    assert s.inferred_upstream == "origin/main"


def test_behind_and_diverged_are_seen_after_fetch(tmp_path):
    remote, local = untracked_clone(tmp_path)
    other_clone_pushes(tmp_path, remote, "theirs")
    s = scan(local, fetch=True)
    assert (s.ahead, s.behind) == (0, 1)
    assert classify_sync([s]).behind == [s]

    commit(local, "mine")
    s = scan(local)
    assert s.diverged
    assert classify_sync([s]).diverged == [s]


def test_real_upstream_is_not_marked_inferred(tmp_path):
    _, local = untracked_clone(tmp_path)
    git(local, "branch", "--set-upstream-to=origin/main")
    commit(local, "b")
    s = scan(local)
    assert (s.ahead, s.inferred_upstream) == (1, "")


def test_never_pushed_branch_has_no_remote(tmp_path):
    _, local = untracked_clone(tmp_path)
    git(local, "switch", "-q", "-c", "feature")
    s = scan(local)
    assert not s.has_remote and s.inferred_upstream == ""


def test_push_sets_the_missing_upstream(tmp_path):
    remote, local = untracked_clone(tmp_path)
    commit(local, "b")
    ok, out = push_repo(str(local))
    assert ok, out
    assert "Set upstream to origin/main" in out
    assert git(local, "rev-parse", "--abbrev-ref", "@{u}") == "origin/main"
    assert git(remote, "rev-parse", "main") == git(local, "rev-parse", "HEAD")


def test_pull_sets_the_missing_upstream(tmp_path):
    remote, local = untracked_clone(tmp_path)
    other_clone_pushes(tmp_path, remote, "theirs")
    git(local, "fetch", "-q")
    ok, out = pull_repo(str(local))
    assert ok, out
    assert (local / "theirs").exists()


def test_failed_fetch_is_reported_without_masking_the_scan(tmp_path):
    _, local = untracked_clone(tmp_path)
    commit(local, "b")
    git(local, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    s = scan(local, fetch=True)
    assert s.fetch_error
    assert s.error is None
    assert s.ahead == 1  # still measured against the cached remote ref

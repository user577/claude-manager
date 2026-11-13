"""Green means the repo matches its remote: nothing exists only on this disk."""
from types import SimpleNamespace

from src.core.git_operations import push_repo
from src.gui.git_status_panel import push_targets
from tests.test_inferred_upstream import (
    commit, git, new_repo, other_clone_pushes, scan,
)


def tracked_clone(tmp_path):
    """A clone with main pushed and tracking origin/main."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    local = tmp_path / "local"
    new_repo(local)
    git(local, "remote", "add", "origin", str(remote))
    commit(local, "a")
    git(local, "push", "-q", "-u", "origin", "main")
    return remote, local


def test_clean_tracked_clone_matches_remote(tmp_path):
    _, local = tracked_clone(tmp_path)
    s = scan(local)
    assert s.unpushed_branches == []
    assert not s.no_remote
    assert s.matches_remote


def test_local_only_side_branch_is_not_green(tmp_path):
    _, local = tracked_clone(tmp_path)
    git(local, "switch", "-q", "-c", "side")
    commit(local, "b")
    git(local, "switch", "-q", "main")
    s = scan(local)
    assert s.unpushed_branches == ["side"]
    assert (s.ahead, s.behind) == (0, 0)  # the old rule called this green
    assert not s.matches_remote


def test_never_pushed_checked_out_branch_is_listed(tmp_path):
    _, local = tracked_clone(tmp_path)
    git(local, "switch", "-q", "-c", "feature")
    commit(local, "b")
    s = scan(local)
    assert s.branch == "feature"
    assert s.unpushed_branches == ["feature"]
    assert not s.matches_remote


def test_branch_with_no_new_commits_is_not_unpushed(tmp_path):
    _, local = tracked_clone(tmp_path)
    git(local, "branch", "empty")  # points at a pushed commit
    assert scan(local).unpushed_branches == []


def test_stash_is_not_green(tmp_path):
    _, local = tracked_clone(tmp_path)
    (local / "a").write_text("changed")
    git(local, "stash", "-q")
    s = scan(local)
    assert s.stash_count == 1 and not s.dirty
    assert not s.matches_remote


def test_no_remote_is_not_green(tmp_path):
    local = tmp_path / "solo"
    new_repo(local)
    commit(local, "a")
    s = scan(local)
    assert s.no_remote
    assert not s.matches_remote


def test_push_sends_unpushed_branches_and_sets_upstream(tmp_path):
    remote, local = tracked_clone(tmp_path)
    git(local, "switch", "-q", "-c", "side")
    commit(local, "b")
    git(local, "switch", "-q", "main")
    ok, out = push_repo(str(local))
    assert ok, out
    assert git(remote, "rev-parse", "side") == git(local, "rev-parse", "side")
    assert git(local, "rev-parse", "--abbrev-ref", "side@{u}") == "origin/side"
    assert scan(local).matches_remote


def test_push_skips_a_behind_current_branch_but_sends_the_rest(tmp_path):
    remote, local = tracked_clone(tmp_path)
    other_clone_pushes(tmp_path, remote, "theirs")
    git(local, "fetch", "-q")
    git(local, "switch", "-q", "-c", "side")
    commit(local, "b")
    git(local, "switch", "-q", "main")
    ok, out = push_repo(str(local))
    assert ok, out
    assert "behind" in out
    assert git(remote, "rev-parse", "side") == git(local, "rev-parse", "side")
    s = scan(local)
    assert s.behind == 1 and s.unpushed_branches == []


def test_push_never_forces_a_rejected_branch(tmp_path):
    remote, local = tracked_clone(tmp_path)
    git(local, "switch", "-q", "-c", "side")
    commit(local, "b")
    git(local, "push", "-q", "-u", "origin", "side")
    # Someone else moves origin/side; ours diverges.
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", "-b", "side", str(remote), str(other))
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    commit(other, "theirs")
    git(other, "push", "-q")
    commit(local, "ours")
    git(local, "switch", "-q", "main")
    remote_side = git(remote, "rev-parse", "side")
    ok, out = push_repo(str(local))
    assert not ok
    assert git(remote, "rev-parse", "side") == remote_side


def test_push_targets_include_repos_with_only_unpushed_branches():
    repo = SimpleNamespace(path="r", label="r")
    base = dict(error=None, has_remote=True, ahead=0, behind=0,
                no_remote=False, unpushed_branches=[])
    assert push_targets([repo], {"r": SimpleNamespace(**base)}) == []
    s = SimpleNamespace(**{**base, "unpushed_branches": ["side"]})
    assert push_targets([repo], {"r": s}) == [repo]
    s = SimpleNamespace(**{**base, "unpushed_branches": ["side"], "no_remote": True})
    assert push_targets([repo], {"r": s}) == []

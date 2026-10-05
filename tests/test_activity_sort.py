import os
import subprocess

from src.config.settings import RepoInfo
from src.core.repo_scanner import (
    RepoStatus, newest_mtime, porcelain_v2_path, scan_one,
)

SHA = "0" * 40


def test_porcelain_v2_path_per_entry_kind():
    assert porcelain_v2_path(f"1 .M N... 100644 100644 100644 {SHA} {SHA} src/a b.py") == "src/a b.py"
    assert porcelain_v2_path(f"2 R. N... 100644 100644 100644 {SHA} {SHA} R100 new.py\told.py") == "new.py"
    assert porcelain_v2_path(f"u UU N... 100644 100644 100644 100644 {SHA} {SHA} {SHA} c.py") == "c.py"
    assert porcelain_v2_path("? notes/todo.txt") == "notes/todo.txt"


def test_porcelain_v2_path_ignores_headers():
    assert porcelain_v2_path("# branch.head master") is None
    assert porcelain_v2_path("") is None


def test_newest_mtime_skips_missing_paths(tmp_path):
    (tmp_path / "old.txt").write_text("x")
    (tmp_path / "new.txt").write_text("x")
    os.utime(tmp_path / "old.txt", (1_000_000, 1_000_000))
    os.utime(tmp_path / "new.txt", (2_000_000, 2_000_000))
    assert newest_mtime(str(tmp_path), ["old.txt", "new.txt", "deleted.txt"]) == 2_000_000
    assert newest_mtime(str(tmp_path), []) == 0


def test_activity_is_the_newer_of_commit_and_worktree():
    s = RepoStatus(path="x", label="x", last_commit_ts=100, last_worktree_ts=300)
    assert s.last_activity_ts == 300
    s.last_worktree_ts = 0
    assert s.last_activity_ts == 100


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def test_scan_counts_uncommitted_edits_as_activity(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one")
    _git(tmp_path, "add", "a.txt")
    env = {**os.environ, "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z",
           "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z"}
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"],
                   check=True, capture_output=True, env=env)

    clean = scan_one(RepoInfo(path=str(tmp_path), label="t"))
    assert clean.last_worktree_ts == 0
    assert clean.last_activity_ts == clean.last_commit_ts == 978307200

    (tmp_path / "a.txt").write_text("two")
    (tmp_path / "b.txt").write_text("new")
    os.utime(tmp_path / "b.txt", (2_000_000_000, 2_000_000_000))
    dirty = scan_one(RepoInfo(path=str(tmp_path), label="t"))
    assert dirty.last_worktree_ts == 2_000_000_000
    assert dirty.last_activity_ts == 2_000_000_000

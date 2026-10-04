import subprocess
import threading
import time

import pytest

from src.config.settings import RepoInfo
from src.core.repo_scanner import (
    RepoStatus, verify_remote_sync, classify_sync, remote_endpoint, _ProbeCache,
)
from src.gui.git_status_panel import sync_prompt_lines


def status(**kw) -> RepoStatus:
    kw.setdefault("path", "C:/repos/x")
    kw.setdefault("label", "x")
    return RepoStatus(**kw)


# --- classify_sync ---

def test_in_sync_repos_need_no_prompt():
    report = classify_sync([status(), status(ahead=2), status(modified_count=3)])
    assert not report.needs_prompt
    assert report.behind == report.diverged == report.unchecked == []


def test_behind_repo_is_pullable():
    s = status(behind=3)
    report = classify_sync([s])
    assert report.needs_prompt
    assert report.behind == [s]
    assert report.diverged == []


def test_diverged_repo_is_not_pullable():
    # diverged also has behind > 0; it must not land in the pull list, where a
    # ff-only pull would just fail.
    s = status(ahead=1, behind=2, diverged=True)
    report = classify_sync([s])
    assert report.diverged == [s]
    assert report.behind == []


def test_fetch_failure_alone_does_not_block_launch():
    s = status(error="fetch timed out after 15s")
    report = classify_sync([s])
    assert report.unchecked == [s]
    assert not report.needs_prompt


def test_fetch_failure_with_stale_behind_still_prompts():
    s = status(behind=1, error="Could not resolve host")
    report = classify_sync([s])
    assert report.behind == [s]
    assert report.unchecked == [s]


# --- sync_prompt_lines ---

def test_prompt_lines_name_each_repo():
    report = classify_sync([
        status(label="alpha", behind=1),
        status(label="beta", behind=4, modified_count=2),
        status(label="gamma", ahead=1, behind=2, diverged=True),
    ])
    lines = sync_prompt_lines(report)
    assert lines[0] == "• alpha: 1 commit behind remote"
    assert lines[1].startswith("• beta: 4 commits behind remote (has local changes")
    assert "gamma: diverged (1 ahead, 2 behind)" in lines[2]
    assert "won't be pulled" in lines[2]


# --- offline fast path ---

@pytest.mark.parametrize("url, expected", [
    ("https://github.com/o/r.git", ("github.com", 443, "https")),
    ("https://gitlab.com:8443/o/r.git\n", ("gitlab.com", 8443, "https")),
    ("http://example.com/r", ("example.com", 80, "http")),
    ("ssh://git@github.com/o/r.git", ("github.com", 22, "ssh")),
    ("ssh://git@host.example:2222/r", ("host.example", 2222, "ssh")),
    ("git@github.com:o/r.git", ("github.com", 22, "ssh")),
    ("git@github-work:o/r.git", ("github-work", 22, "ssh")),
    ("git://example.com/r", ("example.com", 9418, "git")),
    # Local remotes never get probed.
    ("C:/repos/remote.git", None),
    ("C:\\repos\\remote.git", None),
    ("/srv/git/r.git", None),
    ("file:///srv/git/r.git", None),
    ("origin", None),  # what --get-url echoes when no remote is configured
])
def test_remote_endpoint(url, expected):
    assert remote_endpoint(url) == expected


def test_probe_cache_probes_each_host_once():
    calls = []
    gate = threading.Event()

    def slow_probe(host, port, scheme):
        calls.append(host)
        gate.wait(2)
        return False

    cache = _ProbeCache(slow_probe)
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        cache("github.com", 443, "https"))) for _ in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    gate.set()
    for t in threads:
        t.join()
    assert calls == ["github.com"]
    assert results == [False] * 8


# --- verify_remote_sync against real repos ---

def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_remote_and_clones(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    clones = []
    for name in ("mine", "theirs"):
        clone = tmp_path / name
        git(tmp_path, "clone", str(remote), str(clone))
        git(clone, "config", "user.email", "t@example.com")
        git(clone, "config", "user.name", "t")
        git(clone, "config", "commit.gpgsign", "false")
        clones.append(clone)
    mine, theirs = clones
    git(mine, "commit", "--allow-empty", "-m", "base")
    git(mine, "push", "-u", "origin", "HEAD:main")
    git(theirs, "pull", "origin", "main")
    git(theirs, "branch", "--set-upstream-to=origin/main")
    return mine, theirs


def test_verify_remote_sync_sees_remote_commits_without_prior_fetch(tmp_path):
    mine, theirs = make_remote_and_clones(tmp_path)
    git(theirs, "commit", "--allow-empty", "-m", "upstream work")
    git(theirs, "push")

    # mine's remote-tracking ref is stale; only a fetch reveals it's behind.
    s = verify_remote_sync(RepoInfo(path=str(mine), label="mine"))
    assert s.error is None
    assert s.behind == 1
    assert classify_sync([s]).behind == [s]


def test_verify_remote_sync_offline_skips_fetch(tmp_path):
    mine, _ = make_remote_and_clones(tmp_path)
    # A non-routable address: a real fetch would hang until the timeout.
    git(mine, "remote", "set-url", "origin", "https://10.255.255.1/o/r.git")
    probed = []

    def offline(host, port, scheme):
        probed.append((host, port))
        return False

    start = time.monotonic()
    s = verify_remote_sync(RepoInfo(path=str(mine), label="mine"), probe=offline)
    assert time.monotonic() - start < 3
    assert probed == [("10.255.255.1", 443)]
    assert s.error == "offline — couldn't reach 10.255.255.1"
    assert s.branch == "main", "local scan still runs"


def test_verify_remote_sync_unknown_probe_falls_back_to_fetch(tmp_path):
    # e.g. an ssh config alias: the probe can't tell, so the real fetch decides.
    mine, theirs = make_remote_and_clones(tmp_path)
    git(theirs, "commit", "--allow-empty", "-m", "upstream work")
    git(theirs, "push")
    s = verify_remote_sync(RepoInfo(path=str(mine), label="mine"),
                           probe=lambda *a: None)
    assert s.error is None and s.behind == 1


def test_gate_pulls_then_launches(tmp_path, monkeypatch):
    """End to end through the panel: Launch -> fetch -> prompt -> pull -> spawn."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from src.config.settings import Settings
    from src.gui.git_status_panel import GitStatusPanel

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    mine, theirs = make_remote_and_clones(tmp_path)
    git(theirs, "commit", "--allow-empty", "-m", "upstream work")
    git(theirs, "push")

    repo = RepoInfo(path=str(mine), label="mine")
    panel = GitStatusPanel(Settings(repos=[repo], github_dir=str(tmp_path)))
    prompts, spawned = [], []
    monkeypatch.setattr(panel, "_ask_sync",
                        lambda report: prompts.append(report) or "pull")
    monkeypatch.setattr(panel, "_spawn_now",
                        lambda *a: spawned.append(a))

    panel._launch_repo(repo.path, auto=False)
    assert not spawned, "must not launch before the sync check returns"
    deadline = time.monotonic() + 30
    while (not spawned or panel._gate_workers) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert len(prompts) == 1 and prompts[0].behind[0].behind == 1
    assert len(spawned) == 1
    assert verify_remote_sync(repo).behind == 0, "repo should have been fast-forwarded"
    assert not panel._gate_paths
    panel.deleteLater()


def test_verify_remote_sync_reports_unreachable_remote(tmp_path):
    mine, _ = make_remote_and_clones(tmp_path)
    git(mine, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    s = verify_remote_sync(RepoInfo(path=str(mine), label="mine"))
    assert s.error
    assert classify_sync([s]).unchecked == [s]

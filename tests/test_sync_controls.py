"""Pull/Push act on exactly what their label says: ticked repos if any are
ticked, else all — and never on repos that haven't been scanned. A Pull once
took 59 repos because unscanned ones counted as possibly behind."""

import pytest

from src.config.settings import Settings, RepoInfo
from src.core.repo_scanner import RepoStatus
from src.gui.git_status_panel import pull_targets, push_targets

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def repo(name):
    return RepoInfo(path=f"C:/r/{name}", label=name)


def st(name, **kw):
    return RepoStatus(path=f"C:/r/{name}", label=name, **kw)


def labels(repos):
    return sorted(r.label for r in repos)


def test_pull_targets_skip_unscanned_diverged_and_errors():
    repos = [repo(n) for n in ("behind", "diverged", "unscanned", "err", "clean")]
    statuses = {s.path: s for s in (
        st("behind", behind=2, has_remote=True),
        st("diverged", ahead=1, behind=1, diverged=True, has_remote=True),
        st("err", behind=1, error="Path not found"),
        st("clean", has_remote=True),
    )}
    assert labels(pull_targets(repos, statuses)) == ["behind"]


def test_push_targets_need_a_remote_and_nothing_behind():
    repos = [repo(n) for n in ("ahead", "local", "diverged", "unscanned")]
    statuses = {s.path: s for s in (
        st("ahead", ahead=1, has_remote=True),
        st("local", ahead=1, has_remote=False),
        st("diverged", ahead=1, behind=1, diverged=True, has_remote=True),
    )}
    assert labels(push_targets(repos, statuses)) == ["ahead"]


# --- panel wiring ---

@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def panel(qapp, tmp_path):
    from src.gui.git_status_panel import GitStatusPanel

    names = ("b1", "b2", "b3", "ahead", "clean")
    paths = {}
    for n in names:
        (tmp_path / n).mkdir()
        paths[n] = str(tmp_path / n)
    settings = Settings(repos=[RepoInfo(path=p, label=n) for n, p in paths.items()],
                        github_dir=str(tmp_path))
    p = GitStatusPanel(settings)
    p._statuses = {
        paths["b1"]: RepoStatus(path=paths["b1"], label="b1", behind=1, has_remote=True),
        paths["b2"]: RepoStatus(path=paths["b2"], label="b2", behind=4, has_remote=True),
        paths["b3"]: RepoStatus(path=paths["b3"], label="b3", behind=2, has_remote=True),
        paths["ahead"]: RepoStatus(path=paths["ahead"], label="ahead", ahead=1, has_remote=True),
        paths["clean"]: RepoStatus(path=paths["clean"], label="clean", has_remote=True),
    }
    started = []
    p._start_operation = lambda op, repos, msg="": started.append((op, labels(repos)))
    p._update_action_buttons()
    yield p, paths, started
    p.deleteLater()


def test_buttons_count_all_eligible_when_nothing_is_ticked(panel):
    p, _, started = panel
    assert p.sync_btn.text() == "Pull (3)" and p.sync_btn.isEnabled()
    assert p.push_btn.text() == "Push (1)" and p.push_btn.isEnabled()
    p._on_sync()
    assert started == [("fetch_pull", ["b1", "b2", "b3"])]


def test_ticks_narrow_pull_and_push(panel):
    p, paths, started = panel
    p.cards[paths["b2"]].set_selected(True)
    assert p.sync_btn.text() == "Pull (1)"
    assert p.push_btn.text() == "Push" and not p.push_btn.isEnabled()
    p._on_sync()
    p._on_push()  # nothing ticked is ahead: no-op
    assert started == [("fetch_pull", ["b2"])]


def test_actions_are_locked_while_refreshing(panel):
    p, _, started = panel
    p._stage = "fetch"
    p._update_action_buttons()
    assert not p.sync_btn.isEnabled() and not p.push_btn.isEnabled()
    p._stage = None
    p._update_action_buttons()
    assert p.sync_btn.isEnabled()


def test_request_mid_refresh_is_queued_not_raced(panel):
    p, _, _ = panel
    runs = []
    p._prepare_repos = lambda: None
    p._start_scanner = lambda fetch: runs.append(fetch)
    p._start_github_check = lambda: p._finish_refresh()
    p.refresh()
    p.scan_all()            # arrives mid-pipeline
    p.refresh()             # upgrades the queued rerun to a full one
    assert runs == [False] and p._rerun == "full"
    p._on_scan_complete()   # local done -> fetch
    p._on_scan_complete()   # fetch done -> github -> finish -> rerun
    assert runs == [False, True, False]
    assert p._rerun is None and p.refreshing


def test_clone_count_comes_from_the_github_check(panel):
    from src.core.repo_scanner import RemoteRepo
    p, _, _ = panel
    assert p.clone_btn.text() == "Clone" and not p.clone_btn.isEnabled()
    p._stage = "github"
    missing = [RemoteRepo(name="x", clone_url="u", description="", is_private=True)]
    p._on_github_sync_done(missing, [])
    assert p.clone_btn.text() == "Clone (1)" and p.clone_btn.isEnabled()

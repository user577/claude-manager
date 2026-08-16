"""Card selection drives the tiled launch, so the Select-* buttons must
actually tick the right cards — they used to only print names to the log."""

import pytest

from src.config.settings import Settings, RepoInfo
from src.core.repo_scanner import RepoStatus

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def panel(qapp, tmp_path):
    from src.gui.git_status_panel import GitStatusPanel

    paths = {}
    for name in ("clean", "dirty", "ahead", "behind", "gone"):
        d = tmp_path / name
        if name != "gone":  # "gone" deliberately has no directory on disk
            d.mkdir()
        paths[name] = str(d)

    settings = Settings(
        repos=[RepoInfo(path=p, label=n) for n, p in paths.items()],
        github_dir=str(tmp_path),
    )
    p = GitStatusPanel(settings)
    p._statuses = {
        paths["clean"]: RepoStatus(path=paths["clean"], label="clean"),
        paths["dirty"]: RepoStatus(path=paths["dirty"], label="dirty",
                                   dirty=True, modified_count=2),
        paths["ahead"]: RepoStatus(path=paths["ahead"], label="ahead", ahead=3),
        paths["behind"]: RepoStatus(path=paths["behind"], label="behind", behind=1),
        paths["gone"]: RepoStatus(path=paths["gone"], label="gone",
                                  error="Path not found"),
    }
    for path, status in p._statuses.items():
        p.cards[path].update_status(status)
    yield p, paths
    p.deleteLater()


def _selected_labels(panel_obj):
    return sorted(r.label for r in panel_obj._selected_repos())


def test_select_dirty_ticks_only_dirty(panel):
    p, _ = panel
    p._select_dirty()
    assert _selected_labels(p) == ["dirty"]


def test_select_ahead_and_behind_are_exclusive(panel):
    p, _ = panel
    p._select_ahead()
    assert _selected_labels(p) == ["ahead"]
    # Selecting again replaces the previous selection rather than adding to it.
    p._select_behind()
    assert _selected_labels(p) == ["behind"]


def test_errored_repo_is_never_selected(panel):
    p, _ = panel
    p._set_selection(lambda s: True)
    assert "gone" not in _selected_labels(p)


def test_clear_selection(panel):
    p, _ = panel
    p._select_dirty()
    assert _selected_labels(p)
    p._set_selection(lambda s: False)
    assert _selected_labels(p) == []


def test_launch_button_tracks_selection_count(panel):
    p, _ = panel
    p._set_selection(lambda s: False)
    assert not p.launch_tiled_btn.isEnabled()
    assert p.launch_tiled_btn.text() == "Launch Tiled"

    p._select_dirty()
    assert p.launch_tiled_btn.isEnabled()
    assert p.launch_tiled_btn.text() == "Launch Tiled (1)"


def test_missing_directory_excluded_even_if_ticked(panel):
    """_selected_repos filters on exists(), not just the checkbox."""
    p, paths = panel
    p.cards[paths["gone"]].select_check.setEnabled(True)  # force past the guard
    p.cards[paths["gone"]].set_selected(True)
    assert "gone" not in _selected_labels(p)

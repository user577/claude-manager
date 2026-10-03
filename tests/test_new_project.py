import subprocess
from pathlib import Path

import pytest

from src.config.settings import RepoInfo
from src.core.new_project import (
    CMD_UNSAFE, NEW_PROJECT_PROMPT, PLACEHOLDER_PREFIX, RENAME_MARKER,
    apply_pending_renames, create_blank_repo, new_project_prompt,
    pending_rename, sanitize_name,
)
from src.core.process_launcher import escape_prompt


# --- prompt ---

def test_prompt_template_is_cmd_safe():
    # The prompt rides on a cmd.exe command line; one stray quote, &, |, or %
    # would truncate it or run part of it as a shell command.
    assert not CMD_UNSAFE.search(NEW_PROJECT_PROMPT)


def test_prompt_covers_interview_and_kickoff():
    p = new_project_prompt("new-project-1")
    assert "new-project-1" in p
    assert "AskUserQuestion" in p
    assert "confirm or correct" in p
    assert RENAME_MARKER in p
    assert "PLAN.md" in p
    assert "{" not in p, "every placeholder must be filled"


def test_prompt_fits_cmd_line_limit():
    # cmd.exe caps a command line at 8191 chars; leave room for the guardrail,
    # scrub prefix, flags and a long seed idea.
    assert len(escape_prompt(new_project_prompt("x" * 40, "y" * 500))) < 5000


def test_idea_is_seeded_and_cleaned():
    p = new_project_prompt("np", 'a "tiny" CLI & web UI | 100% <fast> ^ok')
    assert "starting idea" in p
    assert not CMD_UNSAFE.search(p)
    assert "CLI and web UI" in p


def test_blank_idea_adds_nothing():
    assert "starting idea" not in new_project_prompt("np", "   ")


# --- naming ---

@pytest.mark.parametrize("raw, expected", [
    ("tray-gen", "tray-gen"),
    ("  My Tool \n", "My Tool"),
    ("..", None),
    ("", None),
    ("a/b", None),
    ("a\\b", None),
    ("bad:name", None),
    ("what?", None),
])
def test_sanitize_name(raw, expected):
    assert sanitize_name(raw) == expected


# --- create / rename against the real filesystem ---

def test_create_blank_repo(tmp_path):
    path = Path(create_blank_repo(str(tmp_path)))
    assert path.parent == tmp_path
    assert path.name.startswith(PLACEHOLDER_PREFIX)
    assert (path / ".git").is_dir()
    # The marker must never show up as untracked.
    (path / RENAME_MARKER).write_text("chosen\n", encoding="utf-8")
    out = subprocess.run(["git", "-C", str(path), "status", "--porcelain"],
                         capture_output=True, text=True).stdout
    assert out.strip() == ""


def test_create_blank_repo_missing_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_blank_repo(str(tmp_path / "nope"))


def test_create_blank_repo_twice_same_second(tmp_path):
    a = create_blank_repo(str(tmp_path))
    b = create_blank_repo(str(tmp_path))
    assert a != b


def placeholder(tmp_path, name="new-project-1", marker=None) -> RepoInfo:
    d = tmp_path / name
    d.mkdir()
    if marker is not None:
        (d / RENAME_MARKER).write_text(marker, encoding="utf-8")
    return RepoInfo(path=str(d), label=name)


def test_rename_applies_marker(tmp_path):
    repo = placeholder(tmp_path, marker="tray-gen\n")
    renamed, problems = apply_pending_renames([repo])
    assert problems == []
    assert renamed == [(str(tmp_path / "new-project-1"), str(tmp_path / "tray-gen"))]
    assert repo.path == str(tmp_path / "tray-gen") and repo.label == "tray-gen"
    assert not (tmp_path / "tray-gen" / RENAME_MARKER).exists()


def test_rename_without_marker_is_untouched(tmp_path):
    repo = placeholder(tmp_path)
    assert apply_pending_renames([repo]) == ([], [])
    assert repo.label == "new-project-1"


def test_rename_refuses_existing_target(tmp_path):
    (tmp_path / "taken").mkdir()
    repo = placeholder(tmp_path, marker="taken")
    renamed, problems = apply_pending_renames([repo])
    assert renamed == [] and "already exists" in problems[0]


def test_rename_refuses_escaping_name(tmp_path):
    repo = placeholder(tmp_path, marker="../outside")
    assert pending_rename(repo.path) is None
    renamed, problems = apply_pending_renames([repo])
    assert renamed == [] and "invalid" in problems[0]


def test_rename_locked_folder_is_reported(tmp_path, monkeypatch):
    repo = placeholder(tmp_path, marker="tray-gen")

    def locked(self, target):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "rename", locked)
    renamed, problems = apply_pending_renames([repo])
    assert renamed == [] and "close its Claude window" in problems[0]
    assert repo.label == "new-project-1"


# --- the New Project button, end to end ---

def test_new_project_button(tmp_path, monkeypatch):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from src.config.settings import Settings
    from src.gui import git_status_panel as gsp

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = Settings(repos=[], github_dir=str(tmp_path))
    monkeypatch.setattr(settings, "save", lambda: None)
    panel = gsp.GitStatusPanel(settings)
    spawned = []
    monkeypatch.setattr(panel, "_spawn_now", lambda *a: spawned.append(a))
    monkeypatch.setattr(panel, "scan_all", lambda: None)
    monkeypatch.setattr(gsp.QInputDialog, "getText",
                        lambda *a, **k: ("a tray app & CLI", True))

    panel._on_new_project()

    assert len(settings.repos) == 1
    repo = settings.repos[0]
    assert repo.label.startswith(PLACEHOLDER_PREFIX) and Path(repo.path).is_dir()
    title, cwd, cmd, mode, label = spawned[0]
    assert cwd == repo.path and label == repo.label
    assert cmd.startswith('claude --permission-mode acceptEdits "')
    assert "a tray app and CLI" in cmd
    panel.deleteLater()


def test_new_project_cancel_creates_nothing(tmp_path, monkeypatch):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from src.config.settings import Settings
    from src.gui import git_status_panel as gsp

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = Settings(repos=[], github_dir=str(tmp_path))
    panel = gsp.GitStatusPanel(settings)
    monkeypatch.setattr(gsp.QInputDialog, "getText", lambda *a, **k: ("", False))
    panel._on_new_project()
    assert settings.repos == [] and list(tmp_path.iterdir()) == []
    panel.deleteLater()

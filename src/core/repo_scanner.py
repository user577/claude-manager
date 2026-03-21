import subprocess
from dataclasses import dataclass

from PySide6.QtCore import Signal, QThread

from src.config.settings import RepoInfo


@dataclass
class RepoStatus:
    path: str
    label: str
    branch: str = "?"
    dirty: bool = False
    modified_count: int = 0
    untracked_count: int = 0
    ahead: int = 0
    behind: int = 0
    stash_count: int = 0
    diverged: bool = False
    has_remote: bool = False
    last_commit: str = ""
    error: str | None = None


def scan_one(repo: RepoInfo) -> RepoStatus:
    status = RepoStatus(path=repo.path, label=repo.label)
    try:
        # Branch
        r = subprocess.run(
            ["git", "-C", repo.path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        status.branch = r.stdout.strip() or "HEAD"

        # Porcelain status
        r = subprocess.run(
            ["git", "-C", repo.path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        status.modified_count = sum(1 for l in lines if not l.startswith("??"))
        status.untracked_count = sum(1 for l in lines if l.startswith("??"))
        status.dirty = len(lines) > 0

        # Ahead/behind
        r = subprocess.run(
            ["git", "-C", repo.path, "rev-list", "--left-right", "--count", "@{u}...HEAD"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            parts = r.stdout.strip().split()
            if len(parts) == 2:
                status.behind = int(parts[0])
                status.ahead = int(parts[1])
            status.has_remote = True
        else:
            status.has_remote = False

        # Stash count
        r = subprocess.run(
            ["git", "-C", repo.path, "stash", "list"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            status.stash_count = len([l for l in r.stdout.splitlines() if l.strip()])

        # Divergence detection (both ahead AND behind = diverged)
        if status.ahead > 0 and status.behind > 0:
            status.diverged = True

        # Last commit
        r = subprocess.run(
            ["git", "-C", repo.path, "log", "-1", "--format=%h %s"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        status.last_commit = r.stdout.strip()

    except Exception as e:
        status.error = str(e)

    return status


class RepoScannerThread(QThread):
    status_updated = Signal(object)
    scan_complete = Signal()

    def __init__(self, repos: list[RepoInfo], parent=None):
        super().__init__(parent)
        self.repos = repos

    def run(self):
        for repo in self.repos:
            result = scan_one(repo)
            self.status_updated.emit(result)
        self.scan_complete.emit()

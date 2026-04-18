import json
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
    last_commit_date: str = ""  # ISO 8601 for sorting
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

        # Fetch remote tracking refs so ahead/behind is current
        subprocess.run(
            ["git", "-C", repo.path, "fetch", "--quiet"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

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

        # Last commit date (ISO 8601 for sorting)
        r = subprocess.run(
            ["git", "-C", repo.path, "log", "-1", "--format=%aI"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        status.last_commit_date = r.stdout.strip()

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


@dataclass
class RemoteRepo:
    name: str
    clone_url: str
    description: str
    is_private: bool


class GitHubSyncThread(QThread):
    """Queries GitHub for all repos owned by the authenticated user and
    compares against locally cloned repos."""
    finished = Signal(list, list)  # (missing: list[RemoteRepo], error: list[str])

    def __init__(self, local_names: set[str], parent=None):
        super().__init__(parent)
        self.local_names = local_names

    def run(self):
        try:
            r = subprocess.run(
                ["gh", "repo", "list", "--limit", "200", "--json",
                 "name,url,description,isPrivate"],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode != 0:
                self.finished.emit([], [f"gh repo list failed: {r.stderr.strip()}"])
                return

            repos = json.loads(r.stdout)
            missing = []
            for repo in repos:
                if repo["name"] not in self.local_names:
                    missing.append(RemoteRepo(
                        name=repo["name"],
                        clone_url=repo["url"],
                        description=repo.get("description") or "",
                        is_private=repo.get("isPrivate", False),
                    ))
            self.finished.emit(missing, [])
        except Exception as e:
            self.finished.emit([], [str(e)])

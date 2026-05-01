import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _git(repo_path: str, *args: str, timeout: int = 5) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def scan_one(repo: RepoInfo, fetch: bool = False) -> RepoStatus:
    status = RepoStatus(path=repo.path, label=repo.label)
    try:
        if fetch:
            _git(repo.path, "fetch", "--quiet", timeout=15)

        # One call: branch + upstream + ahead/behind + modified/untracked counts
        r = _git(repo.path, "status", "--porcelain=v2", "--branch", timeout=10)
        modified = 0
        untracked = 0
        for line in r.stdout.splitlines():
            if line.startswith("# branch.head "):
                status.branch = line[len("# branch.head "):].strip() or "HEAD"
            elif line.startswith("# branch.upstream "):
                status.has_remote = True
            elif line.startswith("# branch.ab "):
                # format: "# branch.ab +<ahead> -<behind>"
                parts = line.split()
                if len(parts) >= 4:
                    status.ahead = int(parts[2].lstrip("+") or 0)
                    status.behind = int(parts[3].lstrip("-") or 0)
            elif line.startswith("?"):
                untracked += 1
            elif line and not line.startswith("#"):
                modified += 1
        status.modified_count = modified
        status.untracked_count = untracked
        status.dirty = (modified + untracked) > 0
        status.diverged = status.ahead > 0 and status.behind > 0

        # One call: last commit hash + subject + ISO date (separated by US char)
        r = _git(repo.path, "log", "-1", "--format=%h %s%x1f%aI")
        out = r.stdout.strip()
        if "\x1f" in out:
            commit, date = out.split("\x1f", 1)
            status.last_commit = commit
            status.last_commit_date = date
        else:
            status.last_commit = out

        r = _git(repo.path, "stash", "list")
        if r.returncode == 0:
            status.stash_count = len([l for l in r.stdout.splitlines() if l.strip()])

    except Exception as e:
        status.error = str(e)

    return status


class RepoScannerThread(QThread):
    status_updated = Signal(object)
    scan_complete = Signal()

    def __init__(self, repos: list[RepoInfo], fetch: bool = False,
                 max_workers: int = 8, parent=None):
        super().__init__(parent)
        self.repos = repos
        self.fetch = fetch
        # Cap workers at repo count; fetch is network-bound so use more workers
        self.max_workers = min(max_workers, max(1, len(repos)))

    def run(self):
        if not self.repos:
            self.scan_complete.emit()
            return
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(scan_one, repo, self.fetch): repo
                for repo in self.repos
            }
            for future in as_completed(futures):
                repo = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = RepoStatus(path=repo.path, label=repo.label, error=str(e))
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

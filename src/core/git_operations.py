import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.constants import PYC_SKIP_DIRS
from src.core.logger import log


def pyc_cleanup(repo_path: str) -> int:
    """Recursively delete all __pycache__ dirs and .pyc files. Returns count removed."""
    root = Path(repo_path)
    removed = 0

    # Remove __pycache__ directories
    for pycache in list(root.rglob("__pycache__")):
        # Skip if any parent is in the skip list
        if any(part in PYC_SKIP_DIRS for part in pycache.parts):
            continue
        try:
            shutil.rmtree(pycache)
            removed += 1
        except OSError:
            pass

    # Remove stray .pyc files
    for pyc in list(root.rglob("*.pyc")):
        if any(part in PYC_SKIP_DIRS for part in pyc.parts):
            continue
        try:
            pyc.unlink()
            removed += 1
        except OSError:
            pass

    return removed


def _run_git(repo_path: str, *args, timeout: int = 30) -> tuple[bool, str]:
    cmd = ["git", "-C", repo_path, *args]
    log.debug("git %s", " ".join(args))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            log.warning("git %s failed (rc=%d): %s", args[0], r.returncode, output[:200])
        return r.returncode == 0, output
    except subprocess.TimeoutExpired:
        log.error("git %s timed out after %ds", args[0], timeout)
        return False, "Timed out"
    except Exception as e:
        log.error("git %s error: %s", args[0], e)
        return False, str(e)


def commit_repo(repo_path: str, message: str) -> tuple[bool, str]:
    # 1. Clean .pyc first
    cleaned = pyc_cleanup(repo_path)
    log = f"Cleaned {cleaned} __pycache__/.pyc items\n" if cleaned else ""

    # 2. Stage everything
    ok, out = _run_git(repo_path, "add", "-A")
    if not ok:
        return False, log + f"Stage failed: {out}"

    # 3. Check if there's anything to commit
    ok, out = _run_git(repo_path, "status", "--porcelain")
    if ok and not out.strip():
        return True, log + "Nothing to commit (clean)"

    # 4. Commit
    ok, out = _run_git(repo_path, "commit", "-m", message)
    return ok, log + out


def push_repo(repo_path: str) -> tuple[bool, str]:
    return _run_git(repo_path, "push", timeout=60)


def fetch_repo(repo_path: str) -> tuple[bool, str]:
    return _run_git(repo_path, "fetch", "--all", "--prune", timeout=60)


def pull_repo(repo_path: str) -> tuple[bool, str]:
    return _run_git(repo_path, "pull", "--ff-only", timeout=60)


def fetch_and_pull_repo(repo_path: str) -> tuple[bool, str]:
    ok_f, out_f = fetch_repo(repo_path)
    if not ok_f:
        return False, f"Fetch failed: {out_f}"
    ok_p, out_p = pull_repo(repo_path)
    combined = f"Fetch: {out_f}\nPull: {out_p}"
    return ok_p, combined


class GitWorker(QThread):
    """Runs a git operation on multiple repos sequentially."""
    repo_done = Signal(str, str, bool, str)  # path, operation, success, output
    all_done = Signal()

    def __init__(self, operation: str, repos: list, message: str = "", parent=None):
        super().__init__(parent)
        self.operation = operation
        self.repos = repos  # list of RepoInfo or paths
        self.message = message
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for repo in self.repos:
            if self._cancelled:
                break
            path = repo.path if hasattr(repo, "path") else str(repo)
            label = repo.label if hasattr(repo, "label") else Path(path).name

            if self.operation == "commit":
                ok, out = commit_repo(path, self.message)
            elif self.operation == "push":
                ok, out = push_repo(path)
            elif self.operation == "fetch_pull":
                ok, out = fetch_and_pull_repo(path)
            else:
                ok, out = False, f"Unknown operation: {self.operation}"

            self.repo_done.emit(label, self.operation, ok, out)
        self.all_done.emit()

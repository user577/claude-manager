"""Count today's commits the user authored across the workspace repos.

Feeds the toolbar's daily commit meter. "Today" is local midnight; "the user"
is each repo's configured ``git config user.email`` so pulled/fetched commits
from other people are excluded.

We count only each repo's remote **default branch** (``origin/HEAD``), which
mirrors GitHub's contribution rules: GitHub greens a commit once it lands on
the default branch, not while it sits on an unpushed or unmerged feature
branch. Counting ``--all`` diverged sharply from the user's GitHub profile
(local/feature-branch work inflated the total), so we track the pushed default
branch instead.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal

# subprocess.CREATE_NO_WINDOW is Windows-only; keep the app from flashing a
# console window per git call.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# A repo's configured author email rarely changes within a session; cache it so
# repeated recounts (every commit + the periodic poll) don't re-shell for it.
_email_cache: dict[str, str] = {}

# The default-branch ref also rarely changes within a session; cache it too.
_default_ref_cache: dict[str, str] = {}


def _author_email(repo_path: str) -> str:
    if repo_path in _email_cache:
        return _email_cache[repo_path]
    email = ""
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "config", "user.email"],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        email = r.stdout.strip()
    except Exception:
        email = ""
    _email_cache[repo_path] = email
    return email


def _default_ref(repo_path: str) -> str:
    """The ref to count: the remote default branch.

    Prefers ``origin/HEAD`` (the branch a fresh clone checks out). Falls back
    to ``origin/main``/``origin/master`` when ``HEAD`` isn't set on the remote,
    then to local ``HEAD`` for repos without an ``origin`` at all. Empty string
    only if none resolve. Cached per repo.
    """
    if repo_path in _default_ref_cache:
        return _default_ref_cache[repo_path]
    ref = ""
    for candidate in ("origin/HEAD", "origin/main", "origin/master", "HEAD"):
        try:
            r = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "--verify",
                 "--quiet", candidate],
                capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW,
            )
            if r.returncode == 0 and r.stdout.strip():
                ref = candidate
                break
        except (OSError, subprocess.SubprocessError):
            pass
    _default_ref_cache[repo_path] = ref
    return ref


def _repo_commits_today(repo_path: str) -> int:
    """Commits authored today on the repo's default branch. 0 on error."""
    ref = _default_ref(repo_path)
    if not ref:
        return 0
    args = ["git", "-C", repo_path, "rev-list", "--count",
            "--since=midnight", ref]
    email = _author_email(repo_path)
    if email:
        # Keep the count to this identity's work (pulled commits from others on
        # the default branch are excluded).
        args.append(f"--author={email}")
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            return int(r.stdout.strip() or 0)
    except (ValueError, OSError, subprocess.SubprocessError):
        pass
    return 0


def count_commits_today(repo_paths: list[str]) -> int:
    """Sum today's authored commits across the given repos."""
    return sum(_repo_commits_today(p) for p in repo_paths)


class CommitCountWorker(QThread):
    """Counts commits off the UI thread and emits the total.

    Iterates repos itself (rather than calling :func:`count_commits_today`) so
    a shutdown ``cancel()`` can break out between repos — that keeps the
    close-time ``wait()`` short even across a large workspace.
    """

    result = Signal(int)

    def __init__(self, repo_paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = list(repo_paths)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        paths = self._paths
        if not paths:
            self.result.emit(0)
            return
        # Counting is I/O-bound (a git subprocess per repo), so fan out across
        # a small pool — a large workspace counts in ~1s instead of serially.
        ex = ThreadPoolExecutor(max_workers=min(16, len(paths)))
        try:
            futures = [ex.submit(_repo_commits_today, p) for p in paths]
            total = 0
            for fut in as_completed(futures):
                if self._cancelled:
                    return  # finally shuts the pool down without waiting
                try:
                    total += fut.result()
                except Exception:
                    pass
            if not self._cancelled:
                self.result.emit(total)
        finally:
            # wait=False so a shutdown cancel returns promptly; already-running
            # git calls are fast and finish on their own.
            ex.shutdown(wait=False, cancel_futures=True)

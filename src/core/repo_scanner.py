import json
import os
import re
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlsplit

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
    # Remote branch ahead/behind was measured against when the branch has no
    # upstream configured (e.g. pushed with `git push origin main`, no -u).
    # Empty when a real upstream exists or there's nothing to compare with.
    inferred_upstream: str = ""
    # Why the fetch before this scan failed. Kept apart from `error` so a dead
    # remote doesn't paint over an otherwise good local scan.
    fetch_error: str | None = None
    last_commit: str = ""
    # Committer time as a Unix timestamp, for sorting. Not an ISO string: those
    # carry the commit's own UTC offset (-05:00, -06:00, +02:00, Z), so they
    # don't compare correctly as text. Committer, not author, time so a rebase
    # or a pulled fork commit counts as recent activity.
    last_commit_ts: int = 0
    # Newest mtime among uncommitted changes (modified, staged, untracked), so
    # today's unsaved-to-git work counts as recent. 0 when the tree is clean.
    last_worktree_ts: int = 0
    error: str | None = None

    @property
    def last_activity_ts(self) -> int:
        """Latest of the last commit and any uncommitted change. Sort key."""
        return max(self.last_commit_ts, self.last_worktree_ts)


# Porcelain v2 entry lines carry a fixed number of space-separated fields
# before the path: 8 for ordinary changes ("1"), 9 for renames/copies ("2",
# whose path is followed by a tab and the original path), 10 for unmerged
# ("u"), and 1 for untracked ("?").
_PATH_FIELD = {"1": 8, "2": 9, "u": 10, "?": 1}


def porcelain_v2_path(line: str) -> str | None:
    """The worktree path of a porcelain v2 entry line, or None for headers."""
    skip = _PATH_FIELD.get(line[:1])
    if skip is None:
        return None
    parts = line.split(" ", skip)
    if len(parts) <= skip:
        return None
    path = parts[skip]
    if line[0] == "2":
        path = path.split("\t", 1)[0]
    return path


def newest_mtime(repo_path: str, rel_paths: list[str]) -> int:
    """Newest mtime among `rel_paths`, ignoring ones that can't be stat'd.

    Deleted files have nothing to stat, and paths git had to C-quote (odd
    characters) won't resolve as written — both are skipped rather than
    guessed at. An untracked directory reports its own mtime, which moves
    when entries are added or removed directly inside it.
    """
    newest = 0
    for rel in rel_paths:
        try:
            newest = max(newest, int(os.stat(os.path.join(repo_path, rel)).st_mtime))
        except OSError:
            continue
    return newest


def newest_first(repos: list[RepoInfo],
                 known: dict[str, RepoStatus]) -> list[RepoInfo]:
    """`repos` ordered most recently active first, for the scan queue.

    The pool takes work in submission order, so this is the order cards come
    back in: the repos in use now update first, the dormant ones last. Each
    repo's age is the newer of its last scan's activity and its HEAD reflog's
    mtime — a cheap stat that moves on commit, checkout, pull and reset, so
    work done since the last scan (or a first scan, with nothing known yet)
    still ranks right. Ties keep their existing order.
    """
    def recency(repo: RepoInfo) -> int:
        status = known.get(repo.path)
        ts = status.last_activity_ts if status else 0
        try:
            ts = max(ts, int(os.stat(
                os.path.join(repo.path, ".git", "logs", "HEAD")).st_mtime))
        except OSError:  # no reflog yet, or .git is a worktree/submodule file
            pass
        return ts
    return sorted(repos, key=recency, reverse=True)


def _git(repo_path: str, *args: str, timeout: int = 5) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def inferred_upstream(repo_path: str, branch: str) -> str | None:
    """The remote-tracking ref a branch with no upstream would track, if any.

    `git status` only reports ahead/behind against a configured upstream, so
    a branch pushed without -u reads as in sync forever. This finds the ref it
    almost certainly means: <remote>/<branch>, where remote is origin, or the
    only remote when there's no origin. None if detached or never pushed.
    """
    if not branch or branch in ("HEAD", "(detached)", "?"):
        return None
    r = _git(repo_path, "remote")
    remotes = r.stdout.split() if r.returncode == 0 else []
    if "origin" in remotes:
        remote = "origin"
    elif len(remotes) == 1:
        remote = remotes[0]
    else:
        return None
    ref = f"{remote}/{branch}"
    r = _git(repo_path, "rev-parse", "--verify", "--quiet", f"refs/remotes/{ref}")
    return ref if r.returncode == 0 else None


def _fetch(repo_path: str, timeout: int) -> str | None:
    """Fetch the default remote; the first line of the failure, else None."""
    try:
        r = _git(repo_path, "fetch", "--quiet", timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"fetch timed out after {timeout}s"
    except Exception as e:
        return str(e)
    if r.returncode != 0:
        return (r.stderr.strip() or "fetch failed").splitlines()[0]
    return None


def scan_one(repo: RepoInfo, fetch: bool = False) -> RepoStatus:
    status = RepoStatus(path=repo.path, label=repo.label)
    try:
        if fetch:
            status.fetch_error = _fetch(repo.path, timeout=15)

        # One call: branch + upstream + ahead/behind + modified/untracked counts
        r = _git(repo.path, "status", "--porcelain=v2", "--branch", timeout=10)
        modified = 0
        untracked = 0
        changed_paths = []
        for line in r.stdout.splitlines():
            path = porcelain_v2_path(line)
            if path:
                changed_paths.append(path)
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
        if not status.has_remote:
            ref = inferred_upstream(repo.path, status.branch)
            if ref:
                r = _git(repo.path, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
                counts = r.stdout.split()
                if r.returncode == 0 and len(counts) == 2:
                    status.ahead, status.behind = int(counts[0]), int(counts[1])
                    status.has_remote = True
                    status.inferred_upstream = ref
        status.diverged = status.ahead > 0 and status.behind > 0
        status.last_worktree_ts = newest_mtime(repo.path, changed_paths)

        # One call: last commit hash + subject + committer timestamp (separated by US char)
        r = _git(repo.path, "log", "-1", "--format=%h %s%x1f%ct")
        out = r.stdout.strip()
        if "\x1f" in out:
            commit, ts = out.rsplit("\x1f", 1)
            status.last_commit = commit
            status.last_commit_ts = int(ts) if ts.isdigit() else 0
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


_DEFAULT_PORTS = {"https": 443, "http": 80, "ssh": 22, "git": 9418}
# scp-like "user@host:path". A single-letter host is a Windows drive (C:/x).
_SCP_RE = re.compile(r"^(?:[^@/]+@)?([^:/]{2,}):(?!//)")


def remote_endpoint(url: str) -> tuple[str, int, str] | None:
    """(host, port, scheme) to probe for a remote URL; None for local paths."""
    url = url.strip()
    if "://" in url:
        parts = urlsplit(url)
        port = _DEFAULT_PORTS.get(parts.scheme)
        if not parts.hostname or port is None:
            return None  # file://, or a scheme we don't know how to probe
        try:
            return parts.hostname, parts.port or port, parts.scheme
        except ValueError:  # malformed port
            return None
    m = _SCP_RE.match(url)
    return (m.group(1), 22, "ssh") if m else None


def probe_remote(host: str, port: int, scheme: str,
                 timeout: float = 1.5) -> bool | None:
    """Quick reachability check. True/False, or None when it can't tell.

    An SSH host that doesn't resolve may be a ~/.ssh/config alias that only
    ssh itself understands, so that case is "unknown" and the caller falls
    back to the real fetch instead of declaring the machine offline.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except socket.gaierror:
        return None if scheme == "ssh" else False
    except OSError:
        return False


class _ProbeCache:
    """Probe each host once per batch, however many repos share it."""

    def __init__(self, probe=probe_remote):
        self._probe = probe
        self._lock = threading.Lock()
        self._events: dict[tuple, threading.Event] = {}
        self._results: dict[tuple, bool | None] = {}

    def __call__(self, host: str, port: int, scheme: str) -> bool | None:
        key = (host, port, scheme)
        with self._lock:
            event = self._events.get(key)
            owner = event is None
            if owner:
                event = self._events[key] = threading.Event()
        if owner:
            try:
                self._results[key] = self._probe(host, port, scheme)
            finally:
                event.set()
        else:
            event.wait()
        return self._results.get(key)


def verify_remote_sync(repo: RepoInfo, timeout: int = 15,
                       probe=probe_remote) -> RepoStatus:
    """Fetch the repo's remotes, then rescan, for a pre-launch sync check.

    Unlike scan_one(fetch=True), a failed or timed-out fetch is recorded in
    status.error rather than masked: the gate must not report "in sync" off
    stale remote-tracking refs when it never actually reached the remote.

    A fast TCP probe of the remote host runs first, so being offline costs
    ~1.5s instead of the full fetch timeout.
    """
    fetch_error = None
    endpoint = None
    try:
        # Default remote's URL (branch upstream, else origin); no network.
        r = _git(repo.path, "ls-remote", "--get-url")
        if r.returncode == 0:
            endpoint = remote_endpoint(r.stdout)
    except Exception:
        pass
    if endpoint and probe(*endpoint) is False:
        fetch_error = f"offline — couldn't reach {endpoint[0]}"
    else:
        fetch_error = _fetch(repo.path, timeout)
    status = scan_one(repo, fetch=False)
    status.fetch_error = fetch_error
    if fetch_error and not status.error:
        status.error = fetch_error
    if fetch_error and not status.error:
        status.error = fetch_error
    return status


@dataclass
class SyncReport:
    """Pre-launch classification of freshly fetched repo statuses."""
    behind: list[RepoStatus]     # strictly behind: a ff-only pull can fix it
    diverged: list[RepoStatus]   # ahead and behind: needs a manual merge/rebase
    unchecked: list[RepoStatus]  # fetch or scan failed, state unknown

    @property
    def needs_prompt(self) -> bool:
        return bool(self.behind or self.diverged)


def classify_sync(statuses: list[RepoStatus]) -> SyncReport:
    """Sort statuses into the buckets the launch gate acts on.

    Pure so it can be tested without git or a QApplication. A repo whose
    fetch failed still lands in behind/diverged if its cached refs say so —
    that's stale but not wrong — and is also listed as unchecked.
    """
    behind, diverged, unchecked = [], [], []
    for s in statuses:
        if s.error:
            unchecked.append(s)
        if s.diverged:
            diverged.append(s)
        elif s.behind > 0:
            behind.append(s)
    return SyncReport(behind, diverged, unchecked)


class SyncCheckThread(QThread):
    """Runs verify_remote_sync over a batch of repos in parallel."""
    checked = Signal(list)  # list[RepoStatus], in input order

    def __init__(self, repos: list[RepoInfo], parent=None):
        super().__init__(parent)
        self.repos = repos

    def run(self):
        workers = min(16, max(1, len(self.repos)))
        probe = _ProbeCache()

        def safe_check(repo: RepoInfo) -> RepoStatus:
            try:
                return verify_remote_sync(repo, probe=probe)
            except Exception as e:
                return RepoStatus(path=repo.path, label=repo.label, error=str(e))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(safe_check, self.repos))
        self.checked.emit(results)


@dataclass
class RemoteRepo:
    name: str
    clone_url: str
    description: str
    is_private: bool


# One JSON object per line, in the same shape `gh repo list --json` gives.
_COLLAB_JQ = (
    ".[] | {name, url: .html_url, description, isPrivate: .private}"
)


def collaborator_repos_cmd() -> list[str]:
    """`gh` argv listing repos the user collaborates on but doesn't own.

    `gh repo list` only covers repos the account owns, so this goes to the REST
    endpoint with ``affiliation=collaborator`` and pages through all results.
    """
    return [
        "gh", "api", "--paginate",
        "user/repos?affiliation=collaborator&per_page=100",
        "--jq", _COLLAB_JQ,
    ]


def parse_collaborator_repos(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


class GitHubSyncThread(QThread):
    """Queries GitHub for the authenticated user's repos — owned ones, or with
    ``collaborator=True`` the ones shared with them — and compares against
    locally cloned repos."""
    finished = Signal(list, list)  # (missing: list[RemoteRepo], error: list[str])

    def __init__(self, local_names: set[str], collaborator: bool = False,
                 parent=None):
        super().__init__(parent)
        self.local_names = local_names
        self.collaborator = collaborator

    def run(self):
        try:
            if self.collaborator:
                cmd = collaborator_repos_cmd()
            else:
                cmd = ["gh", "repo", "list", "--limit", "200", "--json",
                       "name,url,description,isPrivate"]
            r = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode != 0:
                self.finished.emit([], [f"{' '.join(cmd[:3])} failed: {r.stderr.strip()}"])
                return

            if self.collaborator:
                repos = parse_collaborator_repos(r.stdout)
            else:
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

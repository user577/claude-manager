import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.constants import CONFIG_DIR, CONFIG_FILE, DEFAULT_GITHUB_DIR

# Marker username for the un-reconciled legacy/default bucket — i.e. an account
# whose gh username is not yet known. Reconciled into the active gh account by
# Settings.sync_accounts() once the gh CLI has been queried.
LEGACY_USERNAME = ""

# Appended to a username to key that account's "shared with me" workspace —
# the repos it collaborates on but doesn't own. Owned workspaces key on the
# bare username, so configs written before shared workspaces still resolve.
SHARED_SUFFIX = "#shared"

# Default folder for a shared workspace, inside the owning account's folder so
# folder-scoped git config (includeIf identity, safe.directory) still applies.
SHARED_SUBFOLDER = "shared"


def _norm(path: str) -> str:
    """Absolute path normalised for comparison.

    Stored paths mix separators and case (``D:/Users/...`` in a folder field,
    ``D:\\Users\\...`` in the repo paths written beside it), so compare only
    after ``normcase`` + ``normpath``.
    """
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _is_under(path: str, folder: str) -> bool:
    """True when ``path`` sits inside ``folder``.

    ``folder`` itself is not a match — it's the container, not one of the
    repos it holds.
    """
    if not folder:
        return False
    p, f = _norm(path), _norm(folder)
    return p != f and p.startswith(f + os.sep)


def root_commit(path: str) -> str:
    """The repo's root commit hash, or "" if it has none (or isn't readable).

    Survives a folder rename, so it is how a repo whose folder vanished is
    recognised under its new name. A history with several roots (merged
    unrelated histories) is keyed on the lowest hash so the answer is stable.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", path, "rev-list", "--max-parents=0", "HEAD"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    roots = proc.stdout.split() if proc.returncode == 0 else []
    return min(roots) if roots else ""


@dataclass
class RepoInfo:
    path: str
    label: str
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    # Root commit, remembered while the folder exists so a rename made
    # outside the app can be matched back to this entry. "" until known.
    root: str = ""

    def exists(self) -> bool:
        return Path(self.path).is_dir()


@dataclass
class RepoSync:
    """What ``GitHubAccount.sync_repos`` changed."""
    added: int = 0
    foreign: list[RepoInfo] = field(default_factory=list)
    missing: list[RepoInfo] = field(default_factory=list)
    moved: list[tuple[str, str]] = field(default_factory=list)
    # A root commit was recorded: nothing visible changed, but save anyway.
    learned: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.foreign or self.missing or self.moved
                    or self.learned)


@dataclass
class GitHubAccount:
    """A GitHub account paired with its own discrete repo folder.

    `username` is the gh CLI account name (LEGACY_USERNAME == "" while still
    unassigned). `folder` is the single directory scanned for this account's
    repos. `repos` is that account's registered repos with their tags/state.
    """
    username: str
    folder: str = ""
    repos: list[RepoInfo] = field(default_factory=list)
    # The account's second workspace: repos owned by someone else that this
    # account collaborates on. Same gh identity, its own folder, keyed apart
    # from the owned workspace by `key`.
    shared: bool = False

    @property
    def key(self) -> str:
        """Unique id for this workspace; what `Settings.active_account` holds."""
        return self.username + SHARED_SUFFIX if self.shared else self.username

    @property
    def display_name(self) -> str:
        name = self.username or "(default)"
        return f"{name} · shared" if self.shared else name

    @classmethod
    def from_dict(cls, d: dict) -> "GitHubAccount":
        return cls(
            username=d.get("username", ""),
            folder=d.get("folder", ""),
            repos=[RepoInfo(**r) for r in d.get("repos", [])],
            shared=d.get("shared", False),
        )

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "folder": self.folder,
            "repos": [asdict(r) for r in self.repos],
            "shared": self.shared,
        }

    def owns(self, path: str) -> bool:
        """True when ``path`` belongs to this account's folder."""
        return _is_under(path, self.folder)

    def discover_repos(self) -> int:
        """Scan this account's folder for git repos. Returns count added."""
        return len(self._discover())

    def _discover(self) -> list[RepoInfo]:
        if not self.folder:
            return []
        folder = Path(self.folder)
        if not folder.is_dir():
            return []
        known = {_norm(r.path) for r in self.repos}
        added: list[RepoInfo] = []
        for child in sorted(folder.iterdir()):
            if child.is_dir() and (child / ".git").exists():
                p = str(child)
                if _norm(p) not in known:
                    repo = RepoInfo(path=p, label=child.name)
                    self.repos.append(repo)
                    added.append(repo)
                    known.add(_norm(p))
        return added

    def prune_foreign_repos(self) -> list[RepoInfo]:
        """Drop repos that live outside this account's folder.

        The folder is the single source of truth for what an account shows, so
        anything outside it is another account's work. Entries like these
        survive from before the per-account split, or from an "Add Folder..."
        pointed at the wrong drive.

        A folder-less account is left alone: there is nothing to scope against,
        and pruning would silently empty its list. So is an account whose
        folder isn't currently reachable — an unplugged drive or an offline
        sync root must not be read as "none of these repos belong here" and
        cost the user their list.
        """
        if not self.folder or not Path(self.folder).is_dir():
            return []
        keep: list[RepoInfo] = []
        dropped: list[RepoInfo] = []
        for r in self.repos:
            (keep if self.owns(r.path) else dropped).append(r)
        self.repos = keep
        return dropped

    def sync_repos(self) -> RepoSync:
        """Scope the repo list to what is actually in this account's folder.

        Prunes anything outside the folder, discovers anything new inside it,
        and drops entries whose folder is gone. A gone entry whose root commit
        matches exactly one newly found folder was renamed outside the app
        (Explorer, or a Claude session), so it moves to the new path and keeps
        its tags instead of being dropped and rediscovered.

        Like the foreign prune, nothing is dropped while the folder itself is
        unreachable: an unplugged drive makes every repo look missing.
        """
        result = RepoSync(foreign=self.prune_foreign_repos())
        if not self.folder or not Path(self.folder).is_dir():
            return result

        missing = [r for r in self.repos if not r.exists()]
        new = self._discover()
        result.added = len(new)

        # Learn roots while the folders exist, so they are already known if
        # one disappears later. A repo with no commits yet stays "" and is
        # retried next time; everything else is looked up once.
        unknown = [r for r in self.repos if not r.root and r.exists()]
        if unknown:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for repo, root in zip(unknown,
                                      pool.map(root_commit,
                                               [r.path for r in unknown])):
                    repo.root = root
            result.learned = any(r.root for r in unknown)
        if not missing:
            return result

        moved_into: set[int] = set()
        for gone in missing:
            if not gone.root:
                continue
            same = [r for r in new if r.root == gone.root]
            if len(same) != 1 or [m.root for m in missing].count(gone.root) != 1:
                continue  # ambiguous (e.g. two clones of one upstream)
            target = same[0]
            result.moved.append((gone.path, target.path))
            gone.path, gone.label = target.path, target.label
            moved_into.add(id(target))

        result.added -= len(moved_into)
        result.missing = [r for r in missing if not r.exists()]
        self.repos = [r for r in self.repos
                      if id(r) not in moved_into and r.exists()]
        return result


@dataclass(init=False)
class Settings:
    accounts: list[GitHubAccount]
    active_account: str
    layout: str
    instance_count: int
    permission_mode: str
    model: str
    backend: str
    local_model: str
    initial_prompt: str
    use_worktree: bool
    session_mode: str
    repo_sort: str
    commit_goal: int
    window_x: int
    window_y: int
    window_width: int
    window_height: int

    def __init__(
        self,
        *,
        accounts: list[GitHubAccount] | None = None,
        active_account: str | None = None,
        # Legacy / convenience kwargs — fold a single folder + repos into one
        # account when no explicit `accounts` list is supplied.
        repos: list[RepoInfo] | None = None,
        github_dir: str | None = None,
        layout: str = "grid_2x2",
        instance_count: int = 4,
        permission_mode: str = "default",
        model: str = "default",
        backend: str = "cloud",
        local_model: str = "",
        initial_prompt: str = "",
        use_worktree: bool = False,
        session_mode: str = "new",
        repo_sort: str = "name",
        commit_goal: int = 15,
        window_x: int = 200,
        window_y: int = 200,
        window_width: int = 520,
        window_height: int = 720,
    ):
        if accounts is None:
            folder = github_dir if github_dir is not None else str(DEFAULT_GITHUB_DIR)
            accounts = [GitHubAccount(
                username=LEGACY_USERNAME, folder=folder, repos=repos or [],
            )]
            if active_account is None:
                active_account = LEGACY_USERNAME
        if not accounts:
            accounts = [GitHubAccount(
                username=LEGACY_USERNAME, folder=str(DEFAULT_GITHUB_DIR),
            )]
        if active_account is None:
            active_account = accounts[0].key

        self.accounts = accounts
        self.active_account = active_account
        self.layout = layout
        self.instance_count = instance_count
        self.permission_mode = permission_mode
        self.model = model
        self.backend = backend
        self.local_model = local_model
        self.initial_prompt = initial_prompt
        self.use_worktree = use_worktree
        self.session_mode = session_mode
        self.repo_sort = repo_sort
        self.commit_goal = commit_goal
        self.window_x = window_x
        self.window_y = window_y
        self.window_width = window_width
        self.window_height = window_height

    # --- Active-account proxies ----------------------------------------------
    # `repos` and `github_dir` proxy to the active account so the rest of the
    # app (git panel, launcher, cloning, workers) keeps using a single repo set.

    def active(self) -> GitHubAccount | None:
        if not self.accounts:
            return None
        for a in self.accounts:
            if a.key == self.active_account:
                return a
        return self.accounts[0]

    def find(self, key: str) -> GitHubAccount | None:
        return next((a for a in self.accounts if a.key == key), None)

    @property
    def repos(self) -> list[RepoInfo]:
        a = self.active()
        return a.repos if a else []

    @property
    def github_dir(self) -> str:
        a = self.active()
        return a.folder if a else str(DEFAULT_GITHUB_DIR)

    @github_dir.setter
    def github_dir(self, value: str):
        a = self.active()
        if a is not None:
            a.folder = value

    # --- Persistence ----------------------------------------------------------

    @classmethod
    def load(cls) -> "Settings":
        if not CONFIG_FILE.exists():
            s = cls()
            s.discover_repos()
            s.save()
            return s
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if "accounts" in data:
                accounts = [GitHubAccount.from_dict(a) for a in data["accounts"]]
                active_account = data.get("active_account", "")
            else:
                # Migrate a legacy single-folder config into one account whose
                # gh username is filled in later by sync_accounts().
                legacy_repos = [RepoInfo(**r) for r in data.get("repos", [])]
                accounts = [GitHubAccount(
                    username=LEGACY_USERNAME,
                    folder=data.get("github_dir", str(DEFAULT_GITHUB_DIR)),
                    repos=legacy_repos,
                )]
                active_account = LEGACY_USERNAME
            s = cls(
                accounts=accounts,
                active_account=active_account,
                layout=data.get("layout", "grid_2x2"),
                instance_count=data.get("instance_count", 4),
                permission_mode=data.get("permission_mode", "default"),
                model=data.get("model", "default"),
                backend=data.get("backend", "cloud"),
                local_model=data.get("local_model", ""),
                initial_prompt=data.get("initial_prompt", ""),
                use_worktree=data.get("use_worktree", False),
                session_mode=data.get("session_mode", "new"),
                repo_sort=data.get("repo_sort", "name"),
                commit_goal=data.get("commit_goal", 15),
                window_x=data.get("window_x", 200),
                window_y=data.get("window_y", 200),
                window_width=data.get("window_width", 520),
                window_height=data.get("window_height", 720),
            )
            # A config written before per-account folders existed can hold
            # repos from another account's drive. Scope every account to its
            # own folder on load so a switch never shows a foreign repo.
            if s.prune_all_accounts():
                s.save()
            return s
        except Exception:
            return cls()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "accounts": [a.to_dict() for a in self.accounts],
            "active_account": self.active_account,
            "layout": self.layout,
            "instance_count": self.instance_count,
            "permission_mode": self.permission_mode,
            "model": self.model,
            "backend": self.backend,
            "local_model": self.local_model,
            "initial_prompt": self.initial_prompt,
            "use_worktree": self.use_worktree,
            "session_mode": self.session_mode,
            "repo_sort": self.repo_sort,
            "commit_goal": self.commit_goal,
            "window_x": self.window_x,
            "window_y": self.window_y,
            "window_width": self.window_width,
            "window_height": self.window_height,
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # --- Account reconciliation ----------------------------------------------

    def sync_accounts(self, usernames: list[str], active: str | None) -> bool:
        """Reconcile stored accounts with the gh-known accounts.

        - Adopts the legacy/unassigned bucket into the active gh account so an
          upgraded config keeps its folder + repos.
        - Auto-creates a (folder-less) row for each gh account not yet tracked.
        - Keeps `active_account` aligned with the active gh account.

        Returns True if anything changed (caller should save()).
        """
        changed = False

        # 1. Adopt the legacy bucket into the active gh account.
        legacy = self.find(LEGACY_USERNAME)
        if legacy is not None and active:
            existing = self.find(active)
            if existing is None:
                legacy.username = active
            else:
                if not existing.folder and legacy.folder:
                    existing.folder = legacy.folder
                    existing.repos = legacy.repos
                self.accounts.remove(legacy)
            if self.active_account == LEGACY_USERNAME:
                self.active_account = active
            changed = True

        # 2. Auto-add an owned and a shared row for each gh account we don't
        #    track yet (the shared row also back-fills configs that predate it).
        have = {a.key for a in self.accounts}
        for u in usernames:
            if not u:
                continue
            for acct in (GitHubAccount(username=u),
                         GitHubAccount(username=u, shared=True)):
                if acct.key not in have:
                    self.accounts.append(acct)
                    have.add(acct.key)
                    changed = True

        # 3. Default each empty shared folder to a subfolder of its owner's.
        for a in self.accounts:
            if a.shared and not a.folder:
                owner = self.find(a.username)
                if owner is not None and owner.folder:
                    a.folder = str(Path(owner.folder) / SHARED_SUBFOLDER)
                    changed = True

        # 4. Keep active_account aligned with the active gh account. Either of
        #    that user's workspaces counts as aligned — both use its identity.
        current = self.find(self.active_account)
        if active and self.find(active) is not None:
            if current is None or current.username != active:
                self.active_account = active
                changed = True
        elif current is None and self.accounts:
            self.active_account = self.accounts[0].key
            changed = True

        return changed

    # --- Active-account helpers ----------------------------------------------

    def discover_repos(self):
        a = self.active()
        if a is not None:
            a.discover_repos()

    def sync_repos(self) -> RepoSync:
        """Scope the active account's repos to its folder."""
        a = self.active()
        return a.sync_repos() if a is not None else RepoSync()

    def prune_all_accounts(self) -> dict[str, list[RepoInfo]]:
        """Scope *every* account's repo list to its own folder.

        Returns ``{key: dropped}`` for the accounts that actually changed,
        so the caller can report the cleanup and save.
        """
        dropped: dict[str, list[RepoInfo]] = {}
        for a in self.accounts:
            gone = a.prune_foreign_repos()
            if gone:
                dropped[a.key] = gone
        return dropped

    def get_all_tags(self) -> list[str]:
        tags: set[str] = set()
        for r in self.repos:
            tags.update(r.tags)
        return sorted(tags)

    def get_enabled_repos(self) -> list[RepoInfo]:
        return [r for r in self.repos if r.enabled and r.exists()]

    def get_branch(self, repo: RepoInfo) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", repo.path, "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return result.stdout.strip() or "HEAD"
        except Exception:
            return "?"

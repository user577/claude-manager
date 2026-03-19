import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.constants import CONFIG_DIR, CONFIG_FILE, DEFAULT_GITHUB_DIR


@dataclass
class RepoInfo:
    path: str
    label: str
    enabled: bool = True
    tags: list[str] = field(default_factory=list)

    def exists(self) -> bool:
        return Path(self.path).is_dir()


@dataclass
class Settings:
    repos: list[RepoInfo] = field(default_factory=list)
    layout: str = "grid_2x2"
    instance_count: int = 4
    permission_mode: str = "default"
    model: str = "default"
    initial_prompt: str = ""
    use_worktree: bool = False
    session_mode: str = "new"
    github_dir: str = str(DEFAULT_GITHUB_DIR)
    window_x: int = 200
    window_y: int = 200
    window_width: int = 520
    window_height: int = 720

    @classmethod
    def load(cls) -> "Settings":
        if not CONFIG_FILE.exists():
            s = cls()
            s.discover_repos()
            s.save()
            return s
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            repos = [RepoInfo(**r) for r in data.get("repos", [])]
            s = cls(
                repos=repos,
                layout=data.get("layout", "grid_2x2"),
                instance_count=data.get("instance_count", 4),
                permission_mode=data.get("permission_mode", "default"),
                model=data.get("model", "default"),
                initial_prompt=data.get("initial_prompt", ""),
                use_worktree=data.get("use_worktree", False),
                session_mode=data.get("session_mode", "new"),
                github_dir=data.get("github_dir", str(DEFAULT_GITHUB_DIR)),
                window_x=data.get("window_x", 200),
                window_y=data.get("window_y", 200),
                window_width=data.get("window_width", 520),
                window_height=data.get("window_height", 720),
            )
            return s
        except Exception:
            return cls()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "repos": [asdict(r) for r in self.repos],
            "layout": self.layout,
            "instance_count": self.instance_count,
            "permission_mode": self.permission_mode,
            "model": self.model,
            "initial_prompt": self.initial_prompt,
            "use_worktree": self.use_worktree,
            "session_mode": self.session_mode,
            "github_dir": self.github_dir,
            "window_x": self.window_x,
            "window_y": self.window_y,
            "window_width": self.window_width,
            "window_height": self.window_height,
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def discover_repos(self):
        github_dir = Path(self.github_dir)
        if not github_dir.is_dir():
            return
        known_paths = {r.path for r in self.repos}
        for child in sorted(github_dir.iterdir()):
            if child.is_dir() and (child / ".git").exists():
                path_str = str(child)
                if path_str not in known_paths:
                    label = child.name
                    self.repos.append(RepoInfo(path=path_str, label=label))

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
            )
            return result.stdout.strip() or "HEAD"
        except Exception:
            return "?"

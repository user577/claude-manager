import os
import subprocess
import time
import uuid

from PySide6.QtCore import QThread, Signal

from src.config.settings import RepoInfo
from src.core.window_manager import (
    get_work_area, compute_layout, find_windows_by_title, tile_windows,
)


_ollama_model_cache: list[str] | None = None


def get_ollama_models(force_refresh: bool = False) -> list[str]:
    """Query ollama for available models. Cached until force_refresh."""
    global _ollama_model_cache
    if _ollama_model_cache is not None and not force_refresh:
        return _ollama_model_cache

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            _ollama_model_cache = []
            return []
        models = []
        for line in result.stdout.strip().splitlines()[1:]:  # skip header
            parts = line.split()
            if parts:
                models.append(parts[0])  # model name is first column
        _ollama_model_cache = models
        return models
    except Exception:
        _ollama_model_cache = []
        return []


def get_ollama_status() -> dict:
    """Check ollama health. Returns {"running": bool, "version": str, "models": list}."""
    info: dict = {"running": False, "version": "", "models": []}
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            info["version"] = result.stdout.strip()
    except Exception:
        return info

    # Check if the server is actually responding
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/version", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                import json
                data = json.loads(resp.read())
                info["running"] = True
                info["version"] = data.get("version", info["version"])
    except Exception:
        # ollama installed but server not running
        return info

    info["models"] = get_ollama_models(force_refresh=True)
    return info


def _make_title(label: str, uid: str) -> str:
    return f"Claude-{label}-{uid}"


class LaunchWorker(QThread):
    """Launch Claude instances in Windows Terminal and tile them."""
    status = Signal(str)  # progress messages
    finished_ok = Signal()
    finished_err = Signal(str)

    def __init__(self, repos: list[RepoInfo], layout: str, count: int,
                 permission_mode: str = "default",
                 model: str = "default",
                 backend: str = "cloud",
                 local_model: str = "",
                 initial_prompt: str = "",
                 use_worktree: bool = False,
                 session_mode: str = "new",
                 parent=None):
        super().__init__(parent)
        self.repos = repos[:count]
        self.layout = layout
        self.count = min(count, len(repos))
        self.permission_mode = permission_mode
        self.model = model
        self.backend = backend
        self.local_model = local_model
        self.initial_prompt = initial_prompt
        self.use_worktree = use_worktree
        self.session_mode = session_mode

    def run(self):
        if self.count == 0:
            self.finished_err.emit("No repos selected")
            return

        uid = uuid.uuid4().hex[:8]
        titles = []

        # Launch each instance
        for i, repo in enumerate(self.repos):
            title = _make_title(repo.label, uid)
            titles.append(title)
            claude_cmd = "claude"
            if self.permission_mode == "bypassPermissions":
                claude_cmd += " --dangerously-skip-permissions"
            elif self.permission_mode != "default":
                claude_cmd += f" --permission-mode {self.permission_mode}"

            if self.backend == "local" and self.local_model:
                # Local ollama — model flag uses the ollama model name
                claude_cmd += f" --model {self.local_model}"
            elif self.model != "default":
                claude_cmd += f" --model {self.model}"

            if self.use_worktree:
                claude_cmd += " --worktree"

            if self.session_mode == "continue":
                claude_cmd += " --continue"
            elif self.session_mode == "named":
                claude_cmd += f" --name {repo.label}"

            if self.initial_prompt.strip():
                escaped = self.initial_prompt.replace('"', '\\"')
                claude_cmd += f' "{escaped}"'

            # Build the shell command — prepend env vars for local backend
            if self.backend == "local":
                shell_cmd = (
                    f"set ANTHROPIC_BASE_URL=http://localhost:11434"
                    f" && set ANTHROPIC_API_KEY=ollama"
                    f" && {claude_cmd}"
                )
            else:
                shell_cmd = claude_cmd

            cmd = [
                "wt.exe", "--window", "new",
                "--title", title,
                "-d", repo.path,
                "cmd.exe", "/k", shell_cmd,
            ]
            try:
                subprocess.Popen(cmd)
                backend_label = f" [local:{self.local_model}]" if self.backend == "local" else ""
                self.status.emit(f"Launched [{i+1}/{self.count}] {repo.label}{backend_label}")
            except Exception as e:
                self.finished_err.emit(f"Failed to launch {repo.label}: {e}")
                return
            time.sleep(0.8)

        # Wait for windows to render
        self.status.emit("Waiting for windows to appear...")
        time.sleep(2.5)

        # Find and tile windows
        work = get_work_area()
        positions = compute_layout(work, self.layout, self.count)

        hwnds = []
        for title in titles:
            found = find_windows_by_title(title)
            if found:
                hwnds.append(found[0])
            else:
                self.status.emit(f"Warning: could not find window '{title}'")

        if hwnds:
            tile_windows(hwnds, positions[:len(hwnds)])
            self.status.emit(f"Tiled {len(hwnds)} windows ({self.layout})")

        self.finished_ok.emit()

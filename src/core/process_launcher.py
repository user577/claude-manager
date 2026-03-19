import subprocess
import time
import uuid

from PySide6.QtCore import QThread, Signal

from src.config.settings import RepoInfo
from src.core.window_manager import (
    get_work_area, compute_layout, find_windows_by_title, tile_windows,
)


def _make_title(label: str, uid: str) -> str:
    return f"Claude-{label}-{uid}"


class LaunchWorker(QThread):
    """Launch Claude instances in Windows Terminal and tile them."""
    status = Signal(str)  # progress messages
    finished_ok = Signal()
    finished_err = Signal(str)

    def __init__(self, repos: list[RepoInfo], layout: str, count: int, parent=None):
        super().__init__(parent)
        self.repos = repos[:count]
        self.layout = layout
        self.count = min(count, len(repos))

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
            cmd = [
                "wt.exe", "--window", "new",
                "--title", title,
                "-d", repo.path,
                "cmd.exe", "/k", "claude",
            ]
            try:
                subprocess.Popen(cmd)
                self.status.emit(f"Launched [{i+1}/{self.count}] {repo.label}")
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

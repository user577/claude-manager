import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout,
)

from src.config.settings import RepoInfo


def _get_diff_stat(repo_path: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "diff", "--stat", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        # Also include untracked files count
        r2 = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        untracked = sum(1 for l in r2.stdout.splitlines() if l.startswith("??"))
        stat = r.stdout.strip()
        if untracked:
            stat += f"\n  + {untracked} untracked file(s)"
        return stat or "  (staged changes only)"
    except Exception:
        return "  (could not read diff)"


class CommitConfirmDialog(QDialog):
    def __init__(self, repos: list[RepoInfo], message: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Commit")
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)

        # Commit message
        msg_label = QLabel(f"Commit message: <b>{message}</b>")
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)

        layout.addWidget(QLabel(f"Changes in {len(repos)} repo(s):"))

        # Diff stats per repo
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12px;"
        )
        layout.addWidget(self.detail)

        # Build diff summary
        lines = []
        for repo in repos:
            lines.append(f"--- {repo.label} ---")
            lines.append(_get_diff_stat(repo.path))
            lines.append("")
        self.detail.setPlainText("\n".join(lines))

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("Commit All")
        ok_btn.setObjectName("commitBtn")
        ok_btn.setStyleSheet(
            "QPushButton { background: #a6e3a1; color: #1e1e2e; border: none; "
            "font-weight: bold; padding: 8px 20px; border-radius: 6px; }"
            "QPushButton:hover { background: #c6f0c2; }"
        )
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

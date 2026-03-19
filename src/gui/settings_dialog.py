from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QFileDialog,
)

from src.config.settings import Settings, RepoInfo


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumSize(450, 400)

        layout = QVBoxLayout(self)

        # --- GitHub directory ---
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("GitHub directory:"))
        self.dir_edit = QLineEdit(self.settings.github_dir)
        dir_row.addWidget(self.dir_edit, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        # --- Repo list ---
        layout.addWidget(QLabel("Registered Repositories:"))
        self.repo_list = QListWidget()
        for repo in self.settings.repos:
            self.repo_list.addItem(f"{repo.label}  —  {repo.path}")
        layout.addWidget(self.repo_list)

        # --- Repo buttons ---
        btn_row = QHBoxLayout()

        add_btn = QPushButton("Add Folder...")
        add_btn.clicked.connect(self._add_folder)
        btn_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)

        discover_btn = QPushButton("Auto-Discover")
        discover_btn.clicked.connect(self._discover)
        btn_row.addWidget(discover_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # --- Tag editor ---
        tag_row = QHBoxLayout()
        tag_row.addWidget(QLabel("Tags:"))
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("Tags (comma-separated)...")
        self.tag_edit.setEnabled(False)
        tag_row.addWidget(self.tag_edit, 1)
        layout.addLayout(tag_row)

        self.repo_list.currentRowChanged.connect(self._on_repo_selected)
        self.tag_edit.editingFinished.connect(self._on_tags_changed)

        # --- OK / Cancel ---
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom_row.addWidget(ok_btn)
        bottom_row.addWidget(cancel_btn)
        layout.addLayout(bottom_row)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select GitHub Directory", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Git Repository", self.settings.github_dir)
        if d:
            from pathlib import Path
            p = Path(d)
            if (p / ".git").exists():
                repo = RepoInfo(path=str(p), label=p.name)
                self.settings.repos.append(repo)
                self.repo_list.addItem(f"{repo.label}  —  {repo.path}")
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Not a Git Repo",
                                    f"{d} does not contain a .git directory.")

    def _remove_selected(self):
        row = self.repo_list.currentRow()
        if row >= 0:
            self.repo_list.takeItem(row)
            del self.settings.repos[row]

    def _discover(self):
        self.settings.github_dir = self.dir_edit.text()
        old_count = len(self.settings.repos)
        self.settings.discover_repos()
        # Refresh list
        self.repo_list.clear()
        for repo in self.settings.repos:
            self.repo_list.addItem(f"{repo.label}  —  {repo.path}")
        added = len(self.settings.repos) - old_count
        if added > 0:
            self.setWindowTitle(f"Settings — discovered {added} new repos")

    def _on_repo_selected(self, row: int):
        if row < 0 or row >= len(self.settings.repos):
            self.tag_edit.clear()
            self.tag_edit.setEnabled(False)
            return
        self.tag_edit.setEnabled(True)
        repo = self.settings.repos[row]
        self.tag_edit.setText(", ".join(repo.tags))

    def _on_tags_changed(self):
        row = self.repo_list.currentRow()
        if row < 0 or row >= len(self.settings.repos):
            return
        raw = self.tag_edit.text()
        tags = sorted(set(
            t.strip().lower() for t in raw.split(",") if t.strip()
        ))
        self.settings.repos[row].tags = tags
        # Normalize display
        self.tag_edit.setText(", ".join(tags))

    def get_github_dir(self) -> str:
        return self.dir_edit.text()

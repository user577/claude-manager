from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QFileDialog, QMessageBox, QFrame, QSpinBox,
)

from src.config.settings import Settings, RepoInfo


class SettingsDialog(QDialog):
    """Per-account folder mapping + repo/tag management for the active account.

    Each GitHub account gets its own discrete folder. The repo list below the
    folder rows is scoped to the currently active account.
    """

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 480)

        layout = QVBoxLayout(self)

        # --- Per-account folders -------------------------------------------
        layout.addWidget(QLabel("Account folders (one folder per GitHub account):"))
        self.folder_edits: dict[str, QLineEdit] = {}
        if self.settings.accounts:
            for acct in self.settings.accounts:
                row = QHBoxLayout()
                name = acct.username or "(default)"
                lbl = QLabel(name)
                lbl.setMinimumWidth(130)
                lbl.setStyleSheet("font-weight: bold;")
                row.addWidget(lbl)
                edit = QLineEdit(acct.folder)
                edit.setPlaceholderText("(no folder set)")
                row.addWidget(edit, 1)
                browse = QPushButton("Browse")
                browse.clicked.connect(
                    lambda _checked=False, u=acct.username: self._browse_account(u)
                )
                row.addWidget(browse)
                self.folder_edits[acct.username] = edit
                layout.addLayout(row)
        else:
            hint = QLabel("No GitHub accounts detected. Run `gh auth login` first.")
            hint.setStyleSheet("color: #f4be47;")
            layout.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #474747;")
        layout.addWidget(sep)

        # --- Active-account repo list --------------------------------------
        active = self.settings.active()
        active_name = (active.username or "(default)") if active else "(none)"
        layout.addWidget(QLabel(f"Repositories for {active_name}:"))
        self.repo_list = QListWidget()
        self._reload_repo_list()
        layout.addWidget(self.repo_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Folder...")
        add_btn.clicked.connect(self._add_folder)
        btn_row.addWidget(add_btn)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)
        discover_btn = QPushButton("Auto-Discover")
        discover_btn.setToolTip("Scan this account's folder for git repos")
        discover_btn.clicked.connect(self._discover)
        btn_row.addWidget(discover_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # --- Tag editor -----------------------------------------------------
        tag_row = QHBoxLayout()
        tag_row.addWidget(QLabel("Tags:"))
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("Tags (comma-separated)...")
        self.tag_edit.setEnabled(False)
        tag_row.addWidget(self.tag_edit, 1)
        layout.addLayout(tag_row)

        self.repo_list.currentRowChanged.connect(self._on_repo_selected)
        self.tag_edit.editingFinished.connect(self._on_tags_changed)

        # --- Daily commit goal ---------------------------------------------
        goal_row = QHBoxLayout()
        goal_row.addWidget(QLabel("Daily commit goal:"))
        self.goal_spin = QSpinBox()
        self.goal_spin.setRange(1, 999)
        self.goal_spin.setValue(self.settings.commit_goal)
        self.goal_spin.setToolTip(
            "Toolbar commit meter turns green at/above this count, red below."
        )
        goal_row.addWidget(self.goal_spin)
        goal_row.addStretch()
        layout.addLayout(goal_row)

        # --- OK / Cancel ----------------------------------------------------
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom_row.addWidget(ok_btn)
        bottom_row.addWidget(cancel_btn)
        layout.addLayout(bottom_row)

    # --- Folder rows --------------------------------------------------------

    def _browse_account(self, username: str):
        edit = self.folder_edits.get(username)
        if edit is None:
            return
        start = edit.text() or str(Path.home())
        name = username or "default"
        d = QFileDialog.getExistingDirectory(self, f"Folder for {name}", start)
        if d:
            edit.setText(d)
            # If this is the active account, adopt the folder immediately so
            # Auto-Discover and the repo list reflect the new choice.
            active = self.settings.active()
            if active is not None and active.username == username:
                active.folder = d

    def apply(self):
        """Write folder edits back into their accounts. Called on OK."""
        for username, edit in self.folder_edits.items():
            for acct in self.settings.accounts:
                if acct.username == username:
                    acct.folder = edit.text().strip()
                    break
        self.settings.commit_goal = self.goal_spin.value()

    # --- Repo list (scoped to active account) -------------------------------

    def _reload_repo_list(self):
        self.repo_list.clear()
        for repo in self.settings.repos:
            self.repo_list.addItem(f"{repo.label}  —  {repo.path}")

    def _add_folder(self):
        active = self.settings.active()
        if active is None:
            return
        start = active.folder or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "Select Git Repository", start)
        if not d:
            return
        p = Path(d)
        if not (p / ".git").exists():
            QMessageBox.warning(
                self, "Not a Git Repo",
                f"{d} does not contain a .git directory.",
            )
            return
        # An account only ever shows repos from its own folder, so adding one
        # from elsewhere would just be pruned again on the next scan.
        if active.folder and not active.owns(str(p)):
            QMessageBox.warning(
                self, "Outside This Account's Folder",
                f"{d}\n\nis not inside {active.folder}.\n\n"
                f"Each account only shows repos from its own folder. Add this "
                f"repo under that folder, or switch to the account that owns it.",
            )
            return
        active.repos.append(RepoInfo(path=str(p), label=p.name))
        self._reload_repo_list()

    def _remove_selected(self):
        row = self.repo_list.currentRow()
        active = self.settings.active()
        if active is not None and 0 <= row < len(active.repos):
            del active.repos[row]
            self.repo_list.takeItem(row)

    def _discover(self):
        active = self.settings.active()
        if active is None:
            return
        # Adopt the (possibly just-edited) folder before scanning.
        edit = self.folder_edits.get(active.username)
        if edit is not None:
            active.folder = edit.text().strip()
        added, removed = active.sync_repos()
        self._reload_repo_list()
        if not active.folder:
            self.setWindowTitle("Settings — set a folder first")
        elif added or removed:
            bits = []
            if added:
                bits.append(f"discovered {added}")
            if removed:
                bits.append(f"dropped {removed} outside the folder")
            self.setWindowTitle(f"Settings — {', '.join(bits)}")

    def _on_repo_selected(self, row: int):
        repos = self.settings.repos
        if row < 0 or row >= len(repos):
            self.tag_edit.clear()
            self.tag_edit.setEnabled(False)
            return
        self.tag_edit.setEnabled(True)
        self.tag_edit.setText(", ".join(repos[row].tags))

    def _on_tags_changed(self):
        row = self.repo_list.currentRow()
        repos = self.settings.repos
        if row < 0 or row >= len(repos):
            return
        raw = self.tag_edit.text()
        tags = sorted(set(
            t.strip().lower() for t in raw.split(",") if t.strip()
        ))
        repos[row].tags = tags
        self.tag_edit.setText(", ".join(tags))

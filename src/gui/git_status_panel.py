from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QFrame, QProgressBar,
)

from src.config.settings import Settings
from src.core.repo_scanner import RepoScannerThread, RepoStatus
from src.core.git_operations import GitWorker
from src.gui.widgets.repo_status_card import RepoStatusCard
from src.gui.widgets.log_output import LogOutput
from src.gui.commit_confirm_dialog import CommitConfirmDialog


class GitStatusPanel(QWidget):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._scanner = None
        self._git_worker = None
        self._statuses: dict[str, RepoStatus] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Status dashboard ---
        top_row = QHBoxLayout()
        header = QLabel("Repository Status")
        header.setObjectName("sectionHeader")
        top_row.addWidget(header)
        top_row.addStretch()

        self.scan_label = QLabel("")
        self.scan_label.setStyleSheet("color: #585b70; font-size: 11px;")
        top_row.addWidget(self.scan_label)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.scan_all)
        top_row.addWidget(self.refresh_btn)
        layout.addLayout(top_row)

        # --- Search filter ---
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter repos...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)
        layout.addWidget(self.search_box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(260)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(2)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.cards_container)
        layout.addWidget(scroll)

        self.cards: dict[str, RepoStatusCard] = {}

        # --- Quick-select buttons ---
        select_row = QHBoxLayout()
        dirty_btn = QPushButton("Select Dirty")
        dirty_btn.setFixedWidth(100)
        dirty_btn.clicked.connect(self._select_dirty)
        select_row.addWidget(dirty_btn)

        ahead_btn = QPushButton("Select Ahead")
        ahead_btn.setFixedWidth(100)
        ahead_btn.clicked.connect(self._select_ahead)
        select_row.addWidget(ahead_btn)

        select_row.addStretch()
        layout.addLayout(select_row)

        # --- Commit section ---
        commit_row = QHBoxLayout()
        self.commit_msg = QLineEdit()
        self.commit_msg.setPlaceholderText("Commit message for all dirty repos...")
        self.commit_msg.textChanged.connect(self._on_msg_changed)
        commit_row.addWidget(self.commit_msg, 1)

        self.commit_btn = QPushButton("Commit All Dirty")
        self.commit_btn.setObjectName("commitBtn")
        self.commit_btn.setEnabled(False)
        self.commit_btn.clicked.connect(self._on_commit)
        commit_row.addWidget(self.commit_btn)
        layout.addLayout(commit_row)

        # --- Push / Sync row ---
        action_row = QHBoxLayout()

        self.push_btn = QPushButton("Push All")
        self.push_btn.setObjectName("pushBtn")
        self.push_btn.clicked.connect(self._on_push)
        action_row.addWidget(self.push_btn)

        self.sync_btn = QPushButton("Fetch && Pull All")
        self.sync_btn.setObjectName("syncBtn")
        self.sync_btn.clicked.connect(self._on_sync)
        action_row.addWidget(self.sync_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(
            "QPushButton { background: #f38ba8; color: #1e1e2e; border: none; font-weight: bold; }"
            "QPushButton:hover { background: #f5a0b8; }"
        )
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self._on_cancel)
        action_row.addWidget(self.cancel_btn)

        action_row.addStretch()
        layout.addLayout(action_row)

        # --- Progress ---
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { background: #313244; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: #cba6f7; border-radius: 3px; }"
        )
        self.progress.hide()
        layout.addWidget(self.progress)

        # --- Log ---
        self.log = LogOutput()
        layout.addWidget(self.log)

        layout.addStretch()

        # Initial scan
        self._build_cards()

    def _build_cards(self):
        # Clear old cards
        for card in self.cards.values():
            card.setParent(None)
        self.cards.clear()

        for repo in self.settings.repos:
            card = RepoStatusCard()
            if not repo.exists():
                card.update_status(RepoStatus(
                    path=repo.path, label=repo.label, error="Path not found"))
            else:
                card.update_status(RepoStatus(path=repo.path, label=repo.label))
            self.cards[repo.path] = card
            self.cards_layout.addWidget(card)

    def scan_all(self):
        self.refresh_btn.setEnabled(False)
        self._scan_count = 0
        self._scan_total = len(self.settings.repos)
        self.scan_label.setText(f"Scanning 0/{self._scan_total}...")
        self._build_cards()
        repos = list(self.settings.repos)
        self._scanner = RepoScannerThread(repos, parent=self)
        self._scanner.status_updated.connect(self._on_status_updated)
        self._scanner.scan_complete.connect(self._on_scan_complete)
        self._scanner.start()

    def _on_status_updated(self, status: RepoStatus):
        self._scan_count += 1
        self.scan_label.setText(f"Scanning {self._scan_count}/{self._scan_total}...")
        self._statuses[status.path] = status
        if status.path in self.cards:
            self.cards[status.path].update_status(status)

    def _on_scan_complete(self):
        self.scan_label.setText("")
        self.refresh_btn.setEnabled(True)
        self._scanner = None

    def _on_search(self, text: str):
        query = text.strip().lower()
        for path, card in self.cards.items():
            repo = next((r for r in self.settings.repos if r.path == path), None)
            visible = not query or (repo and query in repo.label.lower())
            card.setVisible(visible)

    def _select_dirty(self):
        """Highlight dirty repos by scrolling log — future: multi-select cards."""
        dirty = [s.label for s in self._statuses.values() if s.dirty]
        if dirty:
            self.search_box.clear()
            self.log.log_info(f"Dirty repos ({len(dirty)}): {', '.join(dirty)}")
        else:
            self.log.log_info("All repos are clean")

    def _select_ahead(self):
        ahead = [s.label for s in self._statuses.values() if s.ahead > 0]
        if ahead:
            self.search_box.clear()
            self.log.log_info(f"Ahead repos ({len(ahead)}): {', '.join(ahead)}")
        else:
            self.log.log_info("No repos are ahead of remote")

    def _set_buttons_enabled(self, enabled: bool):
        self.commit_btn.setEnabled(enabled and bool(self.commit_msg.text().strip()))
        self.push_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.cancel_btn.setVisible(not enabled)

    def _start_operation(self, operation: str, repos, message: str = ""):
        if not repos:
            self.log.log_info(f"No repos to {operation}")
            return

        self._set_buttons_enabled(False)
        self.progress.setRange(0, len(repos))
        self.progress.setValue(0)
        self.progress.show()
        self._op_count = 0

        self._git_worker = GitWorker(operation, repos, message, parent=self)
        self._git_worker.repo_done.connect(self._on_repo_done)
        self._git_worker.all_done.connect(self._on_all_done)
        self._git_worker.start()

    def _on_repo_done(self, label: str, operation: str, success: bool, output: str):
        self._op_count += 1
        self.progress.setValue(self._op_count)
        short = output.split("\n")[0][:120] if output else ""
        if success:
            self.log.log_ok(f"[{operation}] {label}: {short}")
        else:
            self.log.log_err(f"[{operation}] {label}: {short}")

    def _on_cancel(self):
        if self._git_worker:
            self._git_worker.cancel()
            self.log.log_info("Cancelling...")

    def _on_all_done(self):
        self._set_buttons_enabled(True)
        self.progress.hide()
        self._git_worker = None
        # Re-scan to update cards
        self.scan_all()

    def _on_msg_changed(self, text: str):
        has_text = bool(text.strip())
        self.commit_btn.setEnabled(has_text)
        if has_text:
            self.commit_msg.setStyleSheet("")
        else:
            self.commit_msg.setStyleSheet("border-color: #f38ba8;")

    def _on_commit(self):
        msg = self.commit_msg.text().strip()
        if not msg:
            self.commit_msg.setStyleSheet("border-color: #f38ba8;")
            self.commit_msg.setFocus()
            return
        # Only commit dirty repos
        dirty = [r for r in self.settings.repos
                 if r.path in self._statuses and self._statuses[r.path].dirty]
        if not dirty:
            self.log.log_info("All repos are clean, nothing to commit")
            return

        # Show confirmation dialog with diff stats
        dlg = CommitConfirmDialog(dirty, msg, parent=self)
        if not dlg.exec():
            self.log.log_info("Commit cancelled")
            return

        self.log.log_info(f"Committing {len(dirty)} dirty repos...")
        self._start_operation("commit", dirty, msg)

    def _on_push(self):
        # Push repos that are ahead or just committed
        pushable = [r for r in self.settings.repos
                    if r.path in self._statuses and (
                        self._statuses[r.path].ahead > 0
                        or self._statuses[r.path].dirty
                    )]
        if not pushable:
            # Push all that have remotes
            pushable = [r for r in self.settings.repos
                        if r.path in self._statuses and self._statuses[r.path].has_remote]
        self.log.log_info(f"Pushing {len(pushable)} repos...")
        self._start_operation("push", pushable)

    def _on_sync(self):
        all_repos = [r for r in self.settings.repos if r.exists()]
        self.log.log_info(f"Fetching & pulling {len(all_repos)} repos...")
        self._start_operation("fetch_pull", all_repos)

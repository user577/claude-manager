import subprocess
import uuid

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
        self.scan_label.setStyleSheet("color: #6e6e6e; font-size: 11px;")
        top_row.addWidget(self.scan_label)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.scan_all)
        top_row.addWidget(self.refresh_btn)
        layout.addLayout(top_row)

        # --- Search filter ---
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter repos...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_filters)
        layout.addWidget(self.search_box)

        # --- Tag filter ---
        self.tag_bar_widget = QWidget()
        self.tag_bar = QHBoxLayout(self.tag_bar_widget)
        self.tag_bar.setContentsMargins(0, 0, 0, 0)
        self.tag_bar.setSpacing(4)
        self.tag_buttons: dict[str, QPushButton] = {}
        self.active_tags: set[str] = set()
        layout.addWidget(self.tag_bar_widget)
        self._refresh_tag_bar()

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
        dirty_btn.setMinimumWidth(100)
        dirty_btn.clicked.connect(self._select_dirty)
        select_row.addWidget(dirty_btn)

        ahead_btn = QPushButton("Select Ahead")
        ahead_btn.setMinimumWidth(100)
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

        self.push_btn = QPushButton("Push Ahead")
        self.push_btn.setObjectName("pushBtn")
        self.push_btn.setToolTip("Push repos that are strictly ahead (skips diverged repos)")
        self.push_btn.clicked.connect(self._on_push)
        action_row.addWidget(self.push_btn)

        self.sync_btn = QPushButton("Fetch && Pull All")
        self.sync_btn.setObjectName("syncBtn")
        self.sync_btn.setToolTip("Safe: fetch + fast-forward pull only (never overwrites remote)")
        self.sync_btn.clicked.connect(self._on_sync)
        action_row.addWidget(self.sync_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(
            "QPushButton { background: #f44747; color: #ffffff; border: none; font-weight: bold; }"
            "QPushButton:hover { background: #f66; }"
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
            "QProgressBar { background: #3c3c3c; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: #007acc; border-radius: 3px; }"
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
            card.launch_requested.connect(self._launch_single)
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

    def _refresh_tag_bar(self):
        for btn in self.tag_buttons.values():
            btn.setParent(None)
        self.tag_buttons.clear()
        while self.tag_bar.count():
            item = self.tag_bar.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        all_tags = self.settings.get_all_tags()
        if not all_tags:
            self.tag_bar_widget.hide()
            return
        self.tag_bar_widget.show()

        for tag in all_tags:
            btn = QPushButton(tag)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._tag_style(False))
            btn.clicked.connect(lambda checked, t=tag: self._toggle_tag(t))
            self.tag_bar.addWidget(btn)
            self.tag_buttons[tag] = btn

        clear_btn = QPushButton("Clear")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #6e6e6e; border: none; "
            "font-size: 11px; padding: 3px 6px; }"
            "QPushButton:hover { color: #cccccc; }"
        )
        clear_btn.clicked.connect(self._clear_tags)
        self.tag_bar.addWidget(clear_btn)
        self.tag_bar.addStretch()

    @staticmethod
    def _tag_style(active: bool) -> str:
        if active:
            return (
                "QPushButton { background: #007acc; color: #ffffff; "
                "border-radius: 10px; padding: 3px 10px; font-size: 11px; border: none; }"
                "QPushButton:hover { background: #1a8ad4; }"
            )
        return (
            "QPushButton { background: #3c3c3c; color: #cccccc; "
            "border-radius: 10px; padding: 3px 10px; font-size: 11px; border: none; }"
            "QPushButton:hover { background: #474747; }"
        )

    def _toggle_tag(self, tag: str):
        if tag in self.active_tags:
            self.active_tags.discard(tag)
        else:
            self.active_tags.add(tag)
        if tag in self.tag_buttons:
            self.tag_buttons[tag].setStyleSheet(
                self._tag_style(tag in self.active_tags)
            )
        self._apply_filters()

    def _clear_tags(self):
        self.active_tags.clear()
        for tag, btn in self.tag_buttons.items():
            btn.setStyleSheet(self._tag_style(False))
        self._apply_filters()

    def _apply_filters(self):
        query = self.search_box.text().strip().lower()
        for path, card in self.cards.items():
            repo = next((r for r in self.settings.repos if r.path == path), None)
            matches_search = not query or (repo and query in repo.label.lower())
            matches_tags = not self.active_tags or (
                repo and bool(set(repo.tags) & self.active_tags)
            )
            card.setVisible(matches_search and matches_tags)

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
            self.commit_msg.setStyleSheet("border-color: #f44747;")

    def _on_commit(self):
        msg = self.commit_msg.text().strip()
        if not msg:
            self.commit_msg.setStyleSheet("border-color: #f44747;")
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
        # Only push repos that are strictly ahead — skip diverged or behind
        pushable = []
        skipped = []
        for r in self.settings.repos:
            s = self._statuses.get(r.path)
            if not s or not s.has_remote:
                continue
            if s.diverged or s.behind > 0:
                skipped.append(r.label)
            elif s.ahead > 0:
                pushable.append(r)

        if skipped:
            self.log.log_info(f"Skipping diverged/behind: {', '.join(skipped)}")
        if not pushable:
            self.log.log_info("No repos are ahead — nothing to push")
            return

        names = ", ".join(r.label for r in pushable)
        self.log.log_info(f"Pushing {len(pushable)} repos: {names}")
        self._start_operation("push", pushable)

    def _on_sync(self):
        all_repos = [r for r in self.settings.repos if r.exists()]
        self.log.log_info(f"Fetching & pulling {len(all_repos)} repos...")
        self._start_operation("fetch_pull", all_repos)

    def _launch_single(self, repo_path: str):
        """Launch a single Claude instance scoped to the given repo."""
        repo = next((r for r in self.settings.repos if r.path == repo_path), None)
        if not repo:
            self.log.log_err(f"Repo not found: {repo_path}")
            return

        uid = uuid.uuid4().hex[:8]
        title = f"Claude-{repo.label}-{uid}"

        guardrail = (
            f"You are working in the project at {repo.path}. "
            "All new files, edits, and code generation MUST stay within this "
            "project directory. Do not create or modify files outside of it."
        )
        escaped = guardrail.replace('"', '\\"')
        claude_cmd = f'claude "{escaped}"'

        cmd = [
            "wt.exe", "--window", "new",
            "--title", title,
            "-d", repo.path,
            "cmd.exe", "/k", claude_cmd,
        ]
        try:
            subprocess.Popen(cmd)
            self.log.log_ok(f"Launched Claude in {repo.label}")
        except Exception as e:
            self.log.log_err(f"Failed to launch: {e}")

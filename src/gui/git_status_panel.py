import subprocess
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QFrame, QProgressBar, QComboBox, QMessageBox,
)

from src.config.settings import Settings, RepoInfo
from src.core.repo_scanner import RepoScannerThread, RepoStatus, GitHubSyncThread, RemoteRepo
from src.core.git_operations import GitWorker, CloneWorker
from src.core.process_launcher import LaunchWorker
from src.core.agent_ladder import ensure_ladder, SIZING_POLICY, TEAM_POLICY
from src.gui.widgets.repo_status_card import RepoStatusCard
from src.gui.widgets.log_output import LogOutput
from src.gui.commit_confirm_dialog import CommitConfirmDialog


AUTO_COMMIT_PROMPT = (
    "You are an autonomous git committer. Review all uncommitted changes in "
    "this repository and create well-formed commits, then exit. Procedure: "
    "(1) Run `git status` and `git diff HEAD` to inspect every change. "
    "(2) Group related changes into logical commits — one focused change per "
    "commit. A single commit is fine if everything is one coherent change. "
    "(3) For each group, stage only the relevant files with `git add <paths>` "
    "(never `git add -A` or `git add .`), then commit with a concise message "
    "in imperative mood (~70 char first line, why-focused if non-obvious). "
    "(4) Do NOT push. Do NOT modify any code — only commit existing changes. "
    "(5) Skip files that look sensitive (.env, credentials, keys, tokens) or "
    "unintentional (build artifacts, logs, .DS_Store) — leave them unstaged "
    "and note them. (6) When done, run `git status` to confirm, summarize "
    "what you committed in one line, and exit."
)


# Urgency ladder for the Status sort, most urgent first. First match wins, so
# order matters: behind+modified has to precede plain behind. Single source of
# truth for both _urgency_rank() and the sort dropdown's tooltip — these were
# two hand-maintained lists that had already drifted apart.
#
# "error" leads rather than trailing: an errored repo (vanished path, unreadable
# git dir) already paints the same red dot as diverged, so burying it below the
# clean repos put a red card at the bottom of an "urgent first" sort.
URGENCY_TIERS = (
    ("error", lambda s: bool(s.error)),
    ("diverged", lambda s: s.diverged),
    ("behind+modified", lambda s: s.behind > 0 and s.modified_count > 0),
    ("behind", lambda s: s.behind > 0),
    ("modified", lambda s: s.modified_count > 0),
    ("ahead", lambda s: s.ahead > 0),
    ("untracked", lambda s: s.untracked_count > 0),
    ("clean", lambda s: True),
)

# Not yet scanned is unknown, not healthy — it sorts below every scanned tier
# (including clean) so a pending scan never outranks a real result.
UNSCANNED_RANK = len(URGENCY_TIERS)

URGENCY_TOOLTIP = " → ".join(name for name, _ in URGENCY_TIERS) + " → unscanned"


def _urgency_rank(status) -> int:
    """Lower = more urgent. Pure so it can be tested without a QApplication."""
    for rank, (_, matches) in enumerate(URGENCY_TIERS):
        if matches(status):
            return rank
    return UNSCANNED_RANK


class GitStatusPanel(QWidget):
    # Emitted after a git operation finishes (commit/push/pull) so the toolbar
    # commit meter can refresh without polling.
    commits_changed = Signal()

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
        self.refresh_btn.setToolTip("Fast local rescan (uses cached fetch state)")
        self.refresh_btn.clicked.connect(self.scan_all)
        top_row.addWidget(self.refresh_btn)

        self.fetch_refresh_btn = QPushButton("Fetch")
        self.fetch_refresh_btn.setToolTip(
            "Fetch all remotes, then refresh — slower but updates ahead/behind"
        )
        self.fetch_refresh_btn.clicked.connect(lambda: self.scan_all(fetch=True))
        top_row.addWidget(self.fetch_refresh_btn)
        layout.addLayout(top_row)

        # --- Search filter + sort ---
        filter_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter repos...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_box, 1)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Name", "name")
        self.sort_combo.addItem("Recently Modified", "date")
        self.sort_combo.addItem("Status (urgent first)", "status")
        self.sort_combo.setFixedWidth(170)
        self.sort_combo.setToolTip(
            "Sort repos by name, last commit date, or status urgency\n"
            f"({URGENCY_TOOLTIP})"
        )
        # Restore saved sort preference
        saved_idx = self.sort_combo.findData(self.settings.repo_sort)
        if saved_idx >= 0:
            self.sort_combo.setCurrentIndex(saved_idx)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        filter_row.addWidget(self.sort_combo)
        layout.addLayout(filter_row)

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
        # Cards are 52px tall on a 2px-spaced layout, so the visible repo count
        # is height/54. Cap at 10 cards (was 5) and floor at 4 so a short window
        # still shows a usable list instead of collapsing to one or two rows.
        scroll.setMinimumHeight(216)
        scroll.setMaximumHeight(540)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(2)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.cards_container)
        # Stretch factor so spare vertical space grows the repo list (up to its
        # cap) rather than being absorbed by the log or the trailing stretch.
        layout.addWidget(scroll, 1)

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

        behind_btn = QPushButton("Select Behind")
        behind_btn.setMinimumWidth(100)
        behind_btn.clicked.connect(self._select_behind)
        select_row.addWidget(behind_btn)

        self.out_of_sync_btn = QPushButton("Out of Sync")
        self.out_of_sync_btn.setMinimumWidth(100)
        self.out_of_sync_btn.setCheckable(True)
        self.out_of_sync_btn.setToolTip("Show only repos that are ahead, behind, diverged, or dirty")
        self.out_of_sync_btn.clicked.connect(self._apply_filters)
        select_row.addWidget(self.out_of_sync_btn)

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

        self.auto_commit_btn = QPushButton("Auto Commit")
        self.auto_commit_btn.setToolTip(
            "Spawn a Sonnet instance per dirty repo to review changes and "
            "create commits autonomously (uses --dangerously-skip-permissions, "
            "does not push)"
        )
        self.auto_commit_btn.setStyleSheet(
            "QPushButton { background: #6e40c9; color: #ffffff; border: none; "
            "border-radius: 4px; padding: 6px 12px; font-weight: bold; }"
            "QPushButton:hover { background: #8b5cf6; }"
            "QPushButton:disabled { background: #3c3c3c; color: #6e6e6e; }"
        )
        self.auto_commit_btn.clicked.connect(self._on_auto_commit)
        commit_row.addWidget(self.auto_commit_btn)
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

        self.github_btn = QPushButton("Check GitHub")
        self.github_btn.setStyleSheet(
            "QPushButton { background: #6e40c9; color: #ffffff; border: none; font-weight: bold; }"
            "QPushButton:hover { background: #8b5cf6; }"
        )
        self.github_btn.setToolTip("Find repos on your GitHub account that aren't cloned locally")
        self.github_btn.clicked.connect(self._on_check_github)
        action_row.addWidget(self.github_btn)

        self.clone_btn = QPushButton("Clone Missing")
        self.clone_btn.setStyleSheet(
            "QPushButton { background: #6e40c9; color: #ffffff; border: none; font-weight: bold; }"
            "QPushButton:hover { background: #8b5cf6; }"
        )
        self.clone_btn.setToolTip("Clone all uncloned repos listed above")
        self.clone_btn.clicked.connect(self._on_clone_missing)
        self.clone_btn.hide()
        action_row.addWidget(self.clone_btn)

        self._pending_clones: list[RemoteRepo] = []

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
        # Floor the log so the taller repo list can't squeeze it to nothing.
        self.log.setMinimumHeight(90)
        layout.addWidget(self.log)

        layout.addStretch()

        # Initial scan
        self._build_cards()

    def _build_cards(self):
        # Clear old cards. deleteLater() (not setParent(None)) so they're
        # destroyed instead of lingering as orphaned top-level widgets — an
        # orphaned card can briefly flash as its own "Claude Manager" window.
        for card in self.cards.values():
            card.hide()
            card.deleteLater()
        self.cards.clear()

        for repo in self.settings.repos:
            # Parent to the container up front so the card is never a top-level
            # window, even for the moment before it's added to the layout.
            card = RepoStatusCard(self.cards_container)
            if not repo.exists():
                card.update_status(RepoStatus(
                    path=repo.path, label=repo.label, error="Path not found"))
            else:
                card.update_status(RepoStatus(path=repo.path, label=repo.label))
            card.launch_requested.connect(self._launch_single)
            card.launch_auto_requested.connect(self._launch_single_auto)
            card.agent_heavy_requested.connect(self._launch_agent_heavy)
            card.agent_team_requested.connect(self._launch_agent_team)
            self.cards[repo.path] = card
            self.cards_layout.addWidget(card)

    def stop_workers(self):
        """Stop any running background threads for a clean shutdown."""
        from src.core.process_launcher import stop_worker
        for attr in ("_scanner", "_git_worker", "_gh_sync",
                     "_clone_worker", "_auto_commit_worker"):
            stop_worker(getattr(self, attr, None))

    def scan_all(self, fetch: bool = False):
        self.refresh_btn.setEnabled(False)
        self.fetch_refresh_btn.setEnabled(False)
        # Pick up new folders added to github_dir since last load
        before = len(self.settings.repos)
        self.settings.discover_repos()
        added = len(self.settings.repos) - before
        if added:
            self.settings.save()
            self._refresh_tag_bar()
            self.log.log_info(f"Discovered {added} new repo(s)")
        self._scan_count = 0
        self._scan_total = len(self.settings.repos)
        prefix = "Fetching" if fetch else "Scanning"
        self.scan_label.setText(f"{prefix} 0/{self._scan_total}...")
        self._scan_prefix = prefix
        self._build_cards()
        repos = list(self.settings.repos)
        # Network-bound fetch parallelizes well; local-only scan needs fewer workers
        workers = 16 if fetch else 8
        self._scanner = RepoScannerThread(repos, fetch=fetch, max_workers=workers, parent=self)
        self._scanner.status_updated.connect(self._on_status_updated)
        self._scanner.scan_complete.connect(self._on_scan_complete)
        self._scanner.start()

    def _on_status_updated(self, status: RepoStatus):
        self._scan_count += 1
        self.scan_label.setText(
            f"{self._scan_prefix} {self._scan_count}/{self._scan_total}..."
        )
        self._statuses[status.path] = status
        if status.path in self.cards:
            self.cards[status.path].update_status(status)

    def _on_scan_complete(self):
        self.scan_label.setText("")
        self.refresh_btn.setEnabled(True)
        self.fetch_refresh_btn.setEnabled(True)
        self._scanner = None
        self._reorder_cards()

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
        filter_sync = self.out_of_sync_btn.isChecked()
        for path, card in self.cards.items():
            repo = next((r for r in self.settings.repos if r.path == path), None)
            matches_search = not query or (repo and query in repo.label.lower())
            matches_tags = not self.active_tags or (
                repo and bool(set(repo.tags) & self.active_tags)
            )
            if filter_sync:
                s = self._statuses.get(path)
                matches_sync = s is not None and (
                    s.dirty or s.ahead > 0 or s.behind > 0 or s.diverged
                )
            else:
                matches_sync = True
            card.setVisible(matches_search and matches_tags and matches_sync)

    def _on_sort_changed(self):
        self.settings.repo_sort = self.sort_combo.currentData()
        self.settings.save()
        self._reorder_cards()

    def _reorder_cards(self):
        sort_key = self.sort_combo.currentData()
        paths = list(self.cards.keys())
        if sort_key == "date":
            # Sort by last_commit_date descending; repos without dates go last
            paths.sort(
                key=lambda p: self._statuses[p].last_commit_date
                if p in self._statuses and self._statuses[p].last_commit_date
                else "",
                reverse=True,
            )
        elif sort_key == "status":
            # Sort by urgency: lower rank = more serious, alphabetical tiebreaker.
            paths.sort(key=self._seriousness)
        else:
            # Sort alphabetically by label
            paths.sort(
                key=lambda p: self._statuses[p].label.lower()
                if p in self._statuses else p.lower()
            )
        for i, path in enumerate(paths):
            card = self.cards[path]
            self.cards_layout.removeWidget(card)
            self.cards_layout.insertWidget(i, card)

    def _seriousness(self, path: str) -> tuple[int, str]:
        """Lower rank = more serious, alphabetical tiebreaker. Status sort key."""
        s = self._statuses.get(path)
        if s is None:
            return (UNSCANNED_RANK, path.lower())
        return (_urgency_rank(s), (s.label or path).lower())

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

    def _select_behind(self):
        behind = [s.label for s in self._statuses.values() if s.behind > 0]
        if behind:
            self.search_box.clear()
            self.log.log_info(f"Behind repos ({len(behind)}): {', '.join(behind)}")
        else:
            self.log.log_info("All repos are up to date with remote")

    def _set_buttons_enabled(self, enabled: bool):
        self.commit_btn.setEnabled(enabled and bool(self.commit_msg.text().strip()))
        self.auto_commit_btn.setEnabled(enabled)
        self.push_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)
        self.github_btn.setEnabled(enabled)
        self.clone_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.fetch_refresh_btn.setEnabled(enabled)
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
        self.commits_changed.emit()
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
        # Only repos with something to pull — skip clean repos that are already in sync.
        # Repos without scan data fall through (might genuinely be behind).
        pullable = []
        skipped_synced = 0
        skipped_diverged = []
        for r in self.settings.repos:
            if not r.exists():
                continue
            s = self._statuses.get(r.path)
            if s is None:
                pullable.append(r)
                continue
            if s.diverged:
                skipped_diverged.append(r.label)
                continue
            if s.behind > 0:
                pullable.append(r)
            else:
                skipped_synced += 1

        if skipped_diverged:
            self.log.log_info(
                f"Skipping diverged ({len(skipped_diverged)}): "
                f"{', '.join(skipped_diverged)}"
            )
        if skipped_synced:
            self.log.log_info(f"Skipping {skipped_synced} already-synced repo(s)")
        if not pullable:
            self.log.log_info("Nothing to fetch & pull")
            return

        self.log.log_info(f"Fetching & pulling {len(pullable)} repo(s)...")
        self._start_operation("fetch_pull", pullable)

    def _on_check_github(self):
        """Query GitHub for repos not cloned locally."""
        self.github_btn.setEnabled(False)
        self.log.log_info("Checking GitHub for uncloned repos...")

        # Collect local repo folder names
        github_dir = Path(self.settings.github_dir)
        local_names = set()
        if github_dir.is_dir():
            for child in github_dir.iterdir():
                if child.is_dir():
                    local_names.add(child.name)

        self._gh_sync = GitHubSyncThread(local_names, parent=self)
        self._gh_sync.finished.connect(self._on_github_sync_done)
        self._gh_sync.start()

    def _on_github_sync_done(self, missing: list, errors: list):
        self.github_btn.setEnabled(True)
        self._gh_sync = None

        if errors:
            for e in errors:
                self.log.log_err(e)
            return

        if not missing:
            self.log.log_ok("All GitHub repos are cloned locally")
            self._pending_clones = []
            self.clone_btn.hide()
            return

        self._pending_clones = missing
        names = ", ".join(r.name for r in missing)
        self.log.log_info(f"Uncloned ({len(missing)}): {names}")
        self.clone_btn.show()

    def _on_clone_missing(self):
        if not self._pending_clones:
            return

        github_dir = self.settings.github_dir
        clone_list = [
            (r.name, r.clone_url, str(Path(github_dir) / r.name))
            for r in self._pending_clones
        ]
        self._pending_clones = []
        self.clone_btn.hide()

        self._set_buttons_enabled(False)
        self.progress.setRange(0, len(clone_list))
        self.progress.setValue(0)
        self.progress.show()
        self._clone_count = 0

        self._clone_worker = CloneWorker(clone_list, parent=self)
        self._clone_worker.repo_done.connect(self._on_clone_repo_done)
        self._clone_worker.all_done.connect(self._on_clone_all_done)
        self._clone_worker.start()

    def _on_clone_repo_done(self, name: str, success: bool, output: str):
        self._clone_count += 1
        self.progress.setValue(self._clone_count)
        short = output.split("\n")[0][:120] if output else ""
        if success:
            self.log.log_ok(f"[clone] {name}: {short}")
            # Auto-register in settings
            dest = str(Path(self.settings.github_dir) / name)
            if not any(r.path == dest for r in self.settings.repos):
                self.settings.repos.append(RepoInfo(path=dest, label=name))
                self.settings.save()
        else:
            self.log.log_err(f"[clone] {name}: {short}")

    def _on_clone_all_done(self):
        self._set_buttons_enabled(True)
        self.progress.hide()
        self._clone_worker = None
        self._build_cards()
        self.scan_all()

    def _launch_single(self, repo_path: str):
        """Launch a single Claude instance scoped to the given repo."""
        self._launch_repo(repo_path, auto=False)

    def _launch_single_auto(self, repo_path: str):
        """Launch with --dangerously-skip-permissions for unattended use."""
        self._launch_repo(repo_path, auto=True)

    @staticmethod
    def _guardrail(repo_path: str) -> str:
        return (
            f"You are working in the project at {repo_path}. "
            "All new files, edits, and code generation MUST stay within this "
            "project directory. Do not create or modify files outside of it."
        )

    @staticmethod
    def _escape_prompt(text: str) -> str:
        """Make prompt text safe to embed in a double-quoted cmd.exe argument.
        Flattened to one line — cmd.exe /k treats embedded newlines in the
        argument as command terminators, which would truncate the prompt."""
        return " ".join(text.split()).replace('"', '\\"')

    def _spawn_claude_window(self, title: str, cwd: str, claude_cmd: str,
                             mode: str, repo_label: str):
        """Open a new Windows Terminal window running claude_cmd via cmd.exe /k.

        wt.exe splits its command line on ";" even inside quoted arguments,
        then tries to run the tail as a separate subcommand (0x80070002), so
        semicolons are escaped ("\\;") to pass through literally.
        """
        claude_cmd = claude_cmd.replace(";", "\\;")
        cmd = [
            "wt.exe", "--window", "new",
            "--title", title,
            "-d", cwd,
            "cmd.exe", "/k", claude_cmd,
        ]
        try:
            subprocess.Popen(cmd)
            self.log.log_ok(f"Launched Claude ({mode}) in {repo_label}")
        except Exception as e:
            self.log.log_err(f"Failed to launch: {e}")

    def _launch_agent_heavy(self, repo_path: str):
        """Launch an auto-scaling multi-agent session against the repo.

        Loads the Haiku->Sonnet->Opus->Fable subagent ladder via --add-dir (session-
        scoped; nothing written to the repo) and primes the orchestrator with
        the sizing policy so it delegates each task to the cheapest tier that
        fits. The per-tier models are pinned in the ladder, so routing is
        enforced rather than merely suggested in prose.
        """
        repo = next((r for r in self.settings.repos if r.path == repo_path), None)
        if not repo:
            self.log.log_err(f"Repo not found: {repo_path}")
            return

        try:
            ladder_root = ensure_ladder()
        except Exception as e:
            self.log.log_err(f"Failed to prepare agent ladder: {e}")
            return

        uid = uuid.uuid4().hex[:8]
        escaped = self._escape_prompt(self._guardrail(repo.path) + " " + SIZING_POLICY)
        # The policy rides in the system prompt rather than the first user turn
        # so it survives context compaction in long sessions, and the
        # orchestrator itself is pinned to the top tier — sizing decisions are
        # the one place a cheap default model would hurt the most.
        # Kickoff makes the mode visible and self-verifying on launch. It sits
        # BEFORE --add-dir: that flag is variadic, so a positional argument
        # directly after it is silently consumed as an extra directory.
        kickoff = (
            "Confirm Agent Heavy mode: list your six ladder subagents with "
            "their models, one line each, then wait for my task."
        )
        claude_cmd = (
            f'claude "{kickoff}" --dangerously-skip-permissions --model opus '
            f'--add-dir "{ladder_root}" --append-system-prompt "{escaped}"'
        )
        self._spawn_claude_window(
            f"Claude-{repo.label}-agents-{uid}", repo.path, claude_cmd,
            "Agent Heavy", repo.label)

    def _launch_agent_team(self, repo_path: str):
        """Launch an Agent Teams lead session against the repo.

        The parallelism-first alternative to Agent Heavy: instead of cheap
        subagent tiers inside one session, the lead spawns full parallel
        Claude sessions (teammates) that coordinate through a shared task
        list. Fastest wall-clock on big divisible work, at much higher token
        cost. The ladder is still loaded so its agent definitions can serve
        as teammate templates. Agent Teams is experimental, gated behind
        CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS.
        """
        repo = next((r for r in self.settings.repos if r.path == repo_path), None)
        if not repo:
            self.log.log_err(f"Repo not found: {repo_path}")
            return

        try:
            ladder_root = ensure_ladder()
        except Exception as e:
            self.log.log_err(f"Failed to prepare agent ladder: {e}")
            return

        uid = uuid.uuid4().hex[:8]
        escaped = self._escape_prompt(self._guardrail(repo.path) + " " + TEAM_POLICY)
        # The experimental gate is set inside the launched shell (not via
        # Popen env) because wt.exe may hand the tab off to an existing
        # terminal broker process, which would drop inherited environment.
        # Kickoff before --add-dir for the same variadic-consumption reason as
        # in _launch_agent_heavy.
        kickoff = (
            "Confirm Agent Team mode: state whether teammate spawning (Agent "
            "Teams) is available in this session and list the ladder agent "
            "definitions usable as teammate templates, then wait for my task."
        )
        claude_cmd = (
            f'set CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1&& '
            f'claude "{kickoff}" --dangerously-skip-permissions --model opus '
            f'--add-dir "{ladder_root}" --append-system-prompt "{escaped}"'
        )
        self._spawn_claude_window(
            f"Claude-{repo.label}-team-{uid}", repo.path, claude_cmd,
            "Agent Team", repo.label)

    def _launch_repo(self, repo_path: str, auto: bool):
        repo = next((r for r in self.settings.repos if r.path == repo_path), None)
        if not repo:
            self.log.log_err(f"Repo not found: {repo_path}")
            return

        uid = uuid.uuid4().hex[:8]
        escaped = self._escape_prompt(self._guardrail(repo.path))
        flags = " --dangerously-skip-permissions" if auto else ""
        claude_cmd = f'claude{flags} "{escaped}"'
        self._spawn_claude_window(
            f"Claude-{repo.label}-{uid}", repo.path, claude_cmd,
            "Auto" if auto else "standard", repo.label)

    def _on_auto_commit(self):
        dirty = [r for r in self.settings.repos
                 if r.path in self._statuses and self._statuses[r.path].dirty]
        if not dirty:
            self.log.log_info("All repos are clean, nothing to auto-commit")
            return

        names = "\n".join(f"  • {r.label}" for r in dirty)
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Auto Commit")
        confirm.setIcon(QMessageBox.Question)
        confirm.setText(
            f"Spawn {len(dirty)} Sonnet instance(s) to auto-commit dirty repos?"
        )
        confirm.setInformativeText(
            f"Each window runs Claude with --dangerously-skip-permissions and "
            f"is told to review changes and create commits (no push).\n\n{names}"
        )
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        confirm.setDefaultButton(QMessageBox.Cancel)
        if confirm.exec() != QMessageBox.Yes:
            self.log.log_info("Auto commit cancelled")
            return

        # Pick a layout that fits the count
        count = len(dirty)
        if count <= 4:
            layout_key = "grid_2x2"
        elif count <= 8:
            layout_key = "vertical"
        else:
            layout_key = "single"

        self.log.log_info(f"Auto-committing {count} repo(s) via Sonnet...")
        self._auto_commit_worker = LaunchWorker(
            repos=dirty,
            layout=layout_key,
            count=count,
            permission_mode="bypassPermissions",
            model="sonnet",
            backend="cloud",
            initial_prompt=AUTO_COMMIT_PROMPT,
            use_worktree=False,
            session_mode="new",
            parent=self,
        )
        self._auto_commit_worker.status.connect(self.log.log_info)
        self._auto_commit_worker.finished_ok.connect(
            lambda: self.log.log_ok("Auto commit instances launched")
        )
        self._auto_commit_worker.finished_err.connect(self.log.log_err)
        self._auto_commit_worker.start()

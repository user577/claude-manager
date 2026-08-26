import time

from PySide6.QtCore import Qt, QSize, QTimer, QEvent
from PySide6.QtGui import QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QPushButton, QWidget, QLabel,
    QMessageBox,
)

from src.constants import APP_DISPLAY_NAME, ICON_PATH
from src.config.settings import Settings
from src.core.process_launcher import OllamaHealthWorker
from src.gui.git_status_panel import GitStatusPanel
from src.gui.project_panel import ProjectPanel
from src.gui.settings_dialog import SettingsDialog
from src.gui.styles import DARK_THEME


class MainWindow(QMainWindow):
    # Tab positions, named so index arithmetic doesn't silently rot the next
    # time a tab is added or removed.
    TAB_GIT = 0
    TAB_PROJECTS = 1

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self._closing = False
        self._polling_paused = False
        self._last_usage_check = -1e9  # monotonic ts of last usage fetch start

        self.setWindowTitle(APP_DISPLAY_NAME)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.setStyleSheet(DARK_THEME)

        # Restore geometry (with safety check for off-screen)
        from PySide6.QtWidgets import QApplication
        screen_geo = QApplication.primaryScreen().availableGeometry()
        x = settings.window_x
        y = settings.window_y
        w = settings.window_width
        h = settings.window_height
        # Reset to center if saved position is off-screen
        if (x + w < 50 or x > screen_geo.width() - 50
                or y + h < 50 or y > screen_geo.height() - 50):
            x = (screen_geo.width() - w) // 2
            y = (screen_geo.height() - h) // 2
        self.setGeometry(x, y, w, h)
        self.setMinimumWidth(580)

        # --- Toolbar ---
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setStyleSheet(
            "QToolBar { background: #252526; border-bottom: 1px solid #474747; spacing: 4px; padding: 4px; }"
        )

        toolbar.addWidget(self._make_toolbar_label())

        spacer = QWidget()
        spacer.setFixedWidth(12)
        spacer.setStyleSheet("background: transparent;")
        toolbar.addWidget(spacer)

        # Live usage meters (5-hour + 7-day limit windows)
        from src.gui.widgets.usage_meter import UsageMeters, CommitMeter
        self.usage_meters = UsageMeters()
        self.usage_meters.setCursor(Qt.PointingHandCursor)
        self.usage_meters.mousePressEvent = lambda _: self._check_usage()
        toolbar.addWidget(self.usage_meters)

        self._usage_worker = None
        self._usage_timer = QTimer(self)
        self._usage_timer.timeout.connect(self._check_usage)
        self._usage_timer.start(600_000)  # network refresh every 10 min
        # (the meter widget ticks its reset countdowns locally every 30s; the
        # 5h/7d/weekly windows barely move, so polling harder just wastes calls)
        QTimer.singleShot(800, self._check_usage)

        # Daily commit count (to the right of the Fable meter)
        self.commit_meter = CommitMeter(settings.commit_goal)
        self.commit_meter.setCursor(Qt.PointingHandCursor)
        self.commit_meter.mousePressEvent = lambda _: self._check_commits(force=True)
        toolbar.addWidget(self.commit_meter)

        self._commit_worker = None
        self._last_commit_check = -1e9
        self._commit_timer = QTimer(self)
        self._commit_timer.timeout.connect(self._check_commits)
        self._commit_timer.start(300_000)  # recount every 5 min
        QTimer.singleShot(1200, self._check_commits)

        # Stretch to push buttons right
        stretch = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        stretch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        stretch.setStyleSheet("background: transparent;")
        toolbar.addWidget(stretch)

        # GitHub account switcher (gh CLI)
        from PySide6.QtWidgets import QComboBox
        self.account_combo = QComboBox()
        self.account_combo.setToolTip("Switch the active GitHub account (gh auth switch)")
        self.account_combo.setMinimumWidth(130)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        toolbar.addWidget(self.account_combo)
        QTimer.singleShot(100, self._populate_accounts)

        # Ollama status dot
        self.ollama_dot = QLabel("\u25CF")
        self.ollama_dot.setFixedWidth(28)
        self.ollama_dot.setAlignment(Qt.AlignCenter)
        self.ollama_dot.setCursor(Qt.PointingHandCursor)
        self.ollama_dot.setToolTip("Ollama: checking...")
        self.ollama_dot.setStyleSheet(
            "color: #6e6e6e; font-size: 16px; background: transparent;"
        )
        self.ollama_dot.mousePressEvent = lambda _: self._show_ollama_info()
        toolbar.addWidget(self.ollama_dot)
        self._ollama_status: dict = {}

        # Check ollama on startup and every 30 seconds (non-blocking)
        self._ollama_health_worker = None
        self._ollama_timer = QTimer(self)
        self._ollama_timer.timeout.connect(self._check_ollama)
        self._ollama_timer.start(30_000)
        QTimer.singleShot(500, self._check_ollama)

        self.pin_btn = QPushButton("Pin")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Always on top")
        self.pin_btn.clicked.connect(self._toggle_on_top)
        toolbar.addWidget(self.pin_btn)

        help_btn = QPushButton("?")
        help_btn.setFixedWidth(32)
        help_btn.setToolTip("Keyboard shortcuts")
        help_btn.clicked.connect(self._show_shortcuts)
        toolbar.addWidget(help_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setToolTip("Manage repos and preferences")
        settings_btn.clicked.connect(self._open_settings)
        toolbar.addWidget(settings_btn)

        self.addToolBar(toolbar)

        # --- Tabs ---
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.git_panel = GitStatusPanel(settings)
        # Recount commits the moment one lands (no waiting for the poll).
        self.git_panel.commits_changed.connect(
            lambda: self._check_commits(force=True)
        )

        self.project_panel = ProjectPanel(settings)

        self.tabs.addTab(self.git_panel, "Git")
        self.tabs.addTab(self.project_panel, "Projects")

        # Scan repos when the Git / Projects tabs are first activated
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._git_scanned = False

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+L"), self, self.git_panel._on_launch_tiled)
        QShortcut(QKeySequence("Ctrl+1"), self,
                  lambda: self.tabs.setCurrentIndex(self.TAB_GIT))
        QShortcut(QKeySequence("Ctrl+2"), self,
                  lambda: self.tabs.setCurrentIndex(self.TAB_PROJECTS))
        QShortcut(QKeySequence("Ctrl+R"), self, self._refresh_git)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.git_panel._on_commit)

    def _make_toolbar_label(self) -> QWidget:
        from PySide6.QtWidgets import QLabel
        lbl = QLabel(f"  {APP_DISPLAY_NAME}")
        lbl.setStyleSheet("color: #007acc; font-weight: bold; font-size: 14px; background: transparent;")
        return lbl

    def _toggle_on_top(self, checked: bool):
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
            self.pin_btn.setText("Unpin")
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
            self.pin_btn.setText("Pin")
        self.show()

    # ---- Polling lifecycle (pause while hidden/minimized) ----

    def _pause_polling(self):
        """Stop the periodic usage/ollama polls (window not visible)."""
        if self._polling_paused:
            return
        self._polling_paused = True
        self._usage_timer.stop()
        self._ollama_timer.stop()
        self._commit_timer.stop()

    def _resume_polling(self):
        """Restart polling and refresh once when the window comes back."""
        if self._closing or not self._polling_paused:
            return
        self._polling_paused = False
        self._usage_timer.start(600_000)
        self._ollama_timer.start(30_000)
        self._commit_timer.start(300_000)
        # Refresh immediately so the meters/status are current on return.
        self._check_usage()
        self._check_ollama()
        self._check_commits()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized():
                self._pause_polling()
            else:
                self._resume_polling()
        super().changeEvent(event)

    def hideEvent(self, event):
        self._pause_polling()
        super().hideEvent(event)

    def showEvent(self, event):
        self._resume_polling()
        super().showEvent(event)

    def _populate_accounts(self):
        """Reconcile gh accounts with settings and fill the toolbar dropdown.

        Each account maps to its own folder; the active one drives which repos
        the Git and Launch tabs show. Selecting an item is handled separately
        in _on_account_changed (signals are blocked here so it doesn't fire).
        """
        from src.core.github_accounts import list_accounts
        usernames, active = list_accounts()
        prev_active = self.settings.active_account
        if self.settings.sync_accounts(usernames, active):
            self.settings.save()

        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        if not self.settings.accounts:
            self.account_combo.addItem("(no gh account)")
            self.account_combo.setEnabled(False)
        else:
            self.account_combo.setEnabled(True)
            for acct in self.settings.accounts:
                label = acct.username or "(default)"
                if not acct.folder:
                    label += "  ⚠ no folder"
                self.account_combo.addItem(label, acct.username)
            idx = self.account_combo.findData(self.settings.active_account)
            if idx >= 0:
                self.account_combo.setCurrentIndex(idx)
        self.account_combo.blockSignals(False)

        # If reconciliation moved the active account (e.g. gh switched outside
        # the app, or a fresh login changed the active identity), rebuild the
        # views so they reflect the now-active account's folder.
        if self.settings.active_account != prev_active:
            self._apply_active_account()

    def _apply_active_account(self):
        """Rebuild the Launch/Git views for the current active account.

        The account's folder is the only thing that decides which repos show,
        so re-scope before rebuilding: anything left over from another
        account's drive is dropped, and anything new in this folder is picked
        up.
        """
        acct = self.settings.active()
        if acct is not None and not acct.folder:
            self.git_panel.log.log_info(
                f"No folder set for {acct.username or 'this account'} — "
                "open Settings to choose one."
            )
        added, removed = self.settings.sync_repos()
        if added or removed:
            self.settings.save()
        if removed:
            self.git_panel.log.log_info(
                f"Dropped {removed} repo(s) outside "
                f"{acct.folder if acct else 'this account'}"
            )
        if acct is not None and acct.folder:
            self.git_panel.log.log_info(
                f"Showing {len(acct.repos)} repo(s) from {acct.folder}"
            )
        self.git_panel._build_cards()
        self.project_panel.refresh_repos()
        self._git_scanned = False
        if self.tabs.currentIndex() == self.TAB_GIT:
            self.git_panel.scan_all()
            self._git_scanned = True

    def _on_account_changed(self, index: int):
        """Switch the active account: swap folder/repos and the gh identity."""
        username = self.account_combo.itemData(index)
        if username is None or username == self.settings.active_account:
            return

        # Keep the gh CLI identity in sync with the selected account.
        if username:
            from src.core.github_accounts import switch_account
            ok, msg = switch_account(username)
            if ok:
                self.git_panel.log.log_ok(f"Switched GitHub account to {username}")
            else:
                QMessageBox.warning(
                    self, "Account Switch Failed",
                    f"Could not switch gh to {username}:\n{msg}\n\n"
                    "Showing this account's folder anyway.",
                )

        # Swap the visible workspace to this account's folder.
        self.settings.active_account = username
        self.settings.save()
        self._apply_active_account()
        # The commit meter tracks the active gh identity's contribution graph,
        # so recount now that the identity changed.
        self._check_commits(force=True)

    # Minimum spacing between usage fetches. The endpoint throttles under
    # frequent polling (returns an empty payload), so manual clicks and
    # minimize/restore refreshes are rate-limited to this. The 10-min periodic
    # timer is always well past it.
    _USAGE_MIN_INTERVAL = 30.0

    def _check_usage(self, force: bool = False):
        """Fetch live usage limits off the UI thread (non-blocking)."""
        if self._closing:
            return
        now = time.monotonic()
        if not force and now - self._last_usage_check < self._USAGE_MIN_INTERVAL:
            return  # too soon since the last fetch — avoid throttling the API
        from src.core.usage_tracker import UsageWorker
        if self._usage_worker is not None and self._usage_worker.isRunning():
            return  # previous fetch still in progress
        self._last_usage_check = now
        self._usage_worker = UsageWorker(self)
        self._usage_worker.result.connect(self.usage_meters.update_data)
        self._usage_worker.start()

    # Light debounce so a burst of triggers (poll + commit signal + click)
    # coalesces into one recount. Cheap local git calls, so this is small.
    _COMMIT_MIN_INTERVAL = 3.0

    def _check_commits(self, force: bool = False):
        """Recount today's authored commits off the UI thread."""
        if self._closing:
            return
        now = time.monotonic()
        if not force and now - self._last_commit_check < self._COMMIT_MIN_INTERVAL:
            return
        from src.core.commit_counter import CommitCountWorker
        if self._commit_worker is not None and self._commit_worker.isRunning():
            return  # previous count still in progress
        self._last_commit_check = now
        self._commit_worker = CommitCountWorker(self)
        self._commit_worker.result.connect(self.commit_meter.set_count)
        self._commit_worker.start()

    def _check_ollama(self):
        """Kick off a background health check (non-blocking)."""
        if self._closing:
            return
        if self._ollama_health_worker is not None and self._ollama_health_worker.isRunning():
            return  # previous check still in progress
        self._ollama_health_worker = OllamaHealthWorker(parent=self)
        self._ollama_health_worker.result.connect(self._on_ollama_health)
        self._ollama_health_worker.start()

    def _on_ollama_health(self, status: dict):
        """Update the status dot from the background worker's result."""
        self._ollama_status = status
        if status["running"]:
            color = "#4ec963"  # green
            tip = f"Ollama: running (v{status['version']})"
            if status["models"]:
                tip += f"\nModels: {', '.join(status['models'][:5])}"
                if len(status["models"]) > 5:
                    tip += f" (+{len(status['models']) - 5} more)"
        else:
            color = "#f44747"  # red
            tip = "Ollama: not running"
            if status["version"]:
                tip += f" (installed: {status['version']})"
        self.ollama_dot.setStyleSheet(
            f"color: {color}; font-size: 16px; background: transparent;"
        )
        self.ollama_dot.setToolTip(tip)

    def _show_ollama_info(self):
        """Show ollama details when the status dot is clicked."""
        status = self._ollama_status
        if not status:
            QMessageBox.information(self, "Ollama Status", "Status not yet checked.")
            return
        if status["running"]:
            models = status["models"]
            model_list = "\n".join(f"  - {m}" for m in models) if models else "  (none)"
            text = (
                f"<b>Status:</b> Running<br>"
                f"<b>Version:</b> {status['version']}<br><br>"
                f"<b>Available models:</b><pre>{model_list}</pre>"
            )
        else:
            text = (
                "<b>Status:</b> Not running<br><br>"
                "Start Ollama with:<br>"
                "<code>ollama serve</code><br><br>"
                "Or install with:<br>"
                "<code>winget install Ollama.Ollama</code>"
            )
        QMessageBox.information(self, "Ollama Status", text)

    def _show_shortcuts(self):
        from PySide6.QtWidgets import QMessageBox
        shortcuts = (
            "<table cellpadding='4'>"
            "<tr><td><b>Ctrl+L</b></td><td>Launch selected repos tiled</td></tr>"
            "<tr><td><b>Ctrl+1</b></td><td>Switch to Git tab</td></tr>"
            "<tr><td><b>Ctrl+2</b></td><td>Switch to Projects tab</td></tr>"
            "<tr><td><b>Ctrl+R</b></td><td>Refresh git status</td></tr>"
            "<tr><td><b>Ctrl+Enter</b></td><td>Commit all dirty repos</td></tr>"
            "</table>"
        )
        QMessageBox.information(self, "Keyboard Shortcuts", shortcuts)

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply()
            self.settings.save()
            self.git_panel._build_cards()
            self.project_panel.refresh_repos()
            self._git_scanned = False
            self._populate_accounts()  # clear any "no folder" warnings
            # Goal or repo set may have changed — re-evaluate the commit meter.
            self.commit_meter.set_goal(self.settings.commit_goal)
            self._check_commits(force=True)

    def _refresh_git(self):
        self.tabs.setCurrentIndex(self.TAB_GIT)
        self.git_panel.scan_all()
        self._git_scanned = True

    def _on_tab_changed(self, index: int):
        if index == self.TAB_GIT:
            self._populate_accounts()
            if not self._git_scanned:
                self.git_panel.scan_all()
                self._git_scanned = True
        elif index == self.TAB_PROJECTS:
            self.project_panel.ensure_loaded()

    def closeEvent(self, event):
        # Save geometry and settings
        geo = self.geometry()
        self.settings.window_x = geo.x()
        self.settings.window_y = geo.y()
        self.settings.window_width = geo.width()
        self.settings.window_height = geo.height()
        self.settings.save()

        # Stop background timers and wait on any in-flight worker threads so we
        # don't exit with a "QThread destroyed while still running" crash.
        # The flag stops any pending one-shot timer from starting a new worker
        # after we've already torn the running ones down.
        self._closing = True
        self._usage_timer.stop()
        self._ollama_timer.stop()
        self._commit_timer.stop()
        from src.core.process_launcher import stop_worker
        stop_worker(self._usage_worker)
        stop_worker(self._ollama_health_worker)
        stop_worker(self._commit_worker)
        self.git_panel.stop_workers()
        self.project_panel.stop_workers()

        super().closeEvent(event)

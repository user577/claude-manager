from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QPushButton, QWidget, QLabel,
    QMessageBox,
)

from src.constants import APP_DISPLAY_NAME, ICON_PATH
from src.config.settings import Settings
from src.core.process_launcher import OllamaHealthWorker
from src.gui.launcher_panel import LauncherPanel
from src.gui.git_status_panel import GitStatusPanel
from src.gui.settings_dialog import SettingsDialog
from src.gui.styles import DARK_THEME


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

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
        spacer.setFixedWidth(1)
        spacer.setStyleSheet("background: transparent;")
        toolbar.addWidget(spacer)

        # Stretch to push buttons right
        stretch = QWidget()
        stretch.setSizePolicy(stretch.sizePolicy())
        from PySide6.QtWidgets import QSizePolicy
        stretch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        stretch.setStyleSheet("background: transparent;")
        toolbar.addWidget(stretch)

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

        self.launcher_panel = LauncherPanel(settings)
        self.git_panel = GitStatusPanel(settings)

        self.tabs.addTab(self.launcher_panel, "Launch")
        self.tabs.addTab(self.git_panel, "Git")

        # Scan repos when Git tab is first activated
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._git_scanned = False

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+L"), self, self.launcher_panel._on_launch)
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.tabs.setCurrentIndex(1))
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

    def _check_ollama(self):
        """Kick off a background health check (non-blocking)."""
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
            "<tr><td><b>Ctrl+L</b></td><td>Launch Claude instances</td></tr>"
            "<tr><td><b>Ctrl+1</b></td><td>Switch to Launch tab</td></tr>"
            "<tr><td><b>Ctrl+2</b></td><td>Switch to Git tab</td></tr>"
            "<tr><td><b>Ctrl+R</b></td><td>Refresh git status</td></tr>"
            "<tr><td><b>Ctrl+Enter</b></td><td>Commit all dirty repos</td></tr>"
            "</table>"
        )
        QMessageBox.information(self, "Keyboard Shortcuts", shortcuts)

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings.github_dir = dlg.get_github_dir()
            self.settings.save()
            self.launcher_panel.refresh_repos()
            self.git_panel._build_cards()
            self._git_scanned = False

    def _refresh_git(self):
        self.tabs.setCurrentIndex(1)
        self.git_panel.scan_all()
        self._git_scanned = True

    def _on_tab_changed(self, index: int):
        if index == 1 and not self._git_scanned:
            self.git_panel.scan_all()
            self._git_scanned = True

    def closeEvent(self, event):
        # Save geometry and settings
        geo = self.geometry()
        self.settings.window_x = geo.x()
        self.settings.window_y = geo.y()
        self.settings.window_width = geo.width()
        self.settings.window_height = geo.height()
        self.launcher_panel.save_state()
        self.settings.save()
        super().closeEvent(event)

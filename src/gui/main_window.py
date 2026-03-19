from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QPushButton, QWidget,
)

from src.constants import APP_DISPLAY_NAME, ICON_PATH
from src.config.settings import Settings
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

        # Restore geometry
        self.setGeometry(
            settings.window_x, settings.window_y,
            settings.window_width, settings.window_height,
        )

        # --- Toolbar ---
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setStyleSheet(
            "QToolBar { background: #181825; border-bottom: 1px solid #45475a; spacing: 4px; padding: 4px; }"
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

        self.pin_btn = QPushButton("Pin")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Always on top")
        self.pin_btn.clicked.connect(self._toggle_on_top)
        toolbar.addWidget(self.pin_btn)

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

    def _make_toolbar_label(self) -> QWidget:
        from PySide6.QtWidgets import QLabel
        lbl = QLabel(f"  {APP_DISPLAY_NAME}")
        lbl.setStyleSheet("color: #cba6f7; font-weight: bold; font-size: 14px; background: transparent;")
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

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings.github_dir = dlg.get_github_dir()
            self.settings.save()
            self.launcher_panel.refresh_repos()
            self.git_panel._build_cards()
            self._git_scanned = False

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

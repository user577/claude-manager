from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox, QComboBox,
    QPushButton, QLabel, QScrollArea, QFrame,
)

from src.config.settings import Settings
from src.core.process_launcher import LaunchWorker
from src.gui.widgets.log_output import LogOutput


class LauncherPanel(QWidget):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Repo checklist ---
        header = QLabel("Repositories")
        header.setObjectName("sectionHeader")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(300)

        self.check_container = QWidget()
        self.check_layout = QVBoxLayout(self.check_container)
        self.check_layout.setSpacing(4)
        self.check_layout.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(self.check_container)
        layout.addWidget(scroll)

        self.repo_checkboxes: list[QCheckBox] = []
        self._populate_repos()

        # --- Controls row ---
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Instances:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 4)
        self.count_spin.setValue(self.settings.instance_count)
        controls.addWidget(self.count_spin)

        controls.addSpacing(16)

        controls.addWidget(QLabel("Layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["2x2 Grid", "Vertical Stack", "Horizontal Stack", "Single"])
        layout_map = {"grid_2x2": 0, "vertical": 1, "horizontal": 2, "single": 3}
        self.layout_combo.setCurrentIndex(layout_map.get(self.settings.layout, 0))
        controls.addWidget(self.layout_combo)

        controls.addStretch()
        layout.addLayout(controls)

        # --- Launch button ---
        self.launch_btn = QPushButton("Launch Claude")
        self.launch_btn.setObjectName("launchBtn")
        self.launch_btn.clicked.connect(self._on_launch)
        layout.addWidget(self.launch_btn)

        # --- Log ---
        self.log = LogOutput()
        layout.addWidget(self.log)

        layout.addStretch()

    def _populate_repos(self):
        # Clear existing
        for cb in self.repo_checkboxes:
            cb.setParent(None)
        self.repo_checkboxes.clear()

        for repo in self.settings.repos:
            branch = self.settings.get_branch(repo)
            cb = QCheckBox(f"{repo.label}  ({branch})")
            cb.setChecked(repo.enabled)
            cb.repo_info = repo
            cb.stateChanged.connect(self._on_check_changed)
            self.check_layout.addWidget(cb)
            self.repo_checkboxes.append(cb)

    def refresh_repos(self):
        self._populate_repos()

    def _on_check_changed(self):
        for cb in self.repo_checkboxes:
            cb.repo_info.enabled = cb.isChecked()

    def _get_layout_key(self) -> str:
        idx = self.layout_combo.currentIndex()
        return ["grid_2x2", "vertical", "horizontal", "single"][idx]

    def save_state(self):
        self._on_check_changed()
        self.settings.instance_count = self.count_spin.value()
        self.settings.layout = self._get_layout_key()

    def _on_launch(self):
        self.save_state()
        enabled = self.settings.get_enabled_repos()
        count = self.count_spin.value()
        layout = self._get_layout_key()

        if not enabled:
            self.log.log_err("No repos selected")
            return

        self.launch_btn.setEnabled(False)
        self.log.log_info(f"Launching {min(count, len(enabled))} instances...")

        self._worker = LaunchWorker(enabled, layout, count, parent=self)
        self._worker.status.connect(self.log.log_info)
        self._worker.finished_ok.connect(self._launch_done)
        self._worker.finished_err.connect(self._launch_error)
        self._worker.start()

    def _launch_done(self):
        self.log.log_ok("All instances launched and tiled")
        self.launch_btn.setEnabled(True)
        self._worker = None

    def _launch_error(self, msg: str):
        self.log.log_err(msg)
        self.launch_btn.setEnabled(True)
        self._worker = None

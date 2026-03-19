from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QSpinBox, QComboBox,
    QPushButton, QLabel, QScrollArea, QFrame, QProgressBar, QLineEdit,
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

        # --- Repo checklist header + select buttons ---
        header_row = QHBoxLayout()
        header = QLabel("Repositories")
        header.setObjectName("sectionHeader")
        header_row.addWidget(header)
        header_row.addStretch()

        all_btn = QPushButton("All")
        all_btn.setFixedWidth(50)
        all_btn.clicked.connect(lambda: self._set_all_checks(True))
        header_row.addWidget(all_btn)

        none_btn = QPushButton("None")
        none_btn.setFixedWidth(50)
        none_btn.clicked.connect(lambda: self._set_all_checks(False))
        header_row.addWidget(none_btn)

        layout.addLayout(header_row)

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

        # --- Permission mode row ---
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Default (ask each time)",
            "Accept Edits (auto-approve edits)",
            "Auto (full auto, confirm risky)",
            "Bypass Permissions (skip all checks)",
            "Plan (read-only, no edits)",
        ])
        mode_map = {"default": 0, "acceptEdits": 1, "auto": 2, "bypassPermissions": 3, "plan": 4}
        self.mode_combo.setCurrentIndex(mode_map.get(self.settings.permission_mode, 0))
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        # --- Launch button ---
        self.launch_btn = QPushButton("Launch Claude")
        self.launch_btn.setObjectName("launchBtn")
        self.launch_btn.clicked.connect(self._on_launch)
        layout.addWidget(self.launch_btn)

        # --- Progress ---
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { background: #313244; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: #89b4fa; border-radius: 3px; }"
        )
        self.progress.hide()
        layout.addWidget(self.progress)

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
            if not repo.exists():
                cb = QCheckBox(f"{repo.label}  (MISSING)")
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setStyleSheet("color: #f38ba8;")
                cb.repo_info = repo
                repo.enabled = False
            else:
                branch = self.settings.get_branch(repo)
                cb = QCheckBox(f"{repo.label}  ({branch})")
                cb.setChecked(repo.enabled)
                cb.repo_info = repo
                cb.stateChanged.connect(self._on_check_changed)
            self.check_layout.addWidget(cb)
            self.repo_checkboxes.append(cb)

    def refresh_repos(self):
        self._populate_repos()
        self._refresh_tag_bar()

    def _set_all_checks(self, checked: bool):
        for cb in self.repo_checkboxes:
            if cb.isEnabled() and cb.isVisible():
                cb.setChecked(checked)

    def _refresh_tag_bar(self):
        # Clear existing buttons
        for btn in self.tag_buttons.values():
            btn.setParent(None)
        self.tag_buttons.clear()
        # Remove stretch items
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
            "QPushButton { background: transparent; color: #585b70; border: none; "
            "font-size: 11px; padding: 3px 6px; }"
            "QPushButton:hover { color: #cdd6f4; }"
        )
        clear_btn.clicked.connect(self._clear_tags)
        self.tag_bar.addWidget(clear_btn)
        self.tag_bar.addStretch()

    @staticmethod
    def _tag_style(active: bool) -> str:
        if active:
            return (
                "QPushButton { background: #cba6f7; color: #1e1e2e; "
                "border-radius: 10px; padding: 3px 10px; font-size: 11px; border: none; }"
                "QPushButton:hover { background: #d4b5fa; }"
            )
        return (
            "QPushButton { background: #313244; color: #cdd6f4; "
            "border-radius: 10px; padding: 3px 10px; font-size: 11px; border: none; }"
            "QPushButton:hover { background: #45475a; }"
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
        for cb in self.repo_checkboxes:
            matches_search = not query or query in cb.repo_info.label.lower()
            matches_tags = not self.active_tags or bool(
                set(cb.repo_info.tags) & self.active_tags
            )
            cb.setVisible(matches_search and matches_tags)

    def _on_check_changed(self):
        for cb in self.repo_checkboxes:
            cb.repo_info.enabled = cb.isChecked()

    def _get_layout_key(self) -> str:
        idx = self.layout_combo.currentIndex()
        return ["grid_2x2", "vertical", "horizontal", "single"][idx]

    def _get_permission_mode(self) -> str:
        idx = self.mode_combo.currentIndex()
        return ["default", "acceptEdits", "auto", "bypassPermissions", "plan"][idx]

    def save_state(self):
        self._on_check_changed()
        self.settings.instance_count = self.count_spin.value()
        self.settings.layout = self._get_layout_key()
        self.settings.permission_mode = self._get_permission_mode()

    def _on_launch(self):
        self.save_state()
        enabled = self.settings.get_enabled_repos()
        count = self.count_spin.value()
        layout = self._get_layout_key()

        if not enabled:
            self.log.log_err("No repos selected")
            return

        actual_count = min(count, len(enabled))
        self.launch_btn.setEnabled(False)
        self.progress.setRange(0, actual_count + 1)  # +1 for tiling step
        self.progress.setValue(0)
        self.progress.show()
        self.log.log_info(f"Launching {actual_count} instances...")

        mode = self._get_permission_mode()
        self._worker = LaunchWorker(enabled, layout, count, mode, parent=self)
        self._worker.status.connect(self._on_launch_status)
        self._worker.finished_ok.connect(self._launch_done)
        self._worker.finished_err.connect(self._launch_error)
        self._worker.start()

    def _on_launch_status(self, msg: str):
        self.log.log_info(msg)
        self.progress.setValue(self.progress.value() + 1)

    def _launch_done(self):
        self.log.log_ok("All instances launched and tiled")
        self.progress.setValue(self.progress.maximum())
        self.progress.hide()
        self.launch_btn.setEnabled(True)
        self._worker = None

    def _launch_error(self, msg: str):
        self.log.log_err(msg)
        self.progress.hide()
        self.launch_btn.setEnabled(True)
        self._worker = None

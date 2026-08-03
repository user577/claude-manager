from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton

from src.core.repo_scanner import RepoStatus
from src.gui.styles import COLOR_CLEAN, COLOR_DIRTY, COLOR_ERROR, COLOR_UNKNOWN, COLOR_AHEAD, COLOR_BEHIND


class StatusDot(QWidget):
    def __init__(self, color: str = COLOR_UNKNOWN, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(14, 14)

    def set_color(self, color: str):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self.color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, 12, 12)
        p.end()


class RepoStatusCard(QWidget):
    launch_requested = Signal(str)  # emits repo path
    launch_auto_requested = Signal(str)  # emits repo path — dangerously-skip-permissions
    agent_heavy_requested = Signal(str)  # emits repo path — auto-scaling subagent ladder
    agent_team_requested = Signal(str)  # emits repo path — parallel Agent Teams lead

    def __init__(self, parent=None):
        super().__init__(parent)
        self._repo_path = ""
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.dot = StatusDot()
        layout.addWidget(self.dot)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(0)

        self.name_label = QLabel("repo-name")
        self.name_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        info_layout.addWidget(self.name_label)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("font-size: 11px; color: #9e9e9e;")
        info_layout.addWidget(self.detail_label)

        layout.addLayout(info_layout, 1)

        self.commit_label = QLabel("")
        self.commit_label.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; "
            "font-size: 11px; color: #6e6e6e;"
        )
        self.commit_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.commit_label)

        self.launch_btn = QPushButton("Launch")
        self.launch_btn.setFixedWidth(60)
        self.launch_btn.setCursor(Qt.PointingHandCursor)
        self.launch_btn.setStyleSheet(
            "QPushButton { background: #474747; color: #cccccc; border: none; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
            "QPushButton:hover { background: #555555; }"
        )
        self.launch_btn.clicked.connect(lambda: self.launch_requested.emit(self._repo_path))
        layout.addWidget(self.launch_btn)

        self.launch_auto_btn = QPushButton("Launch Auto")
        self.launch_auto_btn.setFixedWidth(84)
        self.launch_auto_btn.setCursor(Qt.PointingHandCursor)
        self.launch_auto_btn.setToolTip(
            "Launch with --dangerously-skip-permissions (no confirmation prompts)"
        )
        self.launch_auto_btn.setStyleSheet(
            "QPushButton { background: #8b3a3a; color: #ffffff; border: none; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #a84545; }"
        )
        self.launch_auto_btn.clicked.connect(
            lambda: self.launch_auto_requested.emit(self._repo_path)
        )
        layout.addWidget(self.launch_auto_btn)

        self.agent_heavy_btn = QPushButton("Agent Heavy")
        self.agent_heavy_btn.setFixedWidth(96)
        self.agent_heavy_btn.setCursor(Qt.PointingHandCursor)
        self.agent_heavy_btn.setToolTip(
            "Auto launch (--dangerously-skip-permissions) with an enforced "
            "Haiku->Sonnet->Opus subagent ladder (scout/runner/implementer/"
            "deep-worker) loaded via --add-dir. The orchestrator sizes each task "
            "and delegates to the cheapest tier that fits, escalating only when "
            "needed. Best for substantial tasks — overkill for quick edits."
        )
        self.agent_heavy_btn.setStyleSheet(
            "QPushButton { background: #6e40c9; color: #ffffff; border: none; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #8b5cf6; }"
        )
        self.agent_heavy_btn.clicked.connect(
            lambda: self.agent_heavy_requested.emit(self._repo_path)
        )
        layout.addWidget(self.agent_heavy_btn)

        self.agent_team_btn = QPushButton("Agent Team")
        self.agent_team_btn.setFixedWidth(88)
        self.agent_team_btn.setCursor(Qt.PointingHandCursor)
        self.agent_team_btn.setToolTip(
            "Auto launch as an Agent Teams lead (experimental): spawns full "
            "parallel Claude sessions that coordinate via a shared task list "
            "and direct messaging. Fastest wall-clock on big parallelizable "
            "work, but burns far more tokens than Agent Heavy — which stays "
            "the better default when cost matters."
        )
        self.agent_team_btn.setStyleSheet(
            "QPushButton { background: #1f6f8b; color: #ffffff; border: none; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #2e8cab; }"
        )
        self.agent_team_btn.clicked.connect(
            lambda: self.agent_team_requested.emit(self._repo_path)
        )
        layout.addWidget(self.agent_team_btn)

    def update_status(self, status: RepoStatus):
        self._repo_path = status.path
        self.name_label.setText(f"{status.label}  ({status.branch})")

        # Status details
        parts = []
        if status.error:
            parts.append(f"Error: {status.error}")
        else:
            if status.modified_count:
                parts.append(f"{status.modified_count} modified")
            if status.untracked_count:
                parts.append(f"{status.untracked_count} untracked")
            if status.ahead:
                parts.append(f"{status.ahead} ahead")
            if status.behind:
                parts.append(f"{status.behind} behind")
            if status.diverged:
                parts.append("DIVERGED")
            if status.stash_count:
                parts.append(f"{status.stash_count} stash")
            if not parts:
                parts.append("Clean")
        self.detail_label.setText(" | ".join(parts))

        # Dot color
        if status.error:
            self.dot.set_color(COLOR_ERROR)
        elif status.diverged:
            self.dot.set_color(COLOR_ERROR)
        elif status.dirty:
            self.dot.set_color(COLOR_DIRTY)
        elif status.ahead:
            self.dot.set_color(COLOR_AHEAD)
        elif status.behind:
            self.dot.set_color(COLOR_BEHIND)
        else:
            self.dot.set_color(COLOR_CLEAN)

        # Last commit hash
        self.commit_label.setText(status.last_commit[:40] if status.last_commit else "")

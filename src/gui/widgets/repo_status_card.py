from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

from src.core.repo_scanner import RepoStatus
from src.gui.styles import COLOR_CLEAN, COLOR_DIRTY, COLOR_ERROR, COLOR_UNKNOWN, COLOR_AHEAD


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
    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.detail_label.setStyleSheet("font-size: 11px; color: #a6adc8;")
        info_layout.addWidget(self.detail_label)

        layout.addLayout(info_layout, 1)

        self.commit_label = QLabel("")
        self.commit_label.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; "
            "font-size: 11px; color: #585b70;"
        )
        self.commit_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.commit_label)

    def update_status(self, status: RepoStatus):
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
            if not parts:
                parts.append("Clean")
        self.detail_label.setText(" | ".join(parts))

        # Dot color
        if status.error:
            self.dot.set_color(COLOR_ERROR)
        elif status.dirty:
            self.dot.set_color(COLOR_DIRTY)
        elif status.ahead:
            self.dot.set_color(COLOR_AHEAD)
        else:
            self.dot.set_color(COLOR_CLEAN)

        # Last commit hash
        self.commit_label.setText(status.last_commit[:40] if status.last_commit else "")

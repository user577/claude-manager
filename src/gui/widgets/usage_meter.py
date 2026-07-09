"""Compact usage meters for the toolbar — 5-hour and 7-day limit windows."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar

from src.core.usage_tracker import UsageData, Window, humanize_reset

_SEVERITY_COLOR = {
    "normal": "#4ec963",    # green
    "warning": "#d7a13b",   # amber
    "critical": "#f44747",  # red
}


class _Meter(QWidget):
    """One labeled bar: caption + thin progress bar showing % used."""

    def __init__(self, caption: str, full_name: str, parent=None):
        super().__init__(parent)
        self._full_name = full_name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        cap = QLabel(caption)
        cap.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(cap)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFixedSize(84, 15)
        self.bar.setTextVisible(True)
        self.bar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.bar)

        self._set_bar_color("#6e6e6e")
        self.set_unknown()

    def _set_bar_color(self, color: str):
        self.bar.setStyleSheet(
            "QProgressBar { background: #3c3c3c; border: none; border-radius: 3px; "
            "color: #ffffff; font-size: 10px; font-weight: bold; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
        )

    def set_window(self, win: Window):
        pct = max(0, min(100, int(round(win.percent))))
        self.bar.setValue(pct)
        self.bar.setFormat(f"{pct}%")
        self._set_bar_color(_SEVERITY_COLOR.get(win.severity, "#4ec963"))
        reset = humanize_reset(win.resets_at)
        remaining = max(0, 100 - win.percent)
        tip = f"{self._full_name}: {win.percent:.0f}% used ({remaining:.0f}% left)"
        if reset:
            tip += f"\n{reset}"
        self.setToolTip(tip)

    def set_unknown(self, reason: str = "loading…"):
        self.bar.setValue(0)
        self.bar.setFormat("—")
        self._set_bar_color("#6e6e6e")
        self.setToolTip(f"{self._full_name}: {reason}")


class UsageMeters(QWidget):
    """Two meters side by side, updated from a :class:`UsageData`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.five = _Meter("5h", "5-hour session limit")
        self.week = _Meter("7d", "7-day weekly limit")
        layout.addWidget(self.five)
        layout.addWidget(self.week)
        self.setToolTip("Claude usage limits — click to refresh")

    def update_data(self, data: UsageData):
        if not data.ok:
            self.five.set_unknown(data.error)
            self.week.set_unknown(data.error)
            return
        if data.five_hour:
            self.five.set_window(data.five_hour)
        else:
            self.five.set_unknown("no data")
        if data.seven_day:
            self.week.set_window(data.seven_day)
        else:
            self.week.set_unknown("no data")

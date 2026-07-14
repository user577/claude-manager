"""Compact usage meters for the toolbar — 5-hour and 7-day limit windows."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar

from src.core.usage_tracker import (
    UsageData, Window, humanize_reset, humanize_reset_short,
)

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

        self._cap = QLabel(caption)
        self._cap.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(self._cap)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFixedSize(84, 15)
        self.bar.setTextVisible(True)
        self.bar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.bar)

        # Remaining time until this window resets (e.g. "2h 15m").
        self.reset_label = QLabel("")
        self.reset_label.setMinimumWidth(46)
        self.reset_label.setStyleSheet(
            "color: #9e9e9e; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self.reset_label)

        self._win: Window | None = None
        self._set_bar_color("#6e6e6e")
        self.set_unknown()

    def set_caption(self, caption: str):
        self._cap.setText(caption)

    def _set_bar_color(self, color: str):
        self.bar.setStyleSheet(
            "QProgressBar { background: #3c3c3c; border: none; border-radius: 3px; "
            "color: #ffffff; font-size: 10px; font-weight: bold; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
        )

    def set_window_or_keep(self, win: Window | None, reason: str = "no data"):
        """Update from ``win``; if it's missing, keep the last good reading.

        The usage endpoint intermittently returns a degraded/empty payload
        (e.g. when polled too often). Blanking a real reading on those
        responses causes flicker, so we only fall back to the placeholder when
        we've never had data to show.
        """
        if win is not None:
            self.set_window(win)
        elif self._win is None:
            self.set_unknown(reason)
        # else: keep the last good window untouched

    def set_window(self, win: Window):
        self._win = win
        pct = max(0, min(100, int(round(win.percent))))
        self.bar.setValue(pct)
        self.bar.setFormat(f"{pct}%")
        self._set_bar_color(_SEVERITY_COLOR.get(win.severity, "#4ec963"))
        self._refresh_time()

    def _refresh_time(self):
        """Re-render the reset countdown + tooltip from the stored window.

        Cheap and network-free — safe to call on a short local timer so the
        '↻ 2h 15m' text stays fresh between the (infrequent) network fetches.
        """
        win = self._win
        if win is None:
            return
        short = humanize_reset_short(win.resets_at)
        self.reset_label.setText(f"↻ {short}" if short else "")
        reset = humanize_reset(win.resets_at)
        remaining = max(0, 100 - win.percent)
        tip = f"{self._full_name}: {win.percent:.0f}% used ({remaining:.0f}% left)"
        if reset:
            tip += f"\n{reset}"
        self.setToolTip(tip)

    def set_unknown(self, reason: str = "loading…"):
        self._win = None
        self.bar.setValue(0)
        self.bar.setFormat("—")
        self.reset_label.setText("")
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
        self.fable = _Meter("Fable", "Weekly Fable model limit")
        layout.addWidget(self.five)
        layout.addWidget(self.week)
        layout.addWidget(self.fable)
        self.setToolTip("Claude usage limits — click to refresh")

        # Tick the reset countdowns locally so they stay fresh without hitting
        # the network — the actual usage % is refreshed far less often.
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_time)
        self._tick.start(30_000)  # every 30s

    def _refresh_time(self):
        self.five._refresh_time()
        self.week._refresh_time()
        self.fable._refresh_time()

    def update_data(self, data: UsageData):
        if not data.ok:
            # Transient/throttled failures shouldn't wipe good readings.
            self.five.set_window_or_keep(None, data.error)
            self.week.set_window_or_keep(None, data.error)
            self.fable.set_window_or_keep(None, data.error)
            return
        self.five.set_window_or_keep(data.five_hour)
        self.week.set_window_or_keep(data.seven_day)
        if data.scoped_name:
            self.fable.set_caption(data.scoped_name)
        self.fable.set_window_or_keep(data.scoped)

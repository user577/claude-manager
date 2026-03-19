from datetime import datetime

from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor


class LogOutput(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(180)
        self.setPlaceholderText("Operation log...")

    def log(self, message: str, success: bool | None = None):
        ts = datetime.now().strftime("%H:%M:%S")
        if success is True:
            color = "#a6e3a1"
        elif success is False:
            color = "#f38ba8"
        else:
            color = "#a6adc8"
        self.append(f'<span style="color:#585b70">[{ts}]</span> '
                     f'<span style="color:{color}">{message}</span>')
        self.moveCursor(QTextCursor.End)

    def log_ok(self, message: str):
        self.log(message, success=True)

    def log_err(self, message: str):
        self.log(message, success=False)

    def log_info(self, message: str):
        self.log(message, success=None)

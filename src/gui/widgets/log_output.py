from datetime import datetime

from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor

_MAX_LOG_BLOCKS = 200


class LogOutput(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(180)
        self.setPlaceholderText("Operation log...")

    def log(self, message: str, success: bool | None = None):
        ts = datetime.now().strftime("%H:%M:%S")
        if success is True:
            color = "#4ec963"
        elif success is False:
            color = "#f44747"
        else:
            color = "#9e9e9e"
        self.append(f'<span style="color:#6e6e6e">[{ts}]</span> '
                     f'<span style="color:{color}">{message}</span>')
        # Trim oldest lines to prevent unbounded GPU texture growth.
        doc = self.document()
        while doc.blockCount() > _MAX_LOG_BLOCKS + 1:
            cursor = QTextCursor(doc.firstBlock())
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self.moveCursor(QTextCursor.End)

    def log_ok(self, message: str):
        self.log(message, success=True)

    def log_err(self, message: str):
        self.log(message, success=False)

    def log_info(self, message: str):
        self.log(message, success=None)

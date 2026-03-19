"""Entry point for both dev and frozen (PyInstaller) modes."""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from src.constants import APP_DISPLAY_NAME, ICON_PATH
from src.config.settings import Settings
from src.gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName("ClaudeManager")

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # Windows taskbar icon grouping
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClaudeManager.1.0")
    except Exception:
        pass

    settings = Settings.load()
    window = MainWindow(settings)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

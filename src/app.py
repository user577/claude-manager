"""Entry point for both dev and frozen (PyInstaller) modes."""
import shutil
import sys

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from src.constants import APP_DISPLAY_NAME, ICON_PATH
from src.config.settings import Settings
from src.gui.main_window import MainWindow


def check_prerequisites() -> list[str]:
    """Check that required tools are on PATH. Returns list of missing tools."""
    missing = []
    for tool, label in [("git", "Git"), ("wt", "Windows Terminal"), ("claude", "Claude CLI")]:
        if not shutil.which(tool):
            missing.append(label)
    return missing


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

    # Set up file logging
    from src.core.logger import setup_logging
    logger = setup_logging()
    logger.info("Claude Manager starting")

    # Check prerequisites
    missing = check_prerequisites()
    if missing:
        msg = "The following required tools were not found on PATH:\n\n"
        msg += "\n".join(f"  - {t}" for t in missing)
        msg += "\n\nPlease install them and try again."
        QMessageBox.critical(None, "Claude Manager — Missing Prerequisites", msg)
        sys.exit(1)

    settings = Settings.load()
    window = MainWindow(settings)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

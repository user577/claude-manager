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


def _acquire_single_instance_lock():
    """Acquire a named mutex to enforce single instance. Returns handle or None."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, True, "Global\\ClaudeManager_SingleInstance")
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return None
    return mutex


def _focus_existing_window():
    """Find and bring the existing Claude Manager window to front."""
    import ctypes
    import ctypes.wintypes

    EnumWindows = ctypes.windll.user32.EnumWindows
    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
    SetForegroundWindow = ctypes.windll.user32.SetForegroundWindow
    ShowWindow = ctypes.windll.user32.ShowWindow
    IsIconic = ctypes.windll.user32.IsIconic
    SW_RESTORE = 9

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    buf = ctypes.create_unicode_buffer(256)

    def callback(hwnd, _):
        GetWindowTextW(hwnd, buf, 256)
        if APP_DISPLAY_NAME in buf.value:
            if IsIconic(hwnd):
                ShowWindow(hwnd, SW_RESTORE)
            SetForegroundWindow(hwnd)
            return False  # stop enumerating
        return True

    EnumWindows(WNDENUMPROC(callback), 0)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setOrganizationName("ClaudeManager")

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # Single instance check
    mutex = _acquire_single_instance_lock()
    if mutex is None:
        _focus_existing_window()
        sys.exit(0)

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

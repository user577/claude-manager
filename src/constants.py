import os
import sys
from pathlib import Path

APP_NAME = "ClaudeManager"
APP_DISPLAY_NAME = "Claude Manager"
APP_VERSION = "1.0.0"

DEFAULT_GITHUB_DIR = Path.home() / "Documents" / "GitHub"

# Writable config location
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "settings.json"

# Executables
WT_EXE = "wt.exe"
CLAUDE_CMD = "claude"

# Directories to skip during .pyc cleanup
PYC_SKIP_DIRS = {".venv", "venv", "node_modules", "vendor", ".git", "dist", "build"}

# Icon path (works both dev and frozen)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

ICON_PATH = BASE_DIR / "app_icon.ico"

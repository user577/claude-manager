import logging
from logging.handlers import RotatingFileHandler

from src.constants import CONFIG_DIR

LOG_FILE = CONFIG_DIR / "claude_manager.log"


def setup_logging():
    """Configure file-based logging with 1MB rotation."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger("claude_manager")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return root


log = logging.getLogger("claude_manager")

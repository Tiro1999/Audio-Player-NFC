"""Centralized logging with colored console output and rotating log file.

Usage::

    from .logger import Logger

    logger = Logger(__name__)
    logger.trace("very verbose detail")
    logger.debug("debug information")
    logger.info("normal information")
    logger.warn("something looks off")
    logger.error("something broke")

Log output goes to:
  • stdout  – colored, human-friendly
  • /var/log/nfc_player.log – plain text, rotated at 5 MB (3 backups)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# ── Custom TRACE level (below DEBUG) ──────────────────────────────────────
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# ── Configuration ─────────────────────────────────────────────────────────
LOG_FILE = "/var/log/nfc_player.log"
MAX_LOG_BYTES = 5 * 1024 * 1024   # 5 MB per file
LOG_BACKUP_COUNT = 3               # keep 3 rotated backups

# ── ANSI colors ───────────────────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_COLORS = {
    TRACE:           "\033[90m",    # grey
    logging.DEBUG:   "\033[36m",    # cyan
    logging.INFO:    "\033[32m",    # green
    logging.WARNING: "\033[33m",    # yellow
    logging.ERROR:   "\033[91m",    # bright red
}


class _ColorFormatter(logging.Formatter):
    """Adds ANSI color codes to log output (console only)."""

    def format(self, record):
        color = _COLORS.get(record.levelno, "")
        saved_levelname = record.levelname
        saved_msg = record.msg

        record.levelname = f"{color}{_BOLD}{saved_levelname:<7}{_RESET}"
        record.msg = f"{color}{record.msg}{_RESET}"
        out = super().format(record)

        # Restore originals so the file handler gets clean text
        record.levelname = saved_levelname
        record.msg = saved_msg
        return out


class Logger:
    """Drop-in logger with ``.trace()``, colored console, and file rotation.

    The logging subsystem is initialised once on first ``Logger`` instantiation.
    Subsequent instances simply create a named child logger.
    """

    _initialized = False

    @classmethod
    def setup(cls, console_level=TRACE, file_level=TRACE):
        """Configure root logger (idempotent)."""
        if cls._initialized:
            return
        root = logging.getLogger()
        root.setLevel(TRACE)
        root.handlers.clear()

        # ── Console handler (colored) ─────────────────────────────────
        console = logging.StreamHandler()
        console.setLevel(console_level)
        console.setFormatter(_ColorFormatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        root.addHandler(console)

        # ── File handler (rotating, plain text) ───────────────────────
        try:
            log_dir = os.path.dirname(LOG_FILE)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            fh = RotatingFileHandler(
                LOG_FILE,
                maxBytes=MAX_LOG_BYTES,
                backupCount=LOG_BACKUP_COUNT,
            )
            fh.setLevel(file_level)
            fh.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            root.addHandler(fh)
        except (PermissionError, OSError) as exc:
            root.warning("File logging disabled – cannot write to %s (%s)", LOG_FILE, exc)

        cls._initialized = True

    # ── Instance ──────────────────────────────────────────────────────

    def __init__(self, name: str):
        Logger.setup()
        self._log = logging.getLogger(name)

    def trace(self, msg, *args, **kwargs):
        self._log.log(TRACE, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._log.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log.info(msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        self._log.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log.error(msg, *args, **kwargs)

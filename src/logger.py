"""Centralized structured logging with colored console and daily-rotating file.

Log format:  TIMESTAMP | LEVEL | FILE | FUNCTION | MESSAGE

Output targets:
  - stdout  -- colored, human-friendly (short timestamp)
  - ~/nfc-player/logs/nfc_player.log -- plain text, rotated daily at midnight (3 days kept)
"""

import logging
import os
import pathlib
from logging.handlers import TimedRotatingFileHandler

# ── Custom TRACE level (below DEBUG) ──────────────────────────────────────
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# ── Paths ─────────────────────────────────────────────────────────────────
_SRC_DIR = pathlib.Path(__file__).resolve().parent
_PROJECT_DIR = _SRC_DIR.parent
LOG_DIR = str(_PROJECT_DIR / "logs")
LOG_FILE = str(_PROJECT_DIR / "logs" / "nfc_player.log")
LOG_BACKUP_COUNT = 3               # keep 3 daily backups

# ── Structured format: TIMESTAMP | LEVEL | FILE | FUNCTION | MESSAGE ─────
_FMT_FILE = "%(asctime)s | %(levelname)-7s | %(filename)-18s | %(funcName)-22s | %(message)s"
_FMT_CONSOLE = "%(asctime)s | %(levelname)-7s | %(filename)-18s | %(funcName)-22s | %(message)s"
_DATEFMT_FILE = "%Y-%m-%d %H:%M:%S"
_DATEFMT_CONSOLE = "%H:%M:%S"

# ── ANSI colors ───────────────────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_COLORS = {
    TRACE:           "\033[90m",    # grey
    logging.DEBUG:   "\033[36m",    # cyan
    logging.INFO:    "\033[32m",    # green
    logging.WARNING: "\033[33m",    # yellow
    logging.ERROR:   "\033[91m",    # bright red
}


class _ColorFormatter(logging.Formatter):
    """Adds ANSI color codes to structured log output (console only)."""

    def format(self, record):
        color = _COLORS.get(record.levelno, "")
        saved_levelname = record.levelname
        saved_msg = record.msg

        record.levelname = f"{color}{_BOLD}{saved_levelname:<7}{_RESET}"
        record.msg = f"{color}{record.msg}{_RESET}"
        out = super().format(record)

        # Dim the pipe separators for visual clarity
        out = out.replace(" | ", f" {_DIM}|{_RESET} ")

        record.levelname = saved_levelname
        record.msg = saved_msg
        return out


class Logger:
    """Structured logger: TIMESTAMP | LEVEL | FILE | FUNCTION | MESSAGE.

    Uses ``stacklevel=2`` so that ``%(filename)s`` and ``%(funcName)s``
    resolve to the *caller* of the Logger method, not the Logger wrapper.
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
        console.setFormatter(_ColorFormatter(_FMT_CONSOLE, datefmt=_DATEFMT_CONSOLE))
        root.addHandler(console)

        # ── File handler (daily rotation, plain text) ──────────────────
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            fh = TimedRotatingFileHandler(
                LOG_FILE,
                when="midnight",
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            fh.suffix = "%Y-%m-%d"    # rotated files: nfc_player.log.2026-04-09
            fh.setLevel(file_level)
            fh.setFormatter(logging.Formatter(_FMT_FILE, datefmt=_DATEFMT_FILE))
            root.addHandler(fh)
        except (PermissionError, OSError) as exc:
            root.warning("File logging disabled – cannot write to %s (%s)", LOG_FILE, exc)

        # Reduce noise from third-party libraries
        for name in ("spotipy", "urllib3", "httpcore", "httpx"):
            logging.getLogger(name).setLevel(logging.WARNING)

        cls._initialized = True

    # ── Instance ──────────────────────────────────────────────────────

    def __init__(self, name: str):
        Logger.setup()
        self._log = logging.getLogger(name)

    def trace(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._log.log(TRACE, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._log.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._log.info(msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._log.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        self._log.error(msg, *args, **kwargs)

"""Logging per maturity (rule 6): dev logs TRACE, experimental DEBUG, release INFO."""

import logging
from typing import TextIO

TRACE = 5
LEVELS = {"dev": TRACE, "experimental": logging.DEBUG, "release": logging.INFO}

logging.addLevelName(TRACE, "TRACE")

_FORMAT = "%(levelname)-7s | %(filename)s | %(funcName)s | %(message)s"
_HANDLER_NAME = "nfc_player"
_RESET = "\033[0m"
_COLORS = {
    TRACE: "\033[90m",  # grey
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[91m",  # bright red
    logging.CRITICAL: "\033[91m",
}


class _ColorFormatter(logging.Formatter):
    """Colours each line by its level; used on a terminal only."""

    def format(self, record: logging.LogRecord) -> str:
        return f"{_COLORS.get(record.levelno, '')}{super().format(record)}{_RESET}"


def setup_logging(maturity: str, stream: TextIO | None = None) -> None:
    """Send all logs to `stream` (default stderr) at the level of `maturity`.

    Calling it again replaces the previous setup. A terminal gets the time and colours;
    under systemd the journal adds the time itself.
    """
    if maturity not in LEVELS:
        raise ValueError(f"unknown maturity: {maturity!r}")
    handler = logging.StreamHandler(stream)
    handler.set_name(_HANDLER_NAME)
    if _is_tty(handler.stream):
        handler.setFormatter(_ColorFormatter("%(asctime)s | " + _FORMAT, datefmt="%H:%M:%S"))
    else:
        handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    for old in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)
    root.setLevel(LEVELS[maturity])
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())

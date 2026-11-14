"""Tests for nfc_player.core.log."""

import io
import logging
import re

import pytest

from nfc_player.core.log import TRACE, setup_logging

LOGGER = logging.getLogger("nfc_player.test_log")


class TtyStream(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def restore_logging():
    """Undo the global changes of setup_logging after each test."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    urllib3_level = logging.getLogger("urllib3").level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
    root.setLevel(level)
    logging.getLogger("urllib3").setLevel(urllib3_level)


def handlers_writing_to(stream):
    return [h for h in logging.getLogger().handlers if getattr(h, "stream", None) is stream]


def test_setup_logging_levels():
    stream = io.StringIO()
    setup_logging("dev", stream)
    assert logging.getLogger().level == 5
    setup_logging("experimental", stream)
    assert logging.getLogger().level == logging.DEBUG
    setup_logging("release", stream)
    assert logging.getLogger().level == 20
    assert len(handlers_writing_to(stream)) == 1


def test_setup_logging_twice_logs_each_record_once():
    stream = io.StringIO()
    setup_logging("release", stream)
    setup_logging("release", stream)
    LOGGER.info("hello")
    assert stream.getvalue().count("hello") == 1


def test_setup_logging_replaces_previous_stream():
    first, second = io.StringIO(), io.StringIO()
    setup_logging("release", first)
    setup_logging("release", second)
    LOGGER.info("hello")
    assert first.getvalue() == ""
    assert "hello" in second.getvalue()


def test_plain_format_without_tty():
    stream = io.StringIO()
    setup_logging("release", stream)
    LOGGER.warning("disk %s", "full")
    assert stream.getvalue() == "WARNING | test_log.py | test_plain_format_without_tty | disk full\n"


def test_tty_format_adds_time_and_colour():
    stream = TtyStream()
    setup_logging("release", stream)
    LOGGER.info("ready")
    out = stream.getvalue()
    assert "\x1b[" in out
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)
    assert re.fullmatch(
        r"\d\d:\d\d:\d\d \| INFO    \| test_log\.py \| test_tty_format_adds_time_and_colour \| ready\n", plain
    )


def test_trace_shown_only_in_dev():
    dev, experimental = io.StringIO(), io.StringIO()
    setup_logging("dev", dev)
    LOGGER.log(TRACE, "deep")
    setup_logging("experimental", experimental)
    LOGGER.log(TRACE, "deep")
    LOGGER.debug("debug line")
    assert dev.getvalue().startswith("TRACE   | ")
    assert "deep" not in experimental.getvalue()
    assert "debug line" in experimental.getvalue()


def test_release_hides_debug():
    stream = io.StringIO()
    setup_logging("release", stream)
    LOGGER.debug("hidden")
    assert stream.getvalue() == ""


def test_urllib3_is_quiet_even_in_dev():
    stream = io.StringIO()
    setup_logging("dev", stream)
    logging.getLogger("urllib3.connectionpool").info("noise")
    assert stream.getvalue() == ""


def test_unknown_maturity_raises():
    with pytest.raises(ValueError):
        setup_logging("beta", io.StringIO())

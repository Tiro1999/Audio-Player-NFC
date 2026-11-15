"""PN532 reader over I2C: tag polling, fast NTAG memory reads and removal detection.

The hardware libraries (board, busio, adafruit_pn532) are imported in open_reader() only,
so everything else runs without them.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from nfc_player.nfc.ndef import scan_ndef_tlv

log = logging.getLogger(__name__)

_CC_PAGE = 3  # capability container; the user memory follows from page 4
_PAGES_PER_READ = 4  # one READ returns 16 bytes = 4 pages
_BLOCK_SIZE = 16
_CC_MAGIC = 0xE1  # NDEF-formatted tag
_DEFAULT_CAPACITY = 144  # NTAG213, the smallest NTAG21x
_RETRY_DELAY = 0.15  # seconds between read passes


class ReaderError(Exception):
    """The reader does not respond as expected; reopening it may help."""


@dataclass(frozen=True)
class TagRead:
    """A tag on the reader: UID in upper-case hex, memory from page 4 (None if unreadable)."""

    uid: str
    memory: bytes | None


def read_capacity(cc: bytes) -> int:
    """Data area size in bytes from the capability container (page 3); 144 if not NDEF-formatted."""
    if len(cc) >= 3 and cc[0] == _CC_MAGIC:
        return cc[2] * 8
    return _DEFAULT_CAPACITY


class Pn532Reader:
    """Tag access through an adafruit_pn532 object (or a fake with the same methods)."""

    def __init__(self, pn532: Any) -> None:
        self._pn532 = pn532

    def wait_for_tag(self, timeout: float = 0.5) -> str | None:
        """UID of the tag on the reader in upper-case hex; None if none shows up within `timeout` s."""
        try:
            uid = self._pn532.read_passive_target(timeout=timeout)
        except Exception as exc:
            raise ReaderError(f"tag poll failed: {exc!r}") from exc
        return bytes(uid).hex().upper() if uid else None

    def read_memory(self, retries: int = 3) -> bytes | None:
        """Tag memory from page 4 until the NDEF message is complete, at most the tag capacity.

        A failed read restarts the pass, up to `retries` times. If no pass completes, the longest
        partial data is returned (e.g. tag removed mid-read), None if nothing could be read.
        """
        best = b""
        for attempt in range(1 + retries):
            if attempt:
                time.sleep(_RETRY_DELAY)
            data = bytearray()
            try:
                self._read_pass(data)
            except Exception as exc:
                # Lengths and exception types only: never tag content (S1).
                log.debug(
                    "tag read failed after %d bytes (pass %d of %d): %s",
                    len(data),
                    attempt + 1,
                    1 + retries,
                    type(exc).__name__,
                )
                best = max(best, bytes(data), key=len)
                continue
            log.debug("tag memory read: %d bytes, NDEF TLV %s", len(data), scan_ndef_tlv(data).status)
            return bytes(data)
        return best or None

    def wait_for_removal(
        self,
        stop: threading.Event,
        *,
        poll_interval: float = 0.3,
        timeout: float = 0.5,
        misses_needed: int = 3,
    ) -> None:
        """Block until `misses_needed` polls in a row see no tag, or until `stop` is set.

        A read error counts as a miss. The reader is reset at the end so that it finds the next tag.
        """
        misses = 0
        while misses < misses_needed and not stop.is_set():
            try:
                present = bool(self._pn532.read_passive_target(timeout=timeout))
            except Exception as exc:
                log.debug("removal check: read error counts as a miss: %r", exc)
                present = False
            misses = 0 if present else misses + 1
            if misses:
                log.debug("removal check: miss %d of %d", misses, misses_needed)
            stop.wait(poll_interval)
        self.reset()

    def reset(self) -> None:
        """SAM configuration clears the PN532 target list; after memory reads it may miss new tags."""
        try:
            self._pn532.SAM_configuration()
        except Exception as exc:
            log.debug("reader reset failed: %r", exc)

    def _read_pass(self, data: bytearray) -> None:
        """Append tag memory from page 4 to `data`; a failed read raises and leaves what was read."""
        block = self._read_block(_CC_PAGE)
        capacity = read_capacity(block[:4])
        data += block[4:]
        page = _CC_PAGE + _PAGES_PER_READ
        while not _is_complete(data, capacity):
            data += self._read_block(page)
            page += _PAGES_PER_READ
        del data[capacity:]

    def _read_block(self, page: int) -> bytes:
        """16 bytes (4 pages) from `page`; ReaderError if the reader returns no full block."""
        block = self._pn532.mifare_classic_read_block(page)
        if block is None or len(block) != _BLOCK_SIZE:
            raise ReaderError(f"no data from page {page}")
        return bytes(block)


def _is_complete(data: bytes, capacity: int) -> bool:
    """True once the NDEF message is read completely, there is none, or the capacity is reached."""
    if len(data) >= capacity:
        return True
    scan = scan_ndef_tlv(data)
    return scan.status == "absent" or (scan.status == "found" and len(data) >= scan.end)


def open_reader() -> Pn532Reader:
    """Connect to the PN532 over I2C and configure it; ReaderError if it is not available."""
    try:
        # Hardware libraries exist on the Pi only.
        import board
        import busio
        from adafruit_pn532.i2c import PN532_I2C

        pn532 = PN532_I2C(busio.I2C(board.SCL, board.SDA), debug=False)
        ic, version, revision, _support = pn532.firmware_version
        log.info("reader found: PN532 firmware %d.%d (IC 0x%02X)", version, revision, ic)
        pn532.SAM_configuration()
    except Exception as exc:
        raise ReaderError(f"reader not available: {exc!r}") from exc
    return Pn532Reader(pn532)

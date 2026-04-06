"""PN532 NFC tag reader over I2C.

Supports two modes for resolving Spotify URIs:
  1. NDEF – read a URI/Text record written to the tag
  2. UID  – use the tag's unique ID to look up a URI in config.json
"""

import logging
import re
import time

logger = logging.getLogger(__name__)

# Lazy imports – these are only available on the Pi
_pn532 = None

SPOTIFY_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(track|album|playlist|artist|episode|show)/([a-zA-Z0-9]+)"
)


def _init_pn532():
    """Initialize the PN532 over I2C (lazy, so import errors don't crash tests)."""
    global _pn532
    if _pn532 is not None:
        return _pn532

    import board
    import busio
    from adafruit_pn532.i2c import PN532_I2C

    i2c = busio.I2C(board.SCL, board.SDA)
    pn532 = PN532_I2C(i2c, debug=False)
    ic, ver, rev, support = pn532.firmware_version
    logger.info("PN532 firmware v%d.%d (IC 0x%x)", ver, rev, ic)
    pn532.SAM_configuration()
    _pn532 = pn532
    return pn532


def spotify_url_to_uri(url):
    """Convert 'https://open.spotify.com/playlist/xxx' → 'spotify:playlist:xxx'."""
    m = SPOTIFY_URL_RE.match(url)
    if m:
        return f"spotify:{m.group(1)}:{m.group(2)}"
    if url.startswith("spotify:"):
        return url
    return None


# ---------------------------------------------------------------------------
# NDEF helpers (NTAG213 / 215 / 216)
# ---------------------------------------------------------------------------

def _read_tag_user_memory(pn532, max_pages=40):
    """Read user memory pages (4+) from an NTAG2xx tag."""
    data = bytearray()
    for page in range(4, 4 + max_pages):
        try:
            block = pn532.ntag2xx_read_block(page)
            if block is None:
                break
            data.extend(block)
        except Exception:
            break
    return bytes(data)


def _extract_ndef_uri(raw):
    """
    Minimal NDEF TLV + URI-record parser.
    Handles the common case of a single NDEF URI or Text record written by a
    phone NFC-writer app.  Falls back to ndeflib when available.
    """
    try:
        import ndef as ndeflib

        # Strip leading TLV wrapper if present (type 0x03)
        start = 0
        if raw and raw[0] == 0x03:
            length = raw[1]
            start = 2
            if length == 0xFF:
                length = int.from_bytes(raw[2:4], "big")
                start = 4
            raw = raw[start : start + length]

        for record in ndeflib.message_decoder(raw):
            uri = None
            if hasattr(record, "uri"):
                uri = record.uri
            elif hasattr(record, "text"):
                uri = record.text
            if uri:
                converted = spotify_url_to_uri(uri)
                if converted:
                    return converted
    except Exception as exc:
        logger.debug("NDEF parse failed (%s), falling back to UID", exc)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class NFCReader:
    def __init__(self):
        self.pn532 = _init_pn532()

    def wait_for_tag(self, timeout=0.5):
        """Block until a tag is present. Returns UID hex string or None on timeout."""
        uid = self.pn532.read_passive_target(timeout=timeout)
        if uid is None:
            return None
        return uid.hex().upper()

    def read_spotify_uri(self, uid_hex, nfc_tags_map):
        """
        Try to resolve a Spotify URI for the current tag.

        1. Attempt to read NDEF data from the tag.
        2. Fall back to UID → URI mapping from config.
        """
        # 1. NDEF
        try:
            raw = _read_tag_user_memory(self.pn532)
            if raw:
                uri = _extract_ndef_uri(raw)
                if uri:
                    logger.info("NDEF URI found: %s", uri)
                    return uri
        except Exception as exc:
            logger.debug("NDEF read failed: %s", exc)

        # 2. UID lookup
        uri = nfc_tags_map.get(uid_hex)
        if uri:
            logger.info("UID %s → %s (config lookup)", uid_hex, uri)
            return spotify_url_to_uri(uri) or uri
        return None

    def wait_for_removal(self, poll_interval=0.3, timeout=0.5):
        """Block until the tag is removed from the reader."""
        while True:
            uid = self.pn532.read_passive_target(timeout=timeout)
            if uid is None:
                return
            time.sleep(poll_interval)

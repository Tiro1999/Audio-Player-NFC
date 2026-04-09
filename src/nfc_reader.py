"""PN532 NFC tag reader over I2C.

Supports two modes for resolving Spotify URIs:
  1. NDEF – read a URI/Text record written to the tag
  2. UID  – use the tag's unique ID to look up a URI in config.json
"""

import re
import time
from urllib.parse import urlparse

from .logger import Logger

logger = Logger(__name__)

# Lazy imports – these are only available on the Pi
_pn532 = None

SPOTIFY_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(track|album|playlist|artist|episode|show|audiobook|chapter)/([a-zA-Z0-9]+)"
)


def _init_pn532():
    """Initialize the PN532 over I2C (lazy, so import errors don't crash tests)."""
    global _pn532

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


def is_valid_spotify_uri(uri):
    """Validate that *uri* points to a genuine Spotify resource.

    Accepts:
      • ``spotify:track:xxx``, ``spotify:playlist:xxx``, …
      • ``https://open.spotify.com/track/xxx``

    Rejects everything else (security: prevents arbitrary URL injection).
    """
    if not uri or not isinstance(uri, str):
        return False
    # Native Spotify URI
    if re.match(
        r"^spotify:(track|album|playlist|artist|episode|show|audiobook|chapter):[a-zA-Z0-9]+$", uri
    ):
        return True
    # Spotify web URL – strict hostname check
    try:
        parsed = urlparse(uri)
        return (
            parsed.scheme in ("http", "https")
            and parsed.hostname == "open.spotify.com"
            and bool(re.match(
                r"^/(track|album|playlist|artist|episode|show|audiobook|chapter)/[a-zA-Z0-9]+",
                parsed.path,
            ))
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# NDEF helpers (NTAG213 / 215 / 216)
# ---------------------------------------------------------------------------

def _read_tag_user_memory(pn532, max_pages=40, retries=3):
    """Read user memory pages (4+) from an NTAG2xx tag.

    Retries on short reads which can happen when the tag is not yet
    stable on the reader (I2C bus timing issues).
    """
    best_data = b""
    for attempt in range(retries):
        data = bytearray()
        for page in range(4, 4 + max_pages):
            try:
                block = pn532.ntag2xx_read_block(page)
                if block is None:
                    break
                data.extend(block)
            except Exception:
                break
        if len(data) > len(best_data):
            best_data = bytes(data)
        # If we got a reasonable amount, accept it
        if len(data) >= 64:
            break
        if attempt < retries - 1:
            logger.debug("Short read (%d bytes), retrying…", len(data))
            time.sleep(0.15)

    logger.trace("Read %d bytes of tag user memory", len(best_data))
    return best_data


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
# WiFi NDEF helpers
# ---------------------------------------------------------------------------

def _strip_ndef_tlv(raw):
    """Strip NDEF Message TLV wrapper (type 0x03) if present."""
    if raw and raw[0] == 0x03:
        length = raw[1]
        start = 2
        if length == 0xFF:
            length = int.from_bytes(raw[2:4], "big")
            start = 4
        return raw[start:start + length]
    return raw


def _parse_wifi_string(text):
    """Parse 'WIFI:T:WPA;S:MySSID;P:MyPass;;' → dict or None.

    Supports the Wi-Fi Simple Configuration string format.
    Fields can appear in any order; backslash-escaped special characters.
    """
    text = text.strip()
    if not text.upper().startswith("WIFI:"):
        return None

    body = text[5:]
    fields = {}

    # Split on unescaped semicolons
    i = 0
    current = ""
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            current += body[i + 1]
            i += 2
        elif body[i] == ";":
            if ":" in current:
                key, _, value = current.partition(":")
                fields[key.upper()] = value
            current = ""
            i += 1
        else:
            current += body[i]
            i += 1

    if current and ":" in current:
        key, _, value = current.partition(":")
        fields[key.upper()] = value

    ssid = fields.get("S")
    if not ssid:
        return None

    return {
        "type": "wifi",
        "ssid": ssid,
        "password": fields.get("P", ""),
        "security": fields.get("T", "WPA"),
        "hidden": fields.get("H", "false").lower() == "true",
    }


def _extract_tag_data(raw):
    """Parse NDEF records and return structured tag data.

    Returns one of:
        {"type": "wifi", "ssid": ..., "password": ..., "security": ..., "hidden": ...}
        {"type": "spotify", "uri": "spotify:..."}
        None
    """
    try:
        import ndef as ndeflib

        raw = _strip_ndef_tlv(raw)
        records = list(ndeflib.message_decoder(raw))

        # First pass: WiFi records (WSC MIME or text/URI with WIFI: prefix)
        for record in records:
            if hasattr(record, "credential") and record.credential:
                cred = record.credential[0]
                ssid = getattr(cred, "network_name", "") or ""
                key = getattr(cred, "network_key", "") or ""
                if ssid:
                    return {
                        "type": "wifi",
                        "ssid": ssid,
                        "password": key,
                        "security": "WPA",
                        "hidden": False,
                    }

            text = None
            if hasattr(record, "text"):
                text = record.text
            elif hasattr(record, "uri"):
                text = record.uri
            if text and text.strip().upper().startswith("WIFI:"):
                result = _parse_wifi_string(text)
                if result:
                    return result

        # Second pass: Spotify records
        for record in records:
            uri = None
            if hasattr(record, "uri"):
                uri = record.uri
            elif hasattr(record, "text"):
                uri = record.text
            if uri:
                converted = spotify_url_to_uri(uri)
                if converted:
                    return {"type": "spotify", "uri": converted}

    except Exception as exc:
        logger.debug("NDEF parse failed (%s)", exc)

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class NFCReader:
    def __init__(self):
        self.pn532 = _init_pn532()

    def wait_for_tag(self, timeout=0.5):
        """Block until a tag is present. Returns UID hex string or None on timeout.

        Raises OSError on persistent I2C failures so the caller can re-init.
        """
        uid = self.pn532.read_passive_target(timeout=timeout)
        if uid is None:
            return None
        return uid.hex().upper()

    def read_spotify_uri(self, uid_hex, nfc_tags_map):
        """
        Try to resolve a Spotify URI for the current tag.

        1. Attempt to read NDEF data from the tag.
        2. Fall back to UID → URI mapping from config.
        3. Validate that the result is a genuine Spotify URI.
        """
        # 1. NDEF
        try:
            raw = _read_tag_user_memory(self.pn532)
            if raw:
                logger.trace("Raw NDEF (%d bytes): %s…", len(raw), raw[:64].hex())
                uri = _extract_ndef_uri(raw)
                if uri:
                    if not is_valid_spotify_uri(uri):
                        logger.warn("NDEF URI rejected (not a Spotify link): %s", uri)
                        return None
                    logger.info("NDEF URI: %s", uri)
                    return uri
        except Exception as exc:
            logger.debug("NDEF read failed: %s", exc)

        # 2. UID lookup
        uri = nfc_tags_map.get(uid_hex)
        if uri:
            resolved = spotify_url_to_uri(uri) or uri
            if not is_valid_spotify_uri(resolved):
                logger.warn("Config URI rejected (not a Spotify link): %s", resolved)
                return None
            logger.info("UID %s → %s (config lookup)", uid_hex, resolved)
            return resolved

        logger.debug("No URI mapping for tag %s", uid_hex)
        return None

    def read_tag(self, uid_hex, nfc_tags_map):
        """Read tag and return an action dict, or None.

        Returns one of:
            {"type": "spotify", "uri": "spotify:track:xxx"}
            {"type": "wifi", "ssid": "...", "password": "...", ...}
            None
        """
        # 1. NDEF
        try:
            raw = _read_tag_user_memory(self.pn532)
            if raw:
                logger.trace("Raw NDEF (%d bytes): %s…", len(raw), raw[:64].hex())
                data = _extract_tag_data(raw)
                if data:
                    if data["type"] == "wifi":
                        logger.info("📶 WiFi tag: SSID=%s", data["ssid"])
                        return data
                    if data["type"] == "spotify":
                        if not is_valid_spotify_uri(data["uri"]):
                            logger.warn("NDEF URI rejected (not Spotify): %s", data["uri"])
                            return None
                        logger.info("🎵 NDEF URI: %s", data["uri"])
                        return data
        except Exception as exc:
            logger.debug("NDEF read failed: %s", exc)

        # 2. UID lookup (Spotify only)
        uri = nfc_tags_map.get(uid_hex)
        if uri:
            resolved = spotify_url_to_uri(uri) or uri
            if not is_valid_spotify_uri(resolved):
                logger.warn("Config URI rejected (not Spotify): %s", resolved)
                return None
            logger.info("UID %s → %s (config)", uid_hex, resolved)
            return {"type": "spotify", "uri": resolved}

        logger.debug("No mapping for tag %s", uid_hex)
        return None

    def reset(self):
        """Reset the PN532 state machine so it can detect new tags.

        After reading NTAG memory blocks (ntag2xx_read_block), the PN532
        keeps the old target in its internal list.  Subsequent calls to
        read_passive_target may silently return None for every new tag.
        Calling SAM_configuration() clears the target list and puts the
        chip back into idle/scan mode.
        """
        try:
            self.pn532.SAM_configuration()
            logger.debug("PN532 reset (SAM_configuration)")
        except OSError as exc:
            logger.debug("PN532 reset failed: %s", exc)

    def wait_for_removal(self, poll_interval=0.3, timeout=0.5, consecutive_misses=3):
        """Block until the tag is removed from the reader.

        Requires multiple consecutive failed reads to avoid false positives
        caused by I2C bus glitches or brief contact loss.
        I2C errors count as a "miss" (tag likely moved away).

        After removal is confirmed the PN532 is reset via SAM_configuration
        so the next read_passive_target call can find a fresh tag.
        """
        misses = 0
        while misses < consecutive_misses:
            try:
                uid = self.pn532.read_passive_target(timeout=timeout)
            except OSError:
                uid = None  # treat I2C error as "tag gone"
            if uid is None:
                misses += 1
            else:
                misses = 0
            time.sleep(poll_interval)

        # Reset PN532 so it can detect the next tag
        self.reset()

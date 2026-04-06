"""NFC tag reader module.

Supports the MFRC522 RC522 reader module connected via SPI/GPIO (the most
common DIY choice for Raspberry Pi), and provides an NDEF URI / text parser
so Spotify links written to a tag by a phone are read automatically.

Tag resolution order
--------------------
1. If the raw NDEF payload contains a URI that looks like a Spotify resource
   (``spotify:`` scheme or ``open.spotify.com`` URL), that URI is used.
2. Otherwise the tag's UID (hex string, upper-case, no colons) is looked up
   in the ``nfc.tag_mappings`` dictionary from the config file.

Hardware note
-------------
The RC522 module must be wired to the Raspberry Pi SPI0 bus and CE0::

    RC522 Pin  →  RPi GPIO (BCM)
    ─────────────────────────────
    SDA        →  GPIO 8  (CE0)
    SCK        →  GPIO 11 (SCLK)
    MOSI       →  GPIO 10 (MOSI)
    MISO       →  GPIO 9  (MISO)
    GND        →  GND
    RST        →  GPIO 25
    3.3V       →  3.3 V

SPI must be enabled (``raspi-config`` → *Interface Options* → *SPI*).
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NDEF URI identifier codes (RFC 3986 / NFC Forum URI Record Type Definition)
# ---------------------------------------------------------------------------
_URI_PREFIXES = {
    0x00: "",
    0x01: "http://www.",
    0x02: "https://www.",
    0x03: "http://",
    0x04: "https://",
    0x05: "tel:",
    0x06: "mailto:",
    0x07: "ftp://anonymous:anonymous@",
    0x08: "ftp://ftp.",
    0x09: "ftps://",
    0x0A: "sftp://",
    0x0B: "smb://",
    0x0C: "nfs://",
    0x0D: "ftp://",
    0x0E: "dav://",
    0x0F: "news:",
    0x10: "telnet://",
    0x11: "imap:",
    0x12: "rtsp://",
    0x13: "urn:",
    0x14: "pop:",
    0x15: "sip:",
    0x16: "sips:",
    0x17: "tftp:",
    0x18: "btspp://",
    0x19: "btl2cap://",
    0x1A: "btgoep://",
    0x1B: "tcpobex://",
    0x1C: "irdaobex://",
    0x1D: "file://",
    0x1E: "urn:epc:id:",
    0x1F: "urn:epc:tag:",
    0x20: "urn:epc:pat:",
    0x21: "urn:epc:raw:",
    0x22: "urn:epc:",
    0x23: "urn:nfc:",
}


def _parse_ndef_records(raw_bytes: bytes) -> list[dict]:
    """Parse a sequence of NDEF records from *raw_bytes*.

    Returns a list of dicts with keys ``tnf``, ``type``, ``id``, ``payload``.
    Stops at a Message End record or when the buffer is exhausted.
    """
    records = []
    pos = 0
    while pos < len(raw_bytes):
        if pos >= len(raw_bytes):
            break
        header = raw_bytes[pos]
        pos += 1

        tnf = header & 0x07
        il = bool(header & 0x08)   # ID Length present
        sr = bool(header & 0x10)   # Short Record
        me = bool(header & 0x40)   # Message End

        if pos >= len(raw_bytes):
            break
        type_length = raw_bytes[pos]
        pos += 1

        if sr:
            if pos >= len(raw_bytes):
                break
            payload_length = raw_bytes[pos]
            pos += 1
        else:
            if pos + 4 > len(raw_bytes):
                break
            payload_length = int.from_bytes(raw_bytes[pos:pos + 4], "big")
            pos += 4

        id_length = 0
        if il:
            if pos >= len(raw_bytes):
                break
            id_length = raw_bytes[pos]
            pos += 1

        if pos + type_length > len(raw_bytes):
            break
        record_type = raw_bytes[pos:pos + type_length]
        pos += type_length

        record_id = b""
        if id_length:
            record_id = raw_bytes[pos:pos + id_length]
            pos += id_length

        if pos + payload_length > len(raw_bytes):
            break
        payload = raw_bytes[pos:pos + payload_length]
        pos += payload_length

        records.append({
            "tnf": tnf,
            "type": record_type,
            "id": record_id,
            "payload": payload,
        })

        if me:
            break

    return records


def _extract_spotify_uri_from_ndef(raw_bytes: bytes) -> Optional[str]:
    """Return the first Spotify URI found in *raw_bytes* NDEF data, or *None*.

    Recognises:
    * Well-known URI records (TNF=0x01, Type=b'U') that expand to a Spotify
      URL or ``spotify:`` scheme URI.
    * Well-known Text records (TNF=0x01, Type=b'T') whose text starts with
      ``spotify:``.
    * External type records (TNF=0x04) with a Spotify payload.
    """
    try:
        records = _parse_ndef_records(raw_bytes)
    except Exception:  # noqa: BLE001
        return None

    for rec in records:
        tnf = rec["tnf"]
        rtype = rec["type"]
        payload = rec["payload"]

        if tnf == 0x01 and rtype == b"U":
            # URI record
            if not payload:
                continue
            prefix_code = payload[0]
            prefix = _URI_PREFIXES.get(prefix_code, "")
            uri = prefix + payload[1:].decode("utf-8", errors="replace")
            if _is_spotify_uri(uri):
                return _normalise_spotify_uri(uri)

        elif tnf == 0x01 and rtype == b"T":
            # Text record: skip language code (first byte = length of lang)
            if not payload:
                continue
            lang_len = payload[0] & 0x3F
            text = payload[1 + lang_len:].decode("utf-8", errors="replace")
            if _is_spotify_uri(text):
                return _normalise_spotify_uri(text)

    return None


def _is_spotify_uri(text: str) -> bool:
    return text.startswith("spotify:") or "open.spotify.com/" in text


def _normalise_spotify_uri(text: str) -> str:
    """Convert an ``open.spotify.com`` URL to a ``spotify:`` URI if needed."""
    if text.startswith("spotify:"):
        return text
    # https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
    # → spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
    try:
        path = text.split("open.spotify.com/", 1)[1].split("?")[0]
        parts = path.strip("/").split("/")
        if len(parts) >= 2:
            return "spotify:" + ":".join(parts[:2])
    except (IndexError, AttributeError):
        pass
    return text


class NFCReader:
    """High-level NFC tag reader backed by the MFRC522 hardware module.

    Parameters
    ----------
    tag_mappings:
        Dict mapping upper-case hex UID strings to Spotify URIs.  Used when
        no NDEF URI can be found on the tag itself.
    """

    def __init__(self, tag_mappings: dict | None = None) -> None:
        self._tag_mappings: dict = tag_mappings or {}
        self._reader = None
        self._last_uid: str = ""

    def _get_reader(self):
        """Import and return the SimpleMFRC522 reader (lazy import)."""
        if self._reader is None:
            from mfrc522 import SimpleMFRC522  # type: ignore[import]
            self._reader = SimpleMFRC522()
        return self._reader

    def read_tag(self) -> Optional[str]:
        """Block until an NFC tag is presented; return its Spotify URI or *None*.

        Returns *None* when the tag is recognised but carries no Spotify link
        and has no matching UID mapping.  Ignores repeated reads of the same
        tag until the tag is removed and re-presented (debounce).
        """
        reader = self._get_reader()
        logger.debug("Waiting for NFC tag…")

        uid_int, raw_text = reader.read()
        uid_hex = format(uid_int, "08X").upper()

        if uid_hex == self._last_uid:
            logger.debug("Same tag (%s) still present – ignoring.", uid_hex)
            return None

        self._last_uid = uid_hex
        logger.info("Tag detected: UID=%s", uid_hex)

        # 1. Try to parse NDEF data from the text payload bytes
        if raw_text:
            raw_bytes = raw_text.encode("latin-1") if isinstance(raw_text, str) else raw_text
            uri = _extract_spotify_uri_from_ndef(raw_bytes)
            if uri:
                logger.info("NDEF Spotify URI: %s", uri)
                return uri

        # 2. Fall back to configured UID → URI mapping
        if uid_hex in self._tag_mappings:
            uri = self._tag_mappings[uid_hex]
            logger.info("UID mapping → %s", uri)
            return uri

        logger.warning("Tag %s has no Spotify URI and no UID mapping.", uid_hex)
        return None

    def clear_last_uid(self) -> None:
        """Reset debounce state so the next read always triggers an action."""
        self._last_uid = ""

    def wait_for_tag_removal(self, poll_interval: float = 0.5) -> None:
        """Poll until the current tag is no longer present.

        This is a best-effort helper; the MFRC522 ``read`` is a blocking call
        so removal detection here just waits a fixed interval.
        """
        time.sleep(poll_interval)
        self._last_uid = ""

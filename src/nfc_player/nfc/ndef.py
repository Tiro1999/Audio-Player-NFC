"""NDEF message in tag memory: TLV walker (NFC Forum Type 2 tags) and record decoding (ndeflib)."""

import logging
from dataclasses import dataclass
from typing import Literal

import ndef

log = logging.getLogger(__name__)

_NULL = 0x00  # padding, a single byte
_NDEF = 0x03
_SKIPPED = frozenset({0x01, 0x02, 0xFD})  # Lock Control, Memory Control, Proprietary
_LONG_LENGTH = 0xFF  # followed by a 2-byte big-endian length


@dataclass(frozen=True)
class TlvScan:
    """Outcome of scan_ndef_tlv; for "found", data[start:end] is the NDEF message."""

    status: Literal["need_more", "found", "absent"]
    start: int = 0
    end: int = 0


def scan_ndef_tlv(data: bytes) -> TlvScan:
    """Walk the TLV blocks of tag memory (from page 4) to the NDEF message TLV.

    "need_more": the data ends before the NDEF TLV header; "absent": a terminator or a
    reserved TLV type comes first. "found" does not check that the message is complete.
    """
    offset = 0
    while offset < len(data):
        tlv_type = data[offset]
        if tlv_type == _NULL:
            offset += 1
            continue
        if tlv_type != _NDEF and tlv_type not in _SKIPPED:
            return TlvScan("absent")  # terminator 0xFE, or a reserved type: no usable TLV structure
        length_field = _read_length(data, offset + 1)
        if length_field is None:
            break
        size, value_start = length_field
        if tlv_type == _NDEF:
            return TlvScan("found", value_start, value_start + size)
        offset = value_start + size
    return TlvScan("need_more")


def _read_length(data: bytes, offset: int) -> tuple[int, int] | None:
    """(length, value offset) of the TLV length field at `offset`; None if it is cut off."""
    if offset >= len(data):
        return None
    if data[offset] != _LONG_LENGTH:
        return data[offset], offset + 1
    if offset + 3 > len(data):
        return None
    return int.from_bytes(data[offset + 1 : offset + 3], "big"), offset + 3


def extract_ndef_message(data: bytes) -> bytes | None:
    """The NDEF message in tag memory; None if it is absent or not read completely."""
    scan = scan_ndef_tlv(data)
    if scan.status == "found" and len(data) >= scan.end:
        return bytes(data[scan.start : scan.end])
    return None


def decode_records(message: bytes) -> list:
    """ndef.Record objects of an NDEF message; [] if it cannot be decoded."""
    try:
        return list(ndef.message_decoder(message, errors="relax"))
    except Exception as exc:
        # Type name only: decoder messages may quote tag content.
        log.debug("NDEF message of %d bytes not decodable: %s", len(message), type(exc).__name__)
        return []

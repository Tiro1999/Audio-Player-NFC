"""Tests for nfc_player.nfc.ndef: TLV walker and NDEF record decoding."""

import logging

import ndef
import pytest

from nfc_player.nfc.ndef import TlvScan, decode_records, extract_ndef_message, scan_ndef_tlv

SPOTIFY_URL = "https://open.spotify.com/track/abc"
SPOTIFY_MESSAGE = b"".join(ndef.message_encoder([ndef.UriRecord(SPOTIFY_URL)]))
SHORT_MESSAGE = b"".join(ndef.message_encoder([ndef.UriRecord("https://abc.de")]))  # 11 bytes


def test_scan_ntag213_factory_lock_tlv():
    assert len(SHORT_MESSAGE) == 0x0B
    data = bytes.fromhex("0103A00C34 030B") + SHORT_MESSAGE + b"\xfe"
    assert scan_ndef_tlv(data) == TlvScan("found", start=7, end=18)


def test_scan_ntag215_plain():
    data = bytes([0x03, len(SPOTIFY_MESSAGE)]) + SPOTIFY_MESSAGE + b"\xfe"
    assert scan_ndef_tlv(data) == TlvScan("found", start=2, end=2 + len(SPOTIFY_MESSAGE))


def test_scan_three_byte_length():
    assert scan_ndef_tlv(bytes.fromhex("03FF012C")) == TlvScan("found", start=4, end=4 + 300)


def test_scan_terminator_first_absent():
    data = b"\xfe" + bytes([0x03, len(SHORT_MESSAGE)]) + SHORT_MESSAGE
    assert scan_ndef_tlv(data).status == "absent"


def test_scan_null_padding():
    data = b"\x00\x00" + bytes([0x03, len(SHORT_MESSAGE)]) + SHORT_MESSAGE + b"\xfe"
    assert scan_ndef_tlv(data) == TlvScan("found", start=4, end=4 + len(SHORT_MESSAGE))


@pytest.mark.parametrize(
    "data",
    [b"\x03", b"", b"\x00\x00", bytes.fromhex("03FF01"), bytes.fromhex("0103A00C")],
    ids=["type only", "empty", "null padding only", "long length cut", "lock tlv cut"],
)
def test_scan_truncated_header_need_more(data):
    assert scan_ndef_tlv(data) == TlvScan("need_more")


def test_scan_skips_memory_control_and_proprietary_tlv():
    # Memory Control TLV with a 1-byte length, Proprietary TLV with a 3-byte length.
    data = bytes.fromhex("0203F00203 FDFF0002AAAA 030B") + SHORT_MESSAGE
    assert scan_ndef_tlv(data) == TlvScan("found", start=13, end=24)


@pytest.mark.parametrize("tlv_type", [0x04, 0x80, 0xFC, 0xFF])
def test_scan_reserved_type_absent(tlv_type):
    data = bytes([tlv_type, 0x01, 0x00, 0x03, len(SHORT_MESSAGE)]) + SHORT_MESSAGE
    assert scan_ndef_tlv(data).status == "absent"


def test_extract_returns_message():
    tlv = bytes([0x03, len(SPOTIFY_MESSAGE)]) + SPOTIFY_MESSAGE + b"\xfe"
    assert extract_ndef_message(bytes.fromhex("0103A00C34") + tlv + bytes(8)) == SPOTIFY_MESSAGE


def test_extract_returns_none_when_value_incomplete():
    data = bytes([0x03, len(SPOTIFY_MESSAGE)]) + SPOTIFY_MESSAGE[:-1]
    assert extract_ndef_message(data) is None


def test_decode_records_uri():
    records = decode_records(SPOTIFY_MESSAGE)
    assert len(records) == 1
    assert records[0].uri == SPOTIFY_URL


@pytest.mark.parametrize("message", [b"\xff\xff\xff\xff", SPOTIFY_MESSAGE[:-3]], ids=["garbage", "truncated"])
def test_decode_records_garbage_empty(message, caplog):
    caplog.set_level(logging.DEBUG, logger="nfc_player.nfc")
    assert decode_records(message) == []
    assert [record.levelno for record in caplog.records] == [logging.DEBUG]


def test_decode_records_tolerates_missing_message_flags():
    # Some writer apps leave the message begin and end flags unset.
    message = bytes([SPOTIFY_MESSAGE[0] & 0x3F]) + SPOTIFY_MESSAGE[1:]
    assert [record.uri for record in decode_records(message)] == [SPOTIFY_URL]

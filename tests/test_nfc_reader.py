"""Tests for src/nfc_reader.py."""

from unittest.mock import MagicMock, patch

import pytest

from src.nfc_reader import (
    NFCReader,
    _extract_spotify_uri_from_ndef,
    _is_spotify_uri,
    _normalise_spotify_uri,
    _parse_ndef_records,
)


# ── NDEF record parsing ────────────────────────────────────────────────────────

def _make_uri_record(uri: str, prefix_code: int = 0x00, *, message_begin: bool = True, message_end: bool = True) -> bytes:
    """Build a minimal well-known URI NDEF record byte sequence."""
    record_type = b"U"
    payload = bytes([prefix_code]) + uri.encode("utf-8")

    header = 0x00
    if message_begin:
        header |= 0x80
    if message_end:
        header |= 0x40
    header |= 0x10  # short record (SR)
    header |= 0x01  # TNF = Well Known

    return bytes([header, len(record_type), len(payload)]) + record_type + payload


def _make_text_record(text: str, lang: str = "en") -> bytes:
    """Build a minimal well-known Text NDEF record byte sequence."""
    record_type = b"T"
    lang_bytes = lang.encode("ascii")
    status_byte = len(lang_bytes)  # UTF-8, lang length
    payload = bytes([status_byte]) + lang_bytes + text.encode("utf-8")

    header = 0xD1  # MB | ME | SR | TNF=Well Known
    return bytes([header, len(record_type), len(payload)]) + record_type + payload


class TestParseNdefRecords:
    def test_parses_single_uri_record(self):
        raw = _make_uri_record("spotify:track:abc123")
        records = _parse_ndef_records(raw)
        assert len(records) == 1
        assert records[0]["tnf"] == 0x01
        assert records[0]["type"] == b"U"

    def test_parses_text_record(self):
        raw = _make_text_record("spotify:album:xyz789")
        records = _parse_ndef_records(raw)
        assert len(records) == 1
        assert records[0]["type"] == b"T"

    def test_empty_bytes_returns_empty_list(self):
        assert _parse_ndef_records(b"") == []

    def test_truncated_bytes_does_not_raise(self):
        # Should return an empty list or partial result without raising
        result = _parse_ndef_records(b"\xD1")  # header only
        assert isinstance(result, list)


# ── URI helpers ───────────────────────────────────────────────────────────────

class TestIsSpotifyUri:
    @pytest.mark.parametrize("uri", [
        "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        "spotify:album:1DFixLWuPkv3KT3TnV35m3",
        "spotify:track:4uLU6hMCjMI75M1A2tKUQC",
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "http://open.spotify.com/album/123",
    ])
    def test_returns_true_for_spotify_uris(self, uri):
        assert _is_spotify_uri(uri) is True

    @pytest.mark.parametrize("uri", [
        "https://www.google.com",
        "http://example.com",
        "https://music.apple.com/playlist/abc",
        "https://evil.open.spotify.com/track/abc",  # subdomain attack
        "https://notopen.spotify.com/track/abc",    # different domain
        "",
    ])
    def test_returns_false_for_non_spotify_uris(self, uri):
        assert _is_spotify_uri(uri) is False


class TestNormaliseSpotifyUri:
    def test_spotify_scheme_unchanged(self):
        uri = "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
        assert _normalise_spotify_uri(uri) == uri

    def test_https_url_converted_to_uri(self):
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        result = _normalise_spotify_uri(url)
        assert result == "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"

    def test_url_with_query_string_stripped(self):
        url = "https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3?si=abc"
        result = _normalise_spotify_uri(url)
        assert result == "spotify:album:1DFixLWuPkv3KT3TnV35m3"

    def test_track_url_converted(self):
        url = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
        result = _normalise_spotify_uri(url)
        assert result == "spotify:track:4uLU6hMCjMI75M1A2tKUQC"


# ── NDEF Spotify URI extraction ───────────────────────────────────────────────

class TestExtractSpotifyUriFromNdef:
    def test_extracts_spotify_scheme_uri_record(self):
        raw = _make_uri_record("spotify:playlist:abc123")
        result = _extract_spotify_uri_from_ndef(raw)
        assert result == "spotify:playlist:abc123"

    def test_extracts_https_prefix_uri_record(self):
        # prefix code 0x04 = "https://"
        raw = _make_uri_record("open.spotify.com/track/XYZ", prefix_code=0x04)
        result = _extract_spotify_uri_from_ndef(raw)
        assert result == "spotify:track:XYZ"

    def test_extracts_spotify_text_record(self):
        raw = _make_text_record("spotify:album:TEST123")
        result = _extract_spotify_uri_from_ndef(raw)
        assert result == "spotify:album:TEST123"

    def test_returns_none_for_non_spotify_record(self):
        raw = _make_uri_record("https://www.google.com")
        result = _extract_spotify_uri_from_ndef(raw)
        assert result is None

    def test_returns_none_for_garbage_bytes(self):
        result = _extract_spotify_uri_from_ndef(b"\xFF\xFF\xFF\xFF")
        assert result is None

    def test_returns_none_for_empty_bytes(self):
        result = _extract_spotify_uri_from_ndef(b"")
        assert result is None


# ── NFCReader ─────────────────────────────────────────────────────────────────

class TestNFCReader:
    def _make_reader(self, tag_mappings=None):
        return NFCReader(tag_mappings=tag_mappings or {})

    def _mock_mfrc522_read(self, reader_obj, uid_int: int, raw_text: str):
        """Patch the internal SimpleMFRC522 to return *(uid_int, raw_text)*."""
        mock_hw = MagicMock()
        mock_hw.read.return_value = (uid_int, raw_text)
        reader_obj._reader = mock_hw

    def test_read_tag_returns_uri_from_uid_mapping(self):
        nfc = self._make_reader({"AABBCCDD": "spotify:playlist:HELLO"})
        self._mock_mfrc522_read(nfc, 0xAABBCCDD, "")
        result = nfc.read_tag()
        assert result == "spotify:playlist:HELLO"

    def test_read_tag_returns_uri_from_ndef_text(self):
        nfc = self._make_reader()
        raw = _make_text_record("spotify:album:NDEF_TEST")
        raw_str = raw.decode("latin-1")
        self._mock_mfrc522_read(nfc, 0x11223344, raw_str)
        result = nfc.read_tag()
        assert result == "spotify:album:NDEF_TEST"

    def test_read_tag_ndef_takes_priority_over_mapping(self):
        """NDEF data on the tag should override the UID mapping."""
        tag_mappings = {"11223344": "spotify:playlist:MAPPING_URI"}
        nfc = self._make_reader(tag_mappings)
        raw = _make_text_record("spotify:album:NDEF_URI")
        self._mock_mfrc522_read(nfc, 0x11223344, raw.decode("latin-1"))
        result = nfc.read_tag()
        assert result == "spotify:album:NDEF_URI"

    def test_read_tag_returns_none_for_unknown_uid_without_ndef(self):
        nfc = self._make_reader({})
        self._mock_mfrc522_read(nfc, 0xDEADBEEF, "")
        result = nfc.read_tag()
        assert result is None

    def test_debounce_same_tag_returns_none_on_repeat(self):
        nfc = self._make_reader({"AABBCCDD": "spotify:playlist:HELLO"})
        self._mock_mfrc522_read(nfc, 0xAABBCCDD, "")
        # First read returns URI
        assert nfc.read_tag() == "spotify:playlist:HELLO"
        # Second read of same tag returns None (debounce)
        assert nfc.read_tag() is None

    def test_clear_last_uid_resets_debounce(self):
        nfc = self._make_reader({"AABBCCDD": "spotify:playlist:HELLO"})
        self._mock_mfrc522_read(nfc, 0xAABBCCDD, "")
        nfc.read_tag()
        nfc.clear_last_uid()
        # After clearing, same tag should trigger again
        assert nfc.read_tag() == "spotify:playlist:HELLO"

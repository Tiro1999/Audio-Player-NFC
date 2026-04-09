"""Tests for URI validation – runnable on any machine (no Pi hardware needed)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.nfc_reader import (
    is_valid_spotify_uri,
    spotify_url_to_uri,
    _parse_wifi_string,
    _extract_tag_data,
)


# ── is_valid_spotify_uri ──────────────────────────────────────────────────

class TestIsValidSpotifyUri:
    """Only spotify:* URIs and open.spotify.com URLs must be accepted."""

    @pytest.mark.parametrize("uri", [
        "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
        "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        "spotify:album:6dVIqQ8qmQ5GBnJ9shOYGE",
        "spotify:artist:0OdUWJ0sBjDrqHygGUXeCF",
        "spotify:episode:512ojhOuo1ktJprKbVcKyQ",
        "spotify:show:2MAi0BvDc6GTFvKFPXnkCL",
        "spotify:audiobook:7iHfbu1YPACw6oZPAFJtqe",
        "spotify:chapter:0D5wENdkdwbqlrHoaJ9g29",
    ])
    def test_valid_native_uris(self, uri):
        assert is_valid_spotify_uri(uri) is True

    @pytest.mark.parametrize("url", [
        "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6",
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "http://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE",
        "https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF",
        "https://open.spotify.com/audiobook/7iHfbu1YPACw6oZPAFJtqe",
        "https://open.spotify.com/chapter/0D5wENdkdwbqlrHoaJ9g29",
    ])
    def test_valid_web_urls(self, url):
        assert is_valid_spotify_uri(url) is True

    @pytest.mark.parametrize("uri", [
        None,
        "",
        "https://evil.com/spotify.com/track/abc",
        "https://open.spotify.com.evil.com/track/abc",
        "https://example.com/playlist/abc",
        "ftp://open.spotify.com/track/abc",
        "spotify:invalid:abc",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://notspotify.com/track/abc123",
    ])
    def test_rejects_non_spotify(self, uri):
        assert is_valid_spotify_uri(uri) is False


# ── spotify_url_to_uri ────────────────────────────────────────────────────

class TestSpotifyUrlToUri:

    def test_playlist_url(self):
        assert spotify_url_to_uri(
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        ) == "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"

    def test_track_url(self):
        assert spotify_url_to_uri(
            "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6"
        ) == "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"

    def test_native_uri_passthrough(self):
        assert spotify_url_to_uri("spotify:album:abc123") == "spotify:album:abc123"

    def test_audiobook_url(self):
        assert spotify_url_to_uri(
            "https://open.spotify.com/audiobook/7iHfbu1YPACw6oZPAFJtqe"
        ) == "spotify:audiobook:7iHfbu1YPACw6oZPAFJtqe"

    def test_unknown_url_returns_none(self):
        assert spotify_url_to_uri("https://example.com/foo") is None


# ── _parse_wifi_string ────────────────────────────────────────────────────

class TestParseWifiString:
    """Parse the WIFI: text format used on NFC tags."""

    def test_standard_format(self):
        result = _parse_wifi_string("WIFI:T:WPA;S:MyNetwork;P:MyPassword;;")
        assert result == {
            "type": "wifi",
            "ssid": "MyNetwork",
            "password": "MyPassword",
            "security": "WPA",
            "hidden": False,
        }

    def test_different_field_order(self):
        result = _parse_wifi_string("WIFI:S:TestSSID;T:WPA2;P:secret123;;")
        assert result is not None
        assert result["ssid"] == "TestSSID"
        assert result["password"] == "secret123"
        assert result["security"] == "WPA2"

    def test_case_insensitive_prefix(self):
        result = _parse_wifi_string("wifi:S:TestNet;T:WPA;P:pass;;")
        assert result is not None
        assert result["ssid"] == "TestNet"

    def test_open_network_no_password(self):
        result = _parse_wifi_string("WIFI:S:OpenNet;T:nopass;;")
        assert result is not None
        assert result["ssid"] == "OpenNet"
        assert result["password"] == ""
        assert result["security"] == "nopass"

    def test_hidden_network(self):
        result = _parse_wifi_string("WIFI:S:HiddenNet;T:WPA;P:secret;H:true;;")
        assert result is not None
        assert result["hidden"] is True

    def test_hidden_false(self):
        result = _parse_wifi_string("WIFI:S:Net;T:WPA;P:pass;H:false;;")
        assert result is not None
        assert result["hidden"] is False

    def test_escaped_semicolon_in_values(self):
        result = _parse_wifi_string("WIFI:S:My\\;Network;T:WPA;P:pass\\;word;;")
        assert result is not None
        assert result["ssid"] == "My;Network"
        assert result["password"] == "pass;word"

    def test_escaped_colon_in_ssid(self):
        result = _parse_wifi_string("WIFI:S:Net\\:work;T:WPA;P:pass;;")
        assert result is not None
        assert result["ssid"] == "Net:work"

    def test_escaped_backslash(self):
        result = _parse_wifi_string("WIFI:S:Net\\\\work;T:WPA;P:pass;;")
        assert result is not None
        assert result["ssid"] == "Net\\work"

    def test_empty_ssid_returns_none(self):
        assert _parse_wifi_string("WIFI:T:WPA;P:pass;;") is None

    def test_not_wifi_returns_none(self):
        assert _parse_wifi_string("https://example.com") is None
        assert _parse_wifi_string("") is None
        assert _parse_wifi_string("NOTAWIFI:string") is None

    def test_only_ssid(self):
        result = _parse_wifi_string("WIFI:S:SimpleNet;;")
        assert result is not None
        assert result["ssid"] == "SimpleNet"
        assert result["password"] == ""
        assert result["security"] == "WPA"  # default

    def test_whitespace_stripped(self):
        result = _parse_wifi_string("  WIFI:S:Net;T:WPA;P:pass;;  ")
        assert result is not None
        assert result["ssid"] == "Net"


# ── _extract_tag_data ─────────────────────────────────────────────────────

def _make_ndef_tlv(records):
    """Helper: wrap NDEF records in a TLV container (as stored on NTAG2xx)."""
    import ndef
    message = b"".join(ndef.message_encoder(records))
    if len(message) < 0xFF:
        return b"\x03" + bytes([len(message)]) + message
    return b"\x03\xFF" + len(message).to_bytes(2, "big") + message


class TestExtractTagData:
    """Test unified NDEF extraction for WiFi and Spotify records."""

    def test_spotify_uri_record(self):
        import ndef
        record = ndef.UriRecord("https://open.spotify.com/track/abc123")
        result = _extract_tag_data(_make_ndef_tlv([record]))
        assert result is not None
        assert result["type"] == "spotify"
        assert result["uri"] == "spotify:track:abc123"

    def test_spotify_text_record(self):
        import ndef
        record = ndef.TextRecord("https://open.spotify.com/playlist/xyz789")
        result = _extract_tag_data(_make_ndef_tlv([record]))
        assert result is not None
        assert result["type"] == "spotify"
        assert result["uri"] == "spotify:playlist:xyz789"

    def test_wifi_text_record(self):
        import ndef
        record = ndef.TextRecord("WIFI:S:TestNet;T:WPA;P:password123;;")
        result = _extract_tag_data(_make_ndef_tlv([record]))
        assert result is not None
        assert result["type"] == "wifi"
        assert result["ssid"] == "TestNet"
        assert result["password"] == "password123"

    def test_wifi_takes_priority_over_spotify(self):
        """If a tag has both WiFi and Spotify records, WiFi wins."""
        import ndef
        wifi = ndef.TextRecord("WIFI:S:Net;T:WPA;P:pass;;")
        spotify = ndef.UriRecord("https://open.spotify.com/track/abc123")
        result = _extract_tag_data(_make_ndef_tlv([wifi, spotify]))
        assert result["type"] == "wifi"

    def test_non_spotify_url_returns_none(self):
        import ndef
        record = ndef.UriRecord("https://example.com/something")
        result = _extract_tag_data(_make_ndef_tlv([record]))
        assert result is None

    def test_empty_data_returns_none(self):
        assert _extract_tag_data(b"") is None

    def test_garbage_data_returns_none(self):
        assert _extract_tag_data(b"\xff\xff\xff\xff") is None

    def test_raw_ndef_without_tlv(self):
        """NDEF message without TLV wrapper should also work."""
        import ndef
        record = ndef.UriRecord("https://open.spotify.com/album/def456")
        raw = b"".join(ndef.message_encoder([record]))
        result = _extract_tag_data(raw)
        assert result is not None
        assert result["type"] == "spotify"
        assert result["uri"] == "spotify:album:def456"

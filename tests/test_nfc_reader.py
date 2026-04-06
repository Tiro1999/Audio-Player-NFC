"""Tests for URI validation – runnable on any machine (no Pi hardware needed)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.nfc_reader import is_valid_spotify_uri, spotify_url_to_uri


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
    ])
    def test_valid_native_uris(self, uri):
        assert is_valid_spotify_uri(uri) is True

    @pytest.mark.parametrize("url", [
        "https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6",
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "http://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE",
        "https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF",
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

    def test_unknown_url_returns_none(self):
        assert spotify_url_to_uri("https://example.com/foo") is None
